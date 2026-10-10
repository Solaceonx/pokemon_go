"""Open the local library viewer, starting a hidden local server when needed."""
import json
import re
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from serve_viewer import server_fingerprint

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765"


def connection_url():
    path = ROOT / "output/viewer-server.json"
    try:
        url = json.loads(path.read_text(encoding="utf-8"))["url"]
        if re.fullmatch(r"http://127\.0\.0\.1:\d{1,5}", url): return url
    except (OSError, ValueError, KeyError): pass
    return URL


def ready(url=None):
    try:
        with urllib.request.urlopen((url or connection_url())+"/api/battles", timeout=1) as response:
            data = json.load(response)
            return data.get("schema") == "battle-viewer-library-v1" and data.get("server_fingerprint") == server_fingerprint(ROOT)
    except (OSError, ValueError):
        return False


def main():
    if not ready():
        output = ROOT / "output"
        output.mkdir(exist_ok=True)
        with (output / "viewer-server.log").open("a", encoding="utf-8") as log:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            child = subprocess.Popen([sys.executable, str(ROOT / "serve_viewer.py"), "--port", "0",
                                      "--connection-file", str(output / "viewer-server.json")],
                                     cwd=ROOT, stdout=log, stderr=log, creationflags=flags)
        for _ in range(50):
            if ready():
                break
            if child.poll() is not None:
                raise RuntimeError("Viewer server could not start; see output/viewer-server.log")
            time.sleep(0.1)
        else:
            child.terminate()
            raise RuntimeError("Viewer server did not start")
    webbrowser.open(connection_url())


if __name__ == "__main__":
    main()
