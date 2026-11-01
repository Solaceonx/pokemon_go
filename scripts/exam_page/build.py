#!/usr/bin/env python3
"""The exam page: scripts/exam_page/template.html with the positions of data/exam/<tag>.json in it.

    python3 scripts/exam_page/build.py OUT.html [--tag exam-1]
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("out")
parser.add_argument("--tag", default="exam-1")
args = parser.parse_args()
positions = json.loads((ROOT / "data" / "exam" / f"{args.tag}.json").read_text())
page = (Path(__file__).parent / "template.html").read_text()
Path(args.out).write_text(page.replace("/*POSITIONS*/", json.dumps(positions, separators=(",", ":")).replace("</", "<\\/")))
print(args.out, f"{len(positions)} positions")
