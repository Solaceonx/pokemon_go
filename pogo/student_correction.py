"""Training-only expert labels at states visited by the standalone student.

The expert observes the actual game. If the student rejects its proposal, its
unexecuted decision plan is rolled back and the actual physical action is
recorded. These teacher internals never become neural inputs. Evaluation uses
the ordinary StandaloneAgent without this wrapper or its expert.
"""
from __future__ import annotations

import copy

from .counterfactual_rl import clone_player
from .standalone_rl import StandaloneAgent, encode, mask_for

PLAN_FIELDS = ("_judged", "_fasted", "_hold", "_setup_swap", "_setup_checked", "_sweep_plan", "_replaced_at")


class CorrectedStudent(StandaloneAgent):
    def __init__(self, model, expert, *, seed=0, log=None, demonstrations=None, expert_control=False):
        super().__init__(model, seed=seed, greedy=False, log=log)
        self.expert, self.demonstrations = expert, demonstrations
        self.expert_control = expert_control

    def choose(self, view, head, energy=None):
        mask = mask_for(view, head)
        x = encode(view, energy) if mask.sum() > 1 else None
        plan = {k: copy.deepcopy(getattr(self.expert, k)) for k in PLAN_FIELDS if hasattr(self.expert, k)}
        if head == "act":
            advice = self.expert.act(view)
        elif head == "shield":
            advice = int(self.expert.shield(view, energy))
        else:
            advice = self.expert.replace(view)
        if not mask[advice]:
            raise ValueError("expert supplied an illegal correction")
        # Expert control is a replay test only, never an off-policy PPO sample.
        actual = advice if self.expert_control else super().choose(view, head, energy)
        if x is not None and self.demonstrations is not None:
            self.demonstrations.append((head, x, mask, advice, 0., 0.))
        if actual != advice and head in ("act", "replace"):
            for key, value in plan.items():
                setattr(self.expert, key, value)
            if head == "replace":
                self.expert._hold = 0
                if hasattr(self.expert, "_replaced_at"):
                    self.expert._replaced_at = view.turn
            elif actual == 0:
                self.expert._fasted = (view.me.active, view.foe.build.uid)
                self.expert._hold = max(0, plan.get("_hold", 0) - 1)
            else:
                self.expert._hold = 0
        return actual

    def saw_shield(self, *args):
        self.expert.saw_shield(*args)

    def saw_throw(self, *args):
        self.expert.saw_throw(*args)

    def clone(self):
        twin = super().clone()
        twin.expert = clone_player(self.expert)
        twin.demonstrations = None
        return twin
