"""See and touch the iPhone through the iPhone Mirroring window.

A thin wrapper around bin/phonectl. Positions are fractions of the mirroring
window: (0, 0) is the top-left corner and (1, 1) the bottom-right.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "bin" / "phonectl"
CAPTURES = ROOT / "captures"


class PhoneError(RuntimeError):
    pass


@dataclass(frozen=True)
class Text:
    """One line of text read off the screen, with its box as screen fractions."""

    text: str
    conf: float
    x: float
    y: float
    w: float
    h: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)


@dataclass
class Shot:
    image: Image.Image
    path: Path
    text: list[Text]
    capture_ms: float
    ocr_ms: float | None

    def find(self, pattern: str) -> list[Text]:
        """Lines of text matching a regular expression, ignoring case."""
        rx = re.compile(pattern, re.IGNORECASE)
        return [t for t in self.text if rx.search(t.text)]


class Phone:
    def __init__(self, helper: Path = HELPER, dry_run: bool = False, max_actions: int | None = None):
        if not Path(helper).exists():
            raise PhoneError(f"{helper} is missing; run ./build.sh first")
        self.helper = Path(helper)
        self.dry_run = dry_run
        self.max_actions = max_actions
        self.actions = 0

    def _call(self, *args) -> dict:
        proc = subprocess.run([str(self.helper), *map(str, args)], capture_output=True, text=True)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise PhoneError(proc.stderr.strip() or proc.stdout.strip() or f"phonectl exited {proc.returncode}")
        if "error" in out:
            raise PhoneError(out["error"])
        return out

    def _act(self, *args) -> dict:
        """Send one input action, honouring the dry-run switch and the action cap."""
        if self.max_actions is not None and self.actions >= self.max_actions:
            raise PhoneError(f"action cap of {self.max_actions} reached")
        self.actions += 1
        if self.dry_run:
            print("dry run:", *args)
            return {"ok": True, "dry_run": True}
        return self._call(*args)

    # looking

    def doctor(self, request: bool = False) -> dict:
        return self._call("doctor", *(["--request"] if request else []))

    def shot(self, ocr: bool = False, fast: bool = False, path: Path | None = None) -> Shot:
        if path is None:
            CAPTURES.mkdir(exist_ok=True)
            path = CAPTURES / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000_000:09d}.png"
        flags = (["--ocr"] if ocr else []) + (["--fast"] if fast else [])
        out = self._call("shot", path, *flags)
        return Shot(
            image=Image.open(path).convert("RGB"),
            path=Path(path),
            text=[Text(**t) for t in out.get("text", [])],
            capture_ms=out["capture_ms"],
            ocr_ms=out.get("ocr_ms"),
        )

    def ocr_file(self, path: Path, fast: bool = False) -> list[Text]:
        """Read text from a saved screenshot, so detection can be developed without the phone."""
        out = self._call("ocr-file", path, *(["--fast"] if fast else []))
        return [Text(**t) for t in out["text"]]

    # touching

    def tap(self, x: float, y: float) -> dict:
        return self._act("tap", f"{x:.4f}", f"{y:.4f}")

    def drag(self, x1: float, y1: float, x2: float, y2: float, ms: int = 300, hold_ms: int = 60) -> dict:
        return self._act("drag", f"{x1:.4f}", f"{y1:.4f}", f"{x2:.4f}", f"{y2:.4f}", ms, hold_ms)

    def scroll(self, x: float, y: float, dx: int, dy: int) -> dict:
        return self._act("scroll", f"{x:.4f}", f"{y:.4f}", dx, dy)
