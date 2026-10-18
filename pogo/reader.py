"""A probe for how readable a player is (docs/tasks.md, task 29): an engine that knows how its opponent decides.

At its own throw decisions, when both sides have a charged move ready, the `Reader` predicts the opponent's next action
by running a copy of the opponent on the opponent's own view (the same search dice, but the opponent's mixing dice
drawn afresh: a mixed choice cannot be read in advance), and then searches its options with that action fixed. A
player that always takes the same choice in the same position is read exactly; one that mixes is not.

It has to play side 0 with its target on side 1: side 0 chooses first within a turn, so the copy is taken before the
target has decided. It looks at the real battle through the view, which only a probe may do.
"""
from __future__ import annotations

from .engine import Engine


class Reader(Engine):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("heads", ("throw",))
        super().__init__(*args, **kwargs)
        self.target, self.target_side, self.reads = None, 1, 0

    def act(self, view):
        mine = view.me.mon
        ready = any(mine.energy >= m.energy for m in mine.build.charged)
        if self.target is None or not ready or not self._their_throws(view):
            return super().act(view)
        twin = self.target.clone()
        if hasattr(twin, "_mix_rng"):
            twin._mix_rng.seed(self.rng.getrandbits(32))
        twin._deadline = None
        if hasattr(twin, "rows"):
            twin.rows = []
        predicted = twin.act(view._battle.views[self.target_side])
        self.reads += 1
        self._their_first = predicted
        try:
            return super().act(view)
        finally:
            self._their_first = None
