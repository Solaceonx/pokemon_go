#!/usr/bin/env python3
"""The creators' accuracy, as the battle page scores our live battles: at each of the creator exam's checked decisions
(scripts/lab/creator_exam.py: switch, shield, throw, hold in task 46's records), the win share given up against the
best choice, from the exam's cached play-outs (every legal choice played to the end 100 times), turned into a chess
site's accuracy (103.1668 exp(-0.04354 lost) - 3.1669, 0 to 100) and averaged. Losses under --noise (10 points) are
counted as none, as the battle review counts only differences beyond its margin. The same for engines' answers on the
same decisions, so the numbers compare like with like.

    python3 scripts/lab/creator_accuracy.py [--opponent people crowd] [--engines website bot] [--out FILE.json]

The judge is our simulator continued by our bot, which favours choices like the bot's: read the creators' numbers as
"how close to the best by our simulator", not as how good their play is against people.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import types
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "lab"))
if importlib.util.find_spec("cv2") is None:
    sys.modules["cv2"] = types.ModuleType("cv2")
EXAM = ROOT / "runs" / "lab-creators" / "exam"
NAMES = {"website": "today's website engine (32 imagined battles, 20 steps on)", "bot": "the trained bot alone",
         "website,judge=turn,horizon=40": "today's live engine (judged 40 turns on)"}


def accuracy(lost: float) -> float:
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * lost) - 3.1669))


def mean_margin(xs: list) -> tuple:
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / max(1, n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def main() -> None:
    import creator_exam as ce
    ap = argparse.ArgumentParser()
    ap.add_argument("--opponent", nargs="+", default=["people", "crowd"])
    ap.add_argument("--engines", nargs="+", default=["website", "bot"])
    ap.add_argument("--noise", type=float, default=10.0, help="win-share points under which a loss counts as none")
    ap.add_argument("--out")
    a = ap.parse_args()
    pts = ce.decision_set()
    answers = {e: ce.load(EXAM / f"answers-{ce.slug(e)}-s1.json") for e in a.engines}
    out = {"about": "Creators' and engines' accuracy on the creator exam's decisions (scripts/lab/creator_accuracy.py)",
           "noise": a.noise, "decisions": len(pts), "tables": {}}
    for opp in a.opponent:
        values = ce.load(EXAM / f"values-{opp}-g100-s1.json")
        rows = defaultdict(list)  # (who, kind) -> accuracies; who: a creator's channel, or an engine
        for d in pts:
            v = values.get(d["key"])
            if not v or str(d["human"]) not in v:
                continue
            best = max(v.values())
            def acc_of(choice_values: list) -> float:
                lost = 100 * (best - sum(choice_values) / len(choice_values))
                return accuracy(lost if lost >= a.noise else 0.0)
            ok = True
            per = {"player": acc_of([v[str(d["human"])]])}
            for e in a.engines:
                got = answers[e].get(d["key"])
                valued = [v[str(c)] for c in (got or {}).get("choices", []) if str(c) in v]
                if not valued:
                    ok = False
                    break
                per[e] = acc_of(valued)
            if not ok:
                continue  # only decisions every engine answered, so all rows are on the same decisions
            for who, x in per.items():
                for kind in (d["kind"], "all"):
                    rows[(who, kind)].append(x)
                    if who == "player":
                        rows[(d["channel"], kind)].append(x)
        table = {}
        for (who, kind), xs in sorted(rows.items()):
            m, e = mean_margin(xs)
            table.setdefault(who, {})[kind] = {"accuracy": round(m, 1), "margin": round(e, 1), "n": len(xs)}
        out["tables"][opp] = table
        print(f"== judged against {opp} opponents (100 play-outs a choice; losses under {a.noise:g} points as none)")
        for who in ["player"] + sorted(k for k in table if k not in ["player", *a.engines]) + a.engines:
            if who not in table:
                continue
            t = table[who]
            label = "the creators" if who == "player" else NAMES.get(who, who)
            print(f"  {label:58} all {t['all']['accuracy']:5.1f} ± {t['all']['margin']:.1f} (n {t['all']['n']}) | "
                  + ", ".join(f"{k} {t[k]['accuracy']:.1f}" for k in ("switch", "shield", "throw", "hold") if k in t))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
