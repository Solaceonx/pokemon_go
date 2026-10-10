"""Lossless streaming IO for plain or gzip-compressed battle logs."""
import gzip
import json
from pathlib import Path


def open_log(path, mode="rt"):
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, mode, encoding="utf-8", compresslevel=6)
    return path.open(mode.replace("t", ""), encoding="utf-8")


def read_jsonl(path):
    with open_log(path) as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)
