"""The engine with a learned model of its opponent inside the look-ahead (lab-learn).

The website engine (pogo.realtime.RealTime with WEBSITE settings) plays both sides of every imagined battle with the
trained bot: its search is a best response to the trained bot. When the trained bot's networks change (tasks 39, 44,
48), the imagined opponent changes with them, although the real opponent has not: one reason a new q can lose head
to head inside the engine while it plays as well alone. ModelledEngine keeps the two apart:

    opp_q       the imagined opponent is the trained bot on these networks (our own side keeps `q`)
    opp_policy  the imagined opponent plays a learned policy (pogo.lab.policy.PolicyNet), for example one fitted to
                the website engine's own choices, drawn from its probabilities (opp_sample, the default) or the
                likeliest option taken; its bot inputs come from opp_q, else q

Only with opponents="bot" (the default); other opponent styles stay as they are. Everything else is the
engine as it was.
"""
from __future__ import annotations

from pogo.learner import Learner
from pogo.realtime import RealTime

from .policy import PolicyNet, PolicyPlayer


class ModelledEngine(RealTime):
    def __init__(self, *args, opp_policy: PolicyNet | None = None, opp_q=None, opp_sample: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.opp_policy, self.opp_q, self.opp_sample = opp_policy, opp_q, opp_sample

    def _imagined_opponent(self, rng):
        if self.opponents != "bot" or (self.opp_policy is None and self.opp_q is None):
            return super()._imagined_opponent(rng)
        q = self.opp_q if self.opp_q is not None else self.q
        if self.opp_policy is None:
            return Learner(q=q, margin=self.margin, seed=rng.getrandbits(32))
        return PolicyPlayer(pnet=self.opp_policy, q=q, margin=self.margin, sample=self.opp_sample,
                            seed=rng.getrandbits(32))
