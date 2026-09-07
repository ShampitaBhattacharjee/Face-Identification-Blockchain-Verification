"""Stage 1: face detection and encoding.

Encoder preference order:
  1. face_recognition (dlib ResNet, 128-d)  - best quality
  2. deepface Facenet (128-d)               - if dlib is not installed
  3. OpenCV Haar cascade + normalised pixels - detection-only fallback; the
     256-d vector is NOT a biometric template and is labelled as such.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from faceid.hashing import embedding_hash, sha256_file

log = logging.getLogger(__name__)

Box = tuple[int, int, int, int]  # (top, right, bottom, left) - dlib convention
EncoderResult = tuple[list[Box], Box | None, np.ndarray | None]


class NoFaceFoundError(RuntimeError):
    """Raised when no encoder could find a face in the image."""


@dataclass
class FaceResult:
    image_path: Path
    crop_path: Path
    box: Box
    num_faces: int
    encoder: str
    embedding: np.ndarray = field(repr=False)
    image_hash: str = ""
    embedding_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        top, right, bottom, left = self.box
        return {
            "image_path": str(self.image_path),
            "crop_path": str(self.crop_path),
            "box": {"top": top, "right": right, "bottom": bottom, "left": left},
            "num_faces": self.num_faces,
            "encoder": self.encoder,
            "embedding_dim": int(self.embedding.size),
            "image_hash": self.image_hash,
            "embedding_hash": self.embedding_hash,
        }


def load_rgb(path: Path) -> np.ndarray:
    """Load an image as an RGB uint8 array, honouring EXIF orientation."""
    from PIL import Image, ImageOps

    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        return np.asarray(img)


def _area(box: Box) -> int:
    top, right, bottom, left = box
    return max(0, bottom - top) * max(0, right - left)


def _largest(boxes: list[Box]) -> Box:
    return max(boxes, key=_area)


def _with_face_recognition(rgb: np.ndarray) -> EncoderResult:
    import face_recognition

    boxes: list[Box] = [
        (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
        for b in face_recognition.face_locations(rgb, model="hog")
    ]
    if not boxes:
        return [], None, None
    box = _largest(boxes)
    encodings = face_recognition.face_encodings(rgb, known_face_locations=[box], num_jitters=1)
    if not encodings:
        return boxes, None, None
    return boxes, box, np.asarray(encodings[0], dtype=np.float64)


def _with_deepface(rgb: np.ndarray) -> EncoderResult:
    from deepface import DeepFace

    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    try:
        reps = DeepFace.represent(
            img_path=bgr, model_name="Facenet", enforce_detection=True, detector_backend="opencv"
        )
    except ValueError:  # deepface raises ValueError when no face is found
        return [], None, None
    boxes: list[Box] = []
    embeddings: list[np.ndarray] = []
    for rep in reps:
        area = rep["facial_area"]
        boxes.append(
            (
                int(area["y"]),
                int(area["x"] + area["w"]),
                int(area["y"] + area["h"]),
                int(area["x"]),
            )
        )
        embeddings.append(np.asarray(rep["embedding"], dtype=np.float64))
    if not boxes:
        return [], None, None
    idx = max(range(len(boxes)), key=lambda i: _area(boxes[i]))
    return boxes, boxes[idx], embeddings[idx]


def _with_opencv(rgb: np.ndarray) -> EncoderResult:
    import cv2

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    boxes: list[Box] = [(int(y), int(x + w), int(y + h), int(x)) for (x, y, w, h) in faces]
    if not boxes:
        return [], None, None
    box = _largest(boxes)
    top, right, bottom, left = box
    face = cv2.resize(gray[top:bottom, left:right], (16, 16), interpolation=cv2.INTER_AREA)
    face = face.astype(np.float64)
    face = (face - face.mean()) / (face.std() + 1e-8)
    return boxes, box, face.flatten()


ENCODERS: list[tuple[str, Callable[[np.ndarray], EncoderResult]]] = [
    ("face_recognition (dlib ResNet, 128-d)", _with_face_recognition),
    ("deepface (Facenet, 128-d)", _with_deepface),
    ("opencv-haar + normalised pixels (256-d, NOT a biometric embedding)", _with_opencv),
]


def _save_crop(rgb: np.ndarray, box: Box, out_path: Path, pad_ratio: float) -> Path:
    from PIL import Image

    h, w = rgb.shape[:2]
    top, right, bottom, left = box
    pad_y = int((bottom - top) * pad_ratio)
    pad_x = int((right - left) * pad_ratio)
    top, bottom = max(0, top - pad_y), min(h, bottom + pad_y)
    left, right = max(0, left - pad_x), min(w, right + pad_x)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb[top:bottom, left:right]).save(out_path)
    return out_path


def detect_face(
    image_path: str | Path, output_dir: str | Path, pad_ratio: float = 0.25
) -> FaceResult:
    """Detect the most prominent face, encode it, save a padded crop and hash everything.

    Raises:
        FileNotFoundError: the image does not exist.
        NoFaceFoundError: every available encoder found zero faces.
        RuntimeError: no encoder library is installed at all.
    """
    image_path = Path(image_path)
    if not image_path.is_file():
        raise FileNotFoundError(f"Input image not found: {image_path}")
    output_dir = Path(output_dir)
    rgb = load_rgb(image_path)

    tried: list[str] = []
    import_errors: list[str] = []
    for name, encoder in ENCODERS:
        try:
            boxes, box, embedding = encoder(rgb)
        except ImportError as exc:
            log.warning("Encoder %s unavailable (%s); trying next", name, exc)
            import_errors.append(f"{name}: {exc}")
            continue
        tried.append(name)
        if box is None or embedding is None:
            log.warning("Encoder %s found no face; trying next", name)
            continue
        if len(boxes) > 1:
            log.warning("%d faces found; using the largest one", len(boxes))
        crop_path = _save_crop(rgb, box, output_dir / f"{image_path.stem}_face.png", pad_ratio)
        return FaceResult(
            image_path=image_path,
            crop_path=crop_path,
            box=box,
            num_faces=len(boxes),
            encoder=name,
            embedding=embedding,
            image_hash=sha256_file(image_path),
            embedding_hash=embedding_hash(embedding),
        )

    if not tried:
        raise RuntimeError(
            "No face encoder is installed. Run `pip install -r requirements.txt` "
            "(face_recognition/dlib) or at least `pip install opencv-python-headless`.\n  "
            + "\n  ".join(import_errors)
        )
    raise NoFaceFoundError(
        f"No face detected in {image_path} (tried: {', '.join(tried)}). "
        "Use a clear, front-facing, well-lit photo."
    )
