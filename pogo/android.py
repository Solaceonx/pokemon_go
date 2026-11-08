"""See and touch an Android phone over USB through scrcpy (docs/tasks.md, task 40).

The same interface as pogo.phone.Phone (positions are shares of the screen: (0, 0) top-left, (1, 1) bottom-right),
with its dry run and action cap. Frames come from scrcpy's video stream, decoded here as they arrive (adb's screencap
takes hundreds of milliseconds a frame); touches go through scrcpy's control channel, so a minigame swipe is one
unbroken, fast stroke.

    phone = Android(serial="ZY22JPBNMW")   # scrcpy's folder from $POGO_SCRCPY_DIR, or adb/scrcpy-server on PATH
    phone.start()
    rgb, when = phone.frame()               # the newest frame (height x width x 3) and when it arrived
    phone.tap(0.5, 0.45)
    phone.path([(0.2, 0.5), (0.8, 0.5)], ms=120)
    phone.close()

It runs scrcpy's own server (the scrcpy-server file shipped with scrcpy for Windows); its version must match
SERVER_VERSION. Nothing on the phone is changed beyond that temporary file (no settings, no stay-awake).
"""
from __future__ import annotations

import os
import random
import shutil
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPTURES = ROOT / "captures"
SERVER_VERSION = "5.0.1"
DOWN, UP, MOVE = 0, 1, 2  # Android's MotionEvent actions
FINGER = -2  # scrcpy's generic finger pointer id


class PhoneError(RuntimeError):
    pass


def _tools(scrcpy_dir: str | None) -> tuple[str, str]:
    """adb and scrcpy-server: from scrcpy_dir, $POGO_SCRCPY_DIR, or PATH."""
    folder = scrcpy_dir or os.environ.get("POGO_SCRCPY_DIR")
    if folder:
        adb, server = Path(folder) / "adb.exe", Path(folder) / "scrcpy-server"
        if not adb.exists():
            adb = Path(folder) / "adb"
        if adb.exists() and server.exists():
            return str(adb), str(server)
    adb = shutil.which("adb")
    server = next((Path(p) / "scrcpy-server" for p in os.environ.get("PATH", "").split(os.pathsep)
                   if (Path(p) / "scrcpy-server").exists()), None)
    if not adb or not server:
        raise PhoneError("adb and scrcpy-server not found: set POGO_SCRCPY_DIR to scrcpy's folder")
    return adb, str(server)


def touch_message(action: int, x: int, y: int, width: int, height: int, pointer: int = FINGER) -> bytes:
    """scrcpy's inject-touch control message: positions in the video's pixels, with the video's size."""
    pressure = 0 if action == UP else 0xFFFF
    return struct.pack(">BBqiiHHHii", 2, action, pointer, x, y, width, height, pressure, 0, 0)


