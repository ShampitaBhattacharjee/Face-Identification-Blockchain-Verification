# Sample images

Put the photo you want to run through the pipeline in this folder, e.g. `samples/photo.jpg`.

**Use your own photo, or one you have explicit consent to process.** The pipeline performs
biometric processing (face encoding) and looks the face up across public web content. Do not
run it on other people's photos without permission.

Tips for a strong demo:

- Reverse-image search finds *the same or a very similar photograph* online. Use a photo that
  you have actually posted publicly (your X/Instagram/LinkedIn profile picture is ideal).
- Front-facing, well lit, single person, at least 400 px across the face.
- JPEG or PNG. EXIF orientation is honoured automatically.
- If the full photo gives no social match, retry with `--use-crop` to search the face crop.

No images are committed to this repository on purpose (privacy + repo size).
