"""Deterministic hashing helpers shared by every pipeline stage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of `data`."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Stream a file through SHA-256 (works for large images)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def embedding_hash(embedding: Iterable[float], decimals: int = 6) -> str:
    """Hash a face-embedding vector in a stable way.

    Floating point noise below 10^-decimals is rounded away so the same face
    encoded twice on the same machine yields an identical hash.
    """
    rounded = [round(float(x), decimals) for x in embedding]
    payload = json.dumps(rounded, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def normalise_hex(value: str) -> str:
    """Strip an optional 0x prefix and lowercase, for hash comparisons."""
    value = value.strip()
    if value.lower().startswith("0x"):
        value = value[2:]
    return value.lower()


def to_bytes32(hex_digest: str) -> bytes:
    """Convert a 64-char hex digest (with or without 0x) to 32 raw bytes for Solidity."""
    raw = bytes.fromhex(normalise_hex(hex_digest))
    if len(raw) != 32:
        raise ValueError(f"Expected a 32-byte digest, got {len(raw)} bytes")
    return raw
