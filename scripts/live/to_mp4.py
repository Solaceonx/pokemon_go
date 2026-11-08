#!/usr/bin/env python3
"""Turn a battle recorded by pogo.android (<name>.h264 + <name>.times) into a normal video file, <name>.mp4.

    python3 scripts/live/to_mp4.py RECORDING [RECORDING ...]     (with or without the .h264 ending)

The stream is copied, not re-encoded; each frame keeps the time it arrived at, so the video plays at the speed the
battle was played and lines up with the game log (runs/live/*.jsonl). Videos stay out of git.
"""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path


def convert(base: Path) -> Path:
    import av
    base = base.with_suffix("") if base.suffix == ".h264" else base
    times = [float(x) for x in Path(f"{base}.times").read_text().split()]
    out_path = Path(f"{base}.mp4")
    with av.open(f"{base}.h264", format="h264") as inp, av.open(str(out_path), "w") as out:
        src = inp.streams.video[0]
        dst = out.add_stream_from_template(src)
        dst.time_base = Fraction(1, 1000)
        k, last = 0, -1
        for packet in inp.demux(src):
            if packet.size == 0:
                continue
            when = times[min(k, len(times) - 1)]
            pts = max(last + 1, int(round((when - times[0]) * 1000)))
            packet.stream, packet.time_base, packet.pts, packet.dts = dst, Fraction(1, 1000), pts, pts
            out.mux(packet)
            k, last = k + 1, pts
    return out_path


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(convert(Path(arg)))
