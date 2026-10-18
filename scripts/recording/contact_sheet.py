#!/usr/bin/env python3
"""Frames from a recording at given times, side by side in one image, with each time written on it.

    .reader/py312/bin/python scripts/recording/contact_sheet.py VIDEO OUT.png 21.5 22.0 27.0 [--width 240] [--columns 6]

For measuring where things are on the battle screen (pogo.controls). Needs the reader's Python (av, opencv).
A grid of light lines every tenth of the width and height helps read positions off as screen fractions.
"""
import argparse

import av
import cv2
import numpy as np


def frame_at(container, stream, seconds: float) -> np.ndarray:
    container.seek(int(seconds / stream.time_base), stream=stream, any_frame=False, backward=True)
    best = None
    for frame in container.decode(stream):
        t = float(frame.pts * stream.time_base)
        best = frame
        if t >= seconds:
            break
    return best.to_ndarray(format="rgb24")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("out")
    parser.add_argument("times", nargs="+", type=float)
    parser.add_argument("--width", type=int, default=240)
    parser.add_argument("--columns", type=int, default=6)
    parser.add_argument("--grid", action="store_true", help="draw lines every tenth of the screen")
    args = parser.parse_args()
    container = av.open(args.video)
    stream = container.streams.video[0]
    tiles = []
    for t in args.times:
        img = frame_at(container, stream, t)
        h, w = img.shape[:2]
        small = cv2.resize(img, (args.width, int(h * args.width / w)), interpolation=cv2.INTER_AREA)
        if args.grid:
            sh, sw = small.shape[:2]
            for k in range(1, 10):
                small[int(sh * k / 10), :] = (small[int(sh * k / 10), :] * 0.4 + 255 * 0.6).astype(np.uint8)
                small[:, int(sw * k / 10)] = (small[:, int(sw * k / 10)] * 0.4 + 255 * 0.6).astype(np.uint8)
        cv2.putText(small, f"{t:.1f}s", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        tiles.append(small)
    rows = [tiles[i:i + args.columns] for i in range(0, len(tiles), args.columns)]
    height = tiles[0].shape[0]
    blank = np.zeros_like(tiles[0])
    sheet = np.vstack([np.hstack(r + [blank] * (args.columns - len(r))) for r in rows])
    cv2.imwrite(args.out, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR))
    print(f"{args.out}: {len(tiles)} frames, {sheet.shape[1]}x{sheet.shape[0]}")


if __name__ == "__main__":
    main()
