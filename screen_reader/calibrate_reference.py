"""Create an explicitly labeled profile from selected HomeSliceHenry frames."""
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "profiles"


def main():
    OUT.mkdir(exist_ok=True)
    labels = []
    entries = [
        (119, "Fusion Bolt", (90, 923, 206, 942)),
        (119, "Outrage", (313, 923, 410, 942)),
        (190, "Origin Pulse", (88, 923, 210, 942)),
        (190, "Avalanche", (304, 923, 417, 942)),
        (420, "Dynamax Cannon", (59, 893, 239, 916)),
        (420, "Sludge Bomb", (296, 893, 433, 916)),
    ]
    for t, name, region in entries:
        filename = name.lower().replace(" ", "-")+".png"
        with Image.open(ROOT / "samples" / f"henry-{t}.png") as source:
            phone = source.crop((706, 0, 1214, 1080))
            phone.crop(region).save(OUT / filename)
        labels.append({"name": name, "file": filename})
    with Image.open(ROOT / "samples/henry-300.png") as source:
        source.crop((706+128, 849, 706+380, 878)).save(OUT / "replacement-prompt.png")
    profile = {"id": "henry-2NnWi8jWDJ8-v1", "width": 508, "height": 1080,
               "source_video": "https://www.youtube.com/watch?v=2NnWi8jWDJ8",
               "calibration_seconds": [119, 190, 300, 420],
               "device": "Android footage; not calibrated for the user's iPhone",
               "labels": labels, "replacement_label": "replacement-prompt.png"}
    (OUT / "henry.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
