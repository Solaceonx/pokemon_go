"""Local-only viewer server: scan the battle folder and support video seeking."""
import argparse
import hashlib
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from battle_library import scan_library, viewer_entry

ROOT = Path(__file__).resolve().parent


def server_fingerprint(root=ROOT):
    digest = hashlib.sha256()
    for name in ["serve_viewer.py", "battle_library.py"]:
        path = root / name
        digest.update(name.encode())
        if path.is_file(): digest.update(path.read_bytes())
    return digest.hexdigest()


def byte_range(header, size):
    if not header:
        return 0, size-1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match or not any(match.groups()):
        raise ValueError("Invalid range")
    a, b = match.groups()
    if not a:
        length = int(b)
        if length <= 0:
            raise ValueError("Invalid suffix")
        start, end = max(0, size-length), size-1
    else:
        start, end = int(a), min(int(b), size-1) if b else size-1
    if start >= size or start > end:
        raise ValueError("Unsatisfiable range")
    return start, end, True


def make_handler(project_root=ROOT, battle_root=None):
    project_root = Path(project_root).resolve()
    battle_root = Path(battle_root or project_root / "battles").resolve()
    version = server_fingerprint(project_root)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond(False)

        def do_HEAD(self):
            self.respond(True)

        def respond(self, head):
            route = unquote(urlsplit(self.path).path)
            if route == "/api/battles":
                entries = [viewer_entry(m, "/battles/") for m in scan_library(battle_root)]
                body = json.dumps({"schema": "battle-viewer-library-v1", "server_fingerprint": version, "sources": entries}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if not head:
                    self.wfile.write(body)
                return
            if route in ["/", "/battle_viewer.html"]:
                path = project_root / "battle_viewer.html"
            elif route.startswith("/battles/"):
                path = (battle_root / route.removeprefix("/battles/")).resolve()
                if not path.is_relative_to(battle_root):
                    self.send_error(403)
                    return
            else:
                self.send_error(404)
                return
            if not path.is_file():
                self.send_error(404)
                return
            size = path.stat().st_size
            try:
                start, end, partial = byte_range(self.headers.get("Range"), size)
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206 if partial else 200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(max(0, end-start+1)))
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if path.suffix in [".json", ".gz"]:
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head:
                try:
                    with path.open("rb") as stream:
                        stream.seek(start)
                        remaining = end-start+1
                        while remaining > 0:
                            block = stream.read(min(256*1024, remaining))
                            if not block:
                                break
                            self.wfile.write(block)
                            remaining -= len(block)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    pass

        def log_message(self, *_args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--battles", type=Path, default=ROOT / "battles")
    parser.add_argument("--connection-file", type=Path)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(battle_root=args.battles))
    url = f"http://127.0.0.1:{server.server_port}"
    if args.connection_file:
        temporary = args.connection_file.with_suffix(".incomplete.json")
        temporary.write_text(json.dumps({"url": url, "server_fingerprint": server_fingerprint()}), encoding="utf-8")
        temporary.replace(args.connection_file)
    print(f"Battle viewer: {url}/\nBattle folder: {args.battles.resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
