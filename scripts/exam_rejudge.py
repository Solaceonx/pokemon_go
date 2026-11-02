#!/usr/bin/env python3
"""The exam positions judged again with 400 play-outs, against the owner's answers (docs/benchmarking.md).

    python3 scripts/exam_rejudge.py
"""
import json, sys, multiprocessing, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.argv = ['x']; sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import exam_positions as E
from pogo.battle import Battle
from pogo.review import Logged, Replay

class Note:
    def __init__(self, inner, side, log): self.inner, self.side, self.log, self.step = inner, side, log, 0
    def act(self, v): self.log.append((self.side, v.turn, "act", self.step)); return self.inner.act(v)
    def shield(self, v, e, *m): self.log.append((self.side, v.turn, "shield", self.step)); return self.inner.shield(v, e)
    def replace(self, v): self.log.append((self.side, v.turn, "replace", self.step)); return self.inner.replace(v)
    def clone(self): return self

def step_of(k):
    saved, teams = E.load_game(ROOT / "games" / "played" / f"{k['game']}.json")
    log = []
    a, b = Note(Replay(saved["my_choices"]), 0, log), Note(Logged(saved["log"]), 1, log)
    battle = Battle(teams[0], teams[1], a, b, seed=saved["seed"], record=True)
    while battle.winner is None:
        a.step = b.step = battle.turn
        battle.step()
    want = {"throw": "act", "switch": "act", "shield": "shield", "replace": "replace"}[k["kind"]]
    return next(s for side, t, kind, s in log if side == k["side"] and t == k["turn"] and kind == want)

def job(k):
    pos = next(p for p in POS if p["id"] == k["id"])
    row = {**k, "step": step_of(k), "position": pos, "_id": k["id"]}
    return E.judge_job((row, 400))

POS = json.loads((ROOT / "data/exam/exam-1.json").read_text())
def init():
    E.setup()

if __name__ == "__main__":
    key = [k for k in json.loads((ROOT / "runs/exam/exam-1-key.json").read_text()) if k["group"] != "repeat"]
    A = json.loads((ROOT / "runs/exam/owner-answers.json").read_text())
    with multiprocessing.get_context("spawn").Pool(3, initializer=init) as pool:
        new = dict(pool.map(job, key, chunksize=1))
    (ROOT / "runs/exam/exam-1-judge400.json").write_text(json.dumps(new, indent=0))
    K = {k["id"]: k for k in key}
    moved = same = 0
    for i, j in new.items():
        if j is None: print("not forced", i); continue
        old = K[i]["judge"]
        same += max(old, key=old.get) == max(j, key=j.get); moved += 1
    print(f"judge's top choice unchanged from 48 to 400 play-outs: {same}/{moved}")
    ok = [i for i in new if new[i]]
    chance = sum(1 / len(new[i]) for i in ok) / len(ok)
    top = [i for i in ok if max(new[i], key=new[i].get) == A[i]["choice"]]
    print(f"judge top = owner: {len(top)}/{len(ok)} ({100*len(top)/len(ok):.0f}%); picking at random would match {100*chance:.0f}%")
    tied = [i for i in ok if new[i].get(A[i]["choice"], 0) >= max(new[i].values()) - 0.05]
    print(f"owner within 5 points of judge's top: {len(tied)}/{len(ok)}")
    bl = [i for i in ok if new[i].get(A[i]["choice"], 0) <= max(new[i].values()) - 0.25]
    print(f"judge calls owner's answer a blunder: {len(bl)}, sure {sum(A[i]['confidence']=='sure' for i in bl)}:", bl)
    fl = [i for i in ok if K[i]["group"] == "flagged"]
    print("flagged:", {i: (A[i]["choice"], K[i]["played"], {a: round(b, 2) for a, b in new[i].items()}) for i in fl})
    for v in ("rulebook", "trained", "engine", "matching"):
        print(v, "judge's top:", sum(max(new[i], key=new[i].get) == K[i]["picks"][v] for i in ok), "/", len(ok),
              " mean points below top:", round(100 * sum(max(new[i].values()) - new[i].get(K[i]["picks"][v], min(new[i].values())) for i in ok) / len(ok), 1))
    print("owner mean points below top:", round(100 * sum(max(new[i].values()) - new[i].get(A[i]["choice"], min(new[i].values())) for i in ok) / len(ok), 1))
    act = [k for k in key if k["kind"] in ("throw", "switch")]
    def kinds(pick): return collections.Counter({"f": "fast", "c": "throw", "s": "switch"}[pick[0]] for pick in pick_list(pick))
    def pick_list(who): return [A[k["id"]]["choice"] for k in act] if who == "owner" else [k["picks"][who] for k in act]
    for who in ("owner", "rulebook", "trained", "engine", "matching"):
        print(who, dict(kinds(who)))
    sh = [k for k in key if k["kind"] == "shield"]
    print("shields yes of", len(sh), {w: sum((A[k["id"]]["choice"] if w == "owner" else k["picks"][w]) == "yes" for k in sh) for w in ("owner", "rulebook", "trained", "engine", "matching")})
    print("engine override of trained, owner's side, sure only:", sum(1 for k in key if k["picks"]["engine"] != k["picks"]["trained"] and A[k["id"]]["confidence"] == "sure" and A[k["id"]]["choice"] == k["picks"]["engine"]), "engine;", sum(1 for k in key if k["picks"]["engine"] != k["picks"]["trained"] and A[k["id"]]["confidence"] == "sure" and A[k["id"]]["choice"] == k["picks"]["trained"]), "trained")
