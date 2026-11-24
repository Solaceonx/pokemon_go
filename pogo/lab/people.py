"""The creator exam's human-style opponent, shared with the engine lab fields."""
import random

from pogo.learner import Learner
from pogo.people_shield import cached

PEOPLE = "runs/people-shield/shield.npz"


class PeopleLike(Learner):
    """Draw shields at the creators' network probability; retain the last-Pokemon rule."""

    def __init__(self, rng: random.Random, **kw):
        super().__init__(**kw)
        self._draw = random.Random(rng.getrandbits(32))
        self._people = cached(PEOPLE)

    def clone(self):
        twin = super().clone()
        twin._draw = random.Random()
        twin._draw.setstate(self._draw.getstate())
        return twin

    def shield(self, view, foe_energy, *move):
        if view.me.left() == 1:
            return super().shield(view, foe_energy)
        return self._draw.random() < self._people.probability(view)


def people_player(rng: random.Random, q, pool: list) -> PeopleLike:
    # Preserve the exam's original draw order (settings, margin, private shield seed).
    from pogo.engine import human_settings
    settings = human_settings(rng, pool)
    return PeopleLike(rng, q=q, margin=rng.choice((0.02, 0.05)), **settings)
