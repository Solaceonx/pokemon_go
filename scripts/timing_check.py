"""In the website games, for the person and for the bot: free turns given away by each charged move (the other side's
fast move in progress lands in full), and Pokémon that fainted with a charged move affordable (the last hit landed
before they threw)."""
import glob, json, sys, collections
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent)]
import losses as L
from pogo.battle import CHARGED, Battle
L.setup()
free = {0: collections.Counter(), 1: collections.Counter()}
died = {0: [0, 0], 1: [0, 0]}
class Watch:
    def __init__(self, inner, side): self.inner, self.side, self.scripted = inner, side, True
    def act(self, view):
        a = self.inner.act(view)
        if a in CHARGED:
            mon, foe = view.me.mon, view.foe
            from pogo.battle import damage
            lethal = damage(mon, mon.build.charged[CHARGED.index(a)], foe) >= foe.hp and view.foe_shields == 0
            doomed = mon.hp <= 2 * damage(foe, foe.build.fast, mon)
            if not lethal and not doomed:
                mine, theirs = mon.build.fast.turns, foe.build.fast.turns
                phase = (theirs - view.foe_busy) % theirs
                f = lambda j: theirs - 1 - (phase + j * mine) % theirs
                free[self.side][f(0) - min(f(j) for j in range(theirs))] += 1
        return a
    def shield(self, view, energy, *m): return self.inner.shield(view, energy, *m)
    def replace(self, view): return self.inner.replace(view)
for f in sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "games" / "played" / "*-web.json"))):
    saved = json.load(open(f))
    teams = [[L._state["gd"].build(sid, moves, level=level, ivs=tuple(ivs)) for sid, moves, level, ivs in t] for t in saved["teams"]]
    b = Battle(teams[0], teams[1], Watch(L.Replay(saved["my_choices"]), 0), Watch(L.Logged(saved["log"]), 1), seed=saved["seed"], record=True)
    seen = set()
    while b.winner is None:
        before = [[(m.hp, m.energy) for m in s.team] for s in b.sides]
        b.step()
        for i, s in enumerate(b.sides):
            for j, m in enumerate(s.team):
                if m.hp <= 0 and (i, j) not in seen:
                    seen.add((i, j))
                    hp0, e0 = before[i][j]
                    died[i][1] += 1
                    from pogo.battle import damage
                    foe = b.sides[1 - i].mon
                    by_fast = hp0 <= damage(foe, foe.build.fast, m)  # a fast move could have been the last hit
                    died[i][0] += (e0 >= min(c.energy for c in m.build.charged)) and by_fast
for side, who in ((0, "you"), (1, "the bot")):
    c = free[side]; n = sum(c.values())
    print(f"{who}: {n} charged moves not for a knock-out nor about to faint; free turns more than the best timing within reach: " + ", ".join(f"{k}: {v}" for k, v in sorted(c.items()))
          + f"; fainted {died[side][1]} times, {died[side][0]} of them to a fast move with a charged move affordable")
