"""Check real browser playback and synchronization in local-server/file modes."""
import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import threading

from serve_viewer import ROOT, make_handler


def verify(mode="server", battles=None, empty=False):
    chrome = shutil.which("chrome") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    node = shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
    library = Path(battles) if battles else ROOT / "battles"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(battle_root=library))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    profile = ROOT / "tools/viewer-browser-profile"
    browser = subprocess.Popen([chrome, "--headless=new", "--remote-debugging-port=9247",
        "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
        "--autoplay-policy=no-user-gesture-required", "--disable-infobars",
        "--user-data-dir="+str(profile), "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    page = f"http://127.0.0.1:{server.server_port}/" if mode == "server" else str(ROOT / "battle_viewer.html")
    try:
        script = "test_empty_viewer.mjs" if empty else "test_viewer.mjs"
        result = subprocess.run([node, str(ROOT / script), "9247", page,
            str(ROOT / f"output/viewer-{mode}-verified.png"), str(library)],
            capture_output=True, text=True, timeout=60)
        print(result.stdout, end="")
        if result.stderr: print(result.stderr, end="")
        if result.returncode: raise RuntimeError("Browser verification failed")
    finally:
        browser.terminate()
        try: browser.wait(timeout=5)
        except subprocess.TimeoutExpired:
            browser.kill(); browser.wait(timeout=5)
        server.shutdown(); server.server_close(); worker.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["server", "file"], default="server")
    parser.add_argument("--battles", type=Path, help="Existing local library for server-mode playback checks")
    parser.add_argument("--empty", action="store_true", help="Verify the empty-checkout viewer")
    args = parser.parse_args()
    if args.battles and args.mode == "file": parser.error("An external library requires server mode")
    from build_lazy_viewer import build
    (ROOT / "output").mkdir(exist_ok=True)
    build(args.battles)
    verify(args.mode, args.battles, args.empty)
