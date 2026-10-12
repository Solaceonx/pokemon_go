"""Reconstruct reference-frame geometry from exact stored phone-crop pixels."""
import hashlib
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent


def load_image(path):
    name = Path(path).relative_to(ROOT).as_posix()
    entry = json.loads((ROOT / "fixtures/test-images.json").read_text(encoding="utf-8"))["images"][name]
    stored = ROOT / entry["stored_file"]
    if hashlib.sha256(stored.read_bytes()).hexdigest() != entry["stored_png_sha256"]:
        raise ValueError("Reference image changed: " + name)
    with Image.open(stored) as image:
        crop = image.convert("RGB")
    if hashlib.sha256(crop.tobytes()).hexdigest() != entry["crop_pixel_sha256"]:
        raise ValueError("Reference pixels changed: " + name)
    canvas = Image.new("RGB", entry["original_size"])
    canvas.paste(crop, entry["crop_bounds"][:2])
    return canvas