def stroke(points: list, ms: float, step_ms: float = 8.0) -> list[tuple[float, float, float]]:
    """(seconds from the start, x, y) along the polyline through points, evenly in distance, over ms."""
    if len(points) == 1:
        return [(0.0, *points[0])]
    lengths = [((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 for (x1, y1), (x2, y2) in zip(points, points[1:])]
    total = sum(lengths) or 1.0
    n = max(2, int(ms / step_ms) + 1)
    out = []
    for i in range(n):
        d, k = total * i / (n - 1), 0
        while k < len(lengths) - 1 and d > lengths[k]:
            d -= lengths[k]
            k += 1
        f = min(1.0, d / lengths[k]) if lengths[k] else 1.0
        (x1, y1), (x2, y2) = points[k], points[k + 1]
        out.append((ms / 1000 * i / (n - 1), x1 + (x2 - x1) * f, y1 + (y2 - y1) * f))
    return out


class Android:
    def __init__(self, serial: str | None = None, scrcpy_dir: str | None = None, max_size: int = 1200,
                 max_fps: int = 30, bit_rate: int = 8_000_000, port: int = 27199, dry_run: bool = False,
                 max_actions: int | None = None, record: str | Path | None = None):
        """record: also keep the screen as it arrives, the raw H.264 stream to <record>.h264 and each decoded
        frame's arrival time (seconds since the epoch) to <record>.times, for looking back at a battle."""
        self.serial, self.scrcpy_dir = serial, scrcpy_dir
        self._rec = open(f"{record}.h264", "wb") if record else None
        self._rec_times = open(f"{record}.times", "w") if record else None
        self.max_size, self.max_fps, self.bit_rate, self.port = max_size, max_fps, bit_rate, port
        self.dry_run, self.max_actions, self.actions = dry_run, max_actions, 0
        self._latest = None  # (av frame, arrival time)
        self._frames = 0
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._video = self._control = self._server = None
        self._running = False
        self.size = None  # (width, height) of the video

    # setting up

    def _adb(self, *args, check=True, **kw):
        adb, _ = _tools(self.scrcpy_dir)
        cmd = [adb] + (["-s", self.serial] if self.serial else []) + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, check=check, **kw)

    def doctor(self) -> dict:
        adb, server = _tools(self.scrcpy_dir)
        devices = self._adb("devices", "-l").stdout
        size = self._adb("shell", "wm", "size", check=False).stdout.strip()
        focus = self._adb("shell", "dumpsys window | grep mCurrentFocus", check=False).stdout.strip()
        return {"adb": adb, "server": server, "devices": devices.strip(), "size": size, "focus": focus}

    def start(self, timeout: float = 10.0) -> None:
        _, server = _tools(self.scrcpy_dir)
        self._adb("push", server, "/data/local/tmp/scrcpy-server.jar")
        scid = f"{random.getrandbits(31):08x}"
        self._adb("forward", f"tcp:{self.port}", f"localabstract:scrcpy_{scid}")
        adb, _ = _tools(self.scrcpy_dir)
        args = ["CLASSPATH=/data/local/tmp/scrcpy-server.jar", "app_process", "/", "com.genymobile.scrcpy.Server",
                SERVER_VERSION, f"scid={scid}", "log_level=warn", "tunnel_forward=true", "audio=false", "control=true",
                "video_codec=h264", f"max_size={self.max_size}", f"max_fps={self.max_fps}",
                f"video_bit_rate={self.bit_rate}", "send_device_meta=false", "send_frame_meta=false",
                "send_codec_meta=false", "send_dummy_byte=true", "cleanup=true", "clipboard_autosync=false",
                "power_off_on_close=false"]
        self._server = subprocess.Popen([adb] + (["-s", self.serial] if self.serial else []) + ["shell", *args],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + timeout
        while True:  # the forward accepts at once; the dummy byte says the server is really there
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
            try:
                if sock.recv(1):
                    break
            except OSError:
                pass
            sock.close()
            if time.time() > deadline:
                raise PhoneError("scrcpy's server did not answer: " + (self._server.stdout.read(2000) if self._server.poll() is not None else ""))
            time.sleep(0.1)
        sock.settimeout(None)
        self._video = sock
        self._control = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self._control.settimeout(None)
        self._running = True
        threading.Thread(target=self._decode, daemon=True).start()
        threading.Thread(target=self._drain, daemon=True).start()
        while self._latest is None:
            if time.time() > deadline:
                raise PhoneError("no video frame from the phone")
            time.sleep(0.02)

    def _decode(self) -> None:
        import av
        codec = av.CodecContext.create("h264", "r")
        codec.flags |= 1 << 19  # low delay: hand over each frame at once
        try:
            codec.thread_type = "SLICE"
        except Exception:  # noqa: BLE001
            pass
        while self._running:
            try:
                data = self._video.recv(1 << 16)
            except OSError:
                break
            if not data:
                break
            if self._rec:
                self._rec.write(data)
            for packet in codec.parse(data):
                for frame in codec.decode(packet):
                    now = time.time()
                    with self._lock:
                        self._latest = (frame, now)
                        self._frames += 1
                        self.size = (frame.width, frame.height)
                    if self._rec_times:
                        self._rec_times.write(f"{now:.3f}\n")
        self._running = False

    def _drain(self) -> None:  # device messages (clipboard and so on) on the control socket: read and dropped
        while self._running:
            try:
                if not self._control.recv(4096):
                    break
            except OSError:
                break

    def close(self) -> None:
        self._running = False
        for f in (self._rec, self._rec_times):
            if f:
                f.close()
        for s in (self._video, self._control):
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass
        if self._server and self._server.poll() is None:
            self._server.terminate()
        self._adb("forward", "--remove", f"tcp:{self.port}", check=False)

    # looking

    def frame(self):
        """The newest frame as an RGB array (height x width x 3), and the time it arrived."""
        with self._lock:
            if self._latest is None:
                raise PhoneError("no frame yet")
            frame, when = self._latest
        return frame.to_ndarray(format="rgb24"), when

    def next_frame(self, after: float, timeout: float = 1.0):
        """The first frame to arrive after time `after`."""
        deadline = time.time() + timeout
        while True:
            rgb, when = self.frame()
            if when > after or time.time() > deadline:
                return rgb, when
            time.sleep(0.005)

    @property
    def frames(self) -> int:
        return self._frames

    def shot(self, path: Path | None = None) -> Path:
        from PIL import Image
        if path is None:
            CAPTURES.mkdir(exist_ok=True)
            path = CAPTURES / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000_000:09d}.png"
        Image.fromarray(self.frame()[0]).save(path)
        return Path(path)

    # touching

    def _count(self, *what) -> bool:
        """One input action, honouring the action cap; False in dry run (nothing sent)."""
        if self.max_actions is not None and self.actions >= self.max_actions:
            raise PhoneError(f"action cap of {self.max_actions} reached")
        self.actions += 1
        if self.dry_run:
            print("dry run:", *what)
            return False
        return True

    def _send(self, action: int, x: float, y: float) -> None:
        w, h = self.size
        px, py = min(w - 1, max(0, round(x * w))), min(h - 1, max(0, round(y * h)))
        with self._send_lock:
            self._control.sendall(touch_message(action, px, py, w, h))

    def tap(self, x: float, y: float, hold_ms: float = 40) -> dict:
        if self._count("tap", f"{x:.4f}", f"{y:.4f}"):
            self._send(DOWN, x, y)
            time.sleep(hold_ms / 1000)
            self._send(UP, x, y)
        return {"ok": True}

    def path(self, points: list, ms: float = 300) -> dict:
        """One unbroken touch through every (x, y) point in `ms` milliseconds: a minigame swipe."""
        if self._count("path", ms, points):
            start = time.perf_counter()
            track = stroke(points, ms)
            self._send(DOWN, *track[0][1:])
            for when, x, y in track[1:]:
                wait = start + when - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
                self._send(MOVE, x, y)
            self._send(UP, *track[-1][1:])
        return {"ok": True}

    def drag(self, x1: float, y1: float, x2: float, y2: float, ms: int = 300, hold_ms: int = 60) -> dict:
        if self._count("drag", x1, y1, x2, y2, ms):
            self._send(DOWN, x1, y1)
            time.sleep(hold_ms / 1000)
            start = time.perf_counter()
            for when, x, y in stroke([(x1, y1), (x2, y2)], ms)[1:]:
                wait = start + when - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
                self._send(MOVE, x, y)
            self._send(UP, x2, y2)
        return {"ok": True}
