#!/usr/bin/env python3
"""The exam page: scripts/exam_page/template.html with the positions of data/exam/<tag>.json in it.

    python3 scripts/exam_page/build.py OUT.html [--tag exam-1]            for an Artifact: answers in its db
    python3 scripts/exam_page/build.py OUT.html [--tag exam-1] --site     for the website: a whole page, answers sent to the
                                                                          game store (read back by scripts/import_played.py --store)
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("out")
parser.add_argument("--tag", default="exam-1")
parser.add_argument("--site", action="store_true")
args = parser.parse_args()
positions = json.loads((ROOT / "data" / "exam" / f"{args.tag}.json").read_text())
page = (Path(__file__).parent / "template.html").read_text()
page = page.replace("/*POSITIONS*/", json.dumps(positions, separators=(",", ":")).replace("</", "<\\/"))
if args.site:  # the store's address is public: the game page already carries it
    url = re.search(r'STORE_URL = "(https://[^"]+)"', (ROOT / "scripts" / "pvpbot_site" / "play_controller.js").read_text()).group(1)
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            "<style>:root{color-scheme:light}body{margin:0;font:14px system-ui}[hidden]{display:none!important}</style></head><body>"
            + page.replace("/*STORE_URL*/", url) + "</body></html>")
Path(args.out).write_text(page)
print(args.out, f"{len(positions)} positions")
