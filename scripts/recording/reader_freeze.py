"""Read-only verification of the Task46 collection reader snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def verify(root: Path, manifest: dict) -> dict:
    """Check processing and external reader bytes, failing closed on missing files."""
    root = root.resolve()
    expected = dict(manifest.get("files_sha256", {}))
    expected.update(manifest["processing_sha256"])
    for name, digest in manifest["external_reader_files_sha256"].items():
        expected["screen_reader/" + name] = digest
    failures = []
    for name, digest in expected.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            failures.append({"file": name, "reason": "outside_snapshot"})
            continue
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            failures.append({"file": name, "reason": "missing_or_unreadable"})
            continue
        if actual != digest:
            failures.append({"file": name, "reason": "changed"})
    return {"schema": "task46-reader-freeze-check-v1", "reader_version": manifest["reader_version"],
            "commit": manifest["commit"], "files_checked": len(expected),
            "unchanged": not failures, "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.root, json.loads(args.manifest.read_text(encoding="utf-8-sig")))
    print(json.dumps(result, indent=2))
    if not result["unchanged"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
