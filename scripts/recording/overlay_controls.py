#!/usr/bin/env python3
"""Draw pogo.controls' touch positions onto frames of a recording, to check they land where they should.

    .reader/py312/bin/python scripts/recording/overlay_controls.py VIDEO OUT.png 22.3:battle 30.0:shield 89.9:replace

Screens: battle (fast move, both charged buttons, both bench portraits), shield (shield and "Not now"), replace (the
two choices after a faint) and replace1 (the single choice). Touch points are drawn as red rings with a label, the
keep-out zones (the flee button) in yellow. Needs the reader's Python (av, opencv).
"""
import sys
from pathlib import Path

import av
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
from contact_sheet import frame_at  # noqa: E402
from pogo import controls as c  # noqa: E402

SCREENS = {
    "battle": [("fast", c.FIELD), ("charged 1", c.CHARGED_BUTTONS[0]), ("charged 2", c.CHARGED_BUTTONS[1]),
               ("bench 1", c.BENCH[0]), ("bench 2", c.BENCH[1])],
    "shield": [("shield", c.SHIELD_YES), ("not now", c.SHIELD_NO)],
    "replace": [("left", c.REPLACE_TWO[0]), ("right", c.REPLACE_TWO[1])],
    "replace1": [("only", c.REPLACE_ONE)],
}


def main() -> None:
    video, out, *items = sys.argv[1:]
    container = av.open(video)
    stream = container.streams.video[0]
    tiles = []
    for item in items:
        t, screen = item.split(":")
        img = np.ascontiguousarray(frame_at(container, stream, float(t)))
        h, w = img.shape[:2]
        for (cx, cy), r in c.KEEP_OUT:
            cv2.circle(img, (int(cx * w), int(cy * h)), int(r * w), (255, 220, 0), 6)
        for label, (x, y) in SCREENS[screen]:
            p = (int(x * w), int(y * h))
            cv2.circle(img, p, int(0.035 * w), (255, 0, 0), 8)
            cv2.circle(img, p, 6, (255, 0, 0), -1)
            cv2.putText(img, label, (p[0] - int(0.08 * w), p[1] - int(0.045 * w)), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 0, 0), 4)
        cv2.putText(img, f"{t}s {screen}", (20, 140), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (255, 255, 0), 5)
        tiles.append(cv2.resize(img, (360, int(h * 360 / w)), interpolation=cv2.INTER_AREA))
    cv2.imwrite(out, cv2.cvtColor(np.hstack(tiles), cv2.COLOR_RGB2BGR))
    print(out)


if __name__ == "__main__":
    main()
