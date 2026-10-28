"""Evolvable choices for one question the owner doubts: throwing the cheaper charged move into a shield before the
dearer one is affordable (a bait the defender's energy count sees through), and shielding such a throw.

`CoevoBot` is the trained bot, except in those two spots, where it follows small evolvable policies (logistic in a
few features of the position) instead of its own judgement:

- thrower genes (5): with the cheaper move ready, the dearer not, a shield on their side, the cheaper move not a
  knock-out and waiting safe, throw the cheaper move now with chance sigmoid(genes . [1, its hit as a share of their
  health, our health share, fast moves still to the dearer move / 4, their shields / 2]); otherwise keep farming;
- shielder genes (5): when their energy shows only the cheaper move can be coming, we have a shield, it is not our
  last Pokémon and the hit would not knock us out, shield with chance sigmoid(genes . [1, the hit as a share of our
  health, our health share, our shields / 2, their health share]).

None for either set means the trained bot decides as usual. scripts/coevolve_baits.py evolves both against each
other (the owner: "what if you try doing more of an evolutionary network for this problem").
"""
from __future__ import annotations

import math

from .battle import CHARGED, ENERGY_CAP, FAST, damage
from .learner import Learner


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, x))))


class CoevoBot(Learner):
    def __init__(self, throw_genes=None, shield_genes=None, **kwargs):
        super().__init__(**kwargs)
        self.throw_genes = None if throw_genes is None else [float(g) for g in throw_genes]
        self.shield_genes = None if shield_genes is None else [float(g) for g in shield_genes]

    def clone(self):
        twin = super().clone()
        twin.throw_genes, twin.shield_genes = self.throw_genes, self.shield_genes
        return twin

    def _pick_move(self, view):
        action = super()._pick_move(view)
        if self.throw_genes is None:
            return action
        mon, foe = view.me.mon, view.foe
        moves = mon.build.charged
        if len(moves) < 2 or view.foe_shields == 0 or view.me.busy:
            return action
        cheap = min(range(2), key=lambda k: moves[k].energy)
        dear = 1 - cheap
        if moves[cheap].energy == moves[dear].energy or not moves[cheap].energy <= mon.energy < moves[dear].energy:
            return action
        hit = damage(mon, moves[cheap], foe)
        if hit >= foe.hp:
            return action
        fast = mon.build.fast
        fasts = -(-(moves[dear].energy - mon.energy) // fast.energy_gain)
        if mon.energy + fast.energy_gain > ENERGY_CAP or self._may_faint(view, fasts * fast.turns):
            return action
        x = [1.0, min(hit / max(foe.hp, 1), 1.5), mon.hp / mon.build.hp, fasts / 4, view.foe_shields / 2]
        throw = self.rng.random() < _sigmoid(sum(g * v for g, v in zip(self.throw_genes, x)))
        return CHARGED[cheap] if throw else FAST

    def shield(self, view, foe_energy, *move):
        if self.shield_genes is None:
            return super().shield(view, foe_energy, *move)
        me, mon, foe = view.me, view.me.mon, view.foe
        moves = foe.build.charged
        if me.left() > 1 and len(moves) == 2 and me.shields > 0:
            cheap = min(moves, key=lambda m: m.energy)
            dear = max(moves, key=lambda m: m.energy)
            if cheap.energy < dear.energy and cheap.energy <= foe_energy < dear.energy:
                hit = damage(foe, cheap, mon)
                if hit < mon.hp:
                    x = [1.0, min(hit / max(mon.hp, 1), 1.5), mon.hp / mon.build.hp, me.shields / 2, foe.hp / foe.build.hp]
                    return self.rng.random() < _sigmoid(sum(g * v for g, v in zip(self.shield_genes, x)))
        return super().shield(view, foe_energy, *move)
