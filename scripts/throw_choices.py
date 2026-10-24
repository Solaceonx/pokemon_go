#!/usr/bin/env python3
"""The bot's charged-move choices in the website games, and the ones that look odd (the owner: "I'm still confused
by its choice of charged move sometimes").

    python3 scripts/throw_choices.py

Every game in games/played/*-web.json is replayed from its log (scripts/losses.py: the person's choices, the bot's
logged moves). At each of the bot's throws with both its charged moves affordable: what each would have done to the
Pokémon in front of it, the shields it had, and which was thrown. Flagged as odd: with no shield in the way, the move
that does less damage when the harder one was ready and neither knocks out; or a resisted move when the other was
ready and not resisted. For each odd one, what the trained bot and the rulebook would choose there now.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import losses as L  # noqa: E402
from pogo.agents import Planner  # noqa: E402
from pogo.battle import CHARGED, FAST, Battle, damage  # noqa: E402
from pogo.gamedata import effectiveness  # noqa: E402
from pogo.learner import Learner  # noqa: E402

L.setup()
rows, early = [], []


def effect(move, target) -> float:
    return effectiveness(move.type, tuple(target.build.types))


class Spy(L.Logged):
    def __init__(self, log, game):
        super().__init__(log)
        self.game = game

    def act(self, view):
        a = super().act(view)
        mon, foe = view.me.mon, view.foe
        moves = mon.build.charged
        if a in CHARGED and len(moves) == 2 and not all(mon.energy >= m.energy for m in moves):
            k = CHARGED.index(a)
            early.append({"battle": view._battle.clone(None, None), "game": self.game, "turn": view.turn, "mon": mon.build.name, "foe": foe.build.name,
                          "threw": moves[k].name, "energy": mon.energy, "need": moves[1 - k].energy,
                          "other": moves[1 - k].name, "shields": view.foe_shields, "my_hp": round(mon.hp / mon.build.hp, 2),
                          "foe_energy": foe.energy, "kills": damage(mon, moves[k], foe) >= foe.hp,
                          "resisted": effect(moves[k], foe) < 1, "other_better": effect(moves[1 - k], foe) > effect(moves[k], foe)})
        if a in CHARGED and len(moves) == 2 and all(mon.energy >= m.energy for m in moves):
            k = CHARGED.index(a)
            hits = [damage(mon, m, foe) for m in moves]
            battle = view._battle.clone(None, None)
            rows.append({"game": self.game, "turn": view.turn, "mon": mon.build.name, "foe": foe.build.name,
                         "threw": moves[k].name, "other": moves[1 - k].name, "hit": hits[k], "other_hit": hits[1 - k],
                         "cost": moves[k].energy, "other_cost": moves[1 - k].energy, "energy": mon.energy,
                         "foe_hp": foe.hp, "shields": view.foe_shields, "my_hp": round(mon.hp / mon.build.hp, 2),
                         "battle": battle, "k": k, "eff": effect(moves[k], foe), "other_eff": effect(moves[1 - k], foe)})
        return a


for f in sorted(glob.glob(str(ROOT / "games" / "played" / "*-web.json"))):
    saved = json.loads(Path(f).read_text())
    teams = [[L._state["gd"].build(sid, mv, level=level, ivs=tuple(ivs)) for sid, mv, level, ivs in t] for t in saved["teams"]]
    Battle(teams[0], teams[1], L.Replay(saved["my_choices"]), Spy(saved["log"], Path(f).stem[:16]), seed=saved["seed"]).run()

odd = []
for r in rows:
    softer = r["hit"] < r["other_hit"]
    if r["shields"] == 0 and r["other_hit"] >= r["foe_hp"] > r["hit"]:
        r["why_odd"] = "no shield left, the other move knocks out and this one does not"
        odd.append(r)
    elif r["shields"] == 0 and softer and r["hit"] < r["foe_hp"]:
        r["why_odd"] = "no shield left, the weaker move"
        odd.append(r)
print(f"{len(rows)} throws by the bot with both moves affordable, in the website games")
print(f"into a shield: cheaper/weaker move {sum(r['shields'] > 0 and r['hit'] < r['other_hit'] for r in rows)}, "
      f"harder move {sum(r['shields'] > 0 and r['hit'] >= r['other_hit'] for r in rows)}; no shield left: weaker "
      f"{sum(r['shields'] == 0 and r['hit'] < r['other_hit'] for r in rows)}, harder {sum(r['shields'] == 0 and r['hit'] >= r['other_hit'] for r in rows)}")
print(f"\n{len(odd)} odd ones (no shield left: the weaker move, or not the move that knocks out):")
for r in odd:
    b = r["battle"]
    view = b.views[1]
    now = {}
    for name, player in (("trained bot", Learner(q=L._state["net"], margin=0.02, seed=1)), ("rulebook", Planner(seed=1))):
        a = player.act(b.clone(None, None).views[1])
        now[name] = "fast move" if a == FAST else view.me.mon.build.charged[CHARGED.index(a)].name if a in CHARGED else "switch"
    print(f"  [{r['why_odd']}] {r['game']} turn {r['turn']}: {r['mon']} ({100 * r['my_hp']:.0f}%, {r['energy']} energy) v {r['foe']} "
          f"({r['foe_hp']} HP): threw {r['threw']} ({r['hit']} dmg, {r['cost']}e) over {r['other']} ({r['other_hit']} dmg, "
          f"{r['other_cost']}e); now the trained bot: {now['trained bot']}, the rulebook: {now['rulebook']}")

print("\ninto a shield with the harder move (the bot's 'nuke' instead of a bait), examples:")
for r in [r for r in rows if r["shields"] > 0 and r["hit"] >= r["other_hit"]][:8]:
    print(f"  {r['game']} t{r['turn']}: {r['mon']} ({100 * r['my_hp']:.0f}%) v {r['foe']}, their shields {r['shields']}: "
          f"{r['threw']} {r['hit']} dmg / {r['cost']}e over {r['other']} {r['other_hit']} dmg / {r['other_cost']}e")
res = [r for r in rows if r["eff"] < 1 and r["other_eff"] > r["eff"]]
print(f"\na resisted move thrown when the other was better on type, both affordable: {len(res)}")
for r in res[:8]:
    print(f"  {r['game']} t{r['turn']}: {r['mon']} v {r['foe']}: {r['threw']} ({r['eff']:.2f}x, {r['hit']} dmg) over {r['other']} "
          f"({r['other_eff']:.2f}x, {r['other_hit']} dmg), their shields {r['shields']}")
print(f"\n{len(early)} throws with only one move affordable; of those, into a shield before the dearer move was "
      f"affordable (a bait the energy count gives away): {sum(r['shields'] > 0 and not r['kills'] for r in early)}")
for r in [r for r in early if r["shields"] > 0 and not r["kills"]][:10]:
    print(f"  {r['game']} t{r['turn']}: {r['mon']} ({100 * r['my_hp']:.0f}%) v {r['foe']}: {r['threw']} at {r['energy']}e "
          f"({r['other']} needs {r['need']}){', resisted' if r['resisted'] else ''}{', the other is better on type' if r['other_better'] else ''}")
r2 = [r for r in early if r["resisted"] and r["other_better"]]
print(f"\nresisted, with the other move better on type but not yet affordable: {len(r2)}")
for r in r2[:8]:
    print(f"  {r['game']} t{r['turn']}: {r['mon']} ({100 * r['my_hp']:.0f}%) v {r['foe']}: {r['threw']} at {r['energy']}e, "
          f"{r['other']} needs {r['need']}, their shields {r['shields']}")


def now(battle):
    out = {}
    for name, player in (("trained bot", Learner(q=L._state["net"], margin=0.02, seed=1)), ("rulebook", Planner(seed=1))):
        view = battle.clone(None, None).views[1]
        a = player.act(view)
        out[name] = "fast move" if a == FAST else view.me.mon.build.charged[CHARGED.index(a)].name if a in CHARGED else "switch"
    return out


print("\nreadable baits above 30% health (into a shield, the dearer move not yet affordable), and what today's bot does there:")
for r in [r for r in early if r["shields"] > 0 and not r["kills"] and r["my_hp"] >= 0.3]:
    n = now(r["battle"])
    print(f"  {r['game']} t{r['turn']}: {r['mon']} ({100 * r['my_hp']:.0f}%) v {r['foe']}: {r['threw']} at {r['energy']}e "
          f"({r['other']} needs {r['need']}){', resisted' if r['resisted'] else ''}; today: trained bot {n['trained bot']}, rulebook {n['rulebook']}")
