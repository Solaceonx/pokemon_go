"""Their energy as they throw, asked at the shield prompt between looks (Tracker.their_energy_at_throw): the count
at the last look, the fast move under way counted, and the fight since. Replaying 2026-11-22, the count at the
prompt was short of the move named at 18 of 91 throws; this way at 3."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData()


def stunfisk_for(seconds):
    tr = Tracker(GD, [GD.default("melmetal"), GD.default("altaria"), GD.default("jellicent")])
    k = 0
    while k * 0.5 <= seconds:
        tr.update(Observation(t=k * 0.5, my_species="melmetal", foe_species="azumarill", my_left=3, foe_left=3))
        k += 1
    return tr


class EnergyAtThrow(unittest.TestCase):
    def test_the_move_under_way_counts(self):
        tr = stunfisk_for(2.0)  # Bubble: 3 turns; 4 turns in, one landed and one under way
        gain = tr.foe.mon.build.fast.energy_gain
        self.assertEqual(tr.foe.hi, gain)
        self.assertEqual(tr.their_energy_at_throw()[1], 2 * gain)

    def test_and_the_fight_since_the_last_look(self):
        tr = stunfisk_for(1.5)  # 3 turns: one landed, none under way
        gain = tr.foe.mon.build.fast.energy_gain
        self.assertEqual(tr.their_energy_at_throw()[1], gain)
        self.assertEqual(tr.their_energy_at_throw(1.0)[1], 2 * gain)  # 2 more turns: the next one under way

    def test_nothing_changes_in_the_tracker(self):
        tr = stunfisk_for(2.0)
        before = (tr.foe.lo, tr.foe.hi, tr.beat, tr.turn)
        tr.their_energy_at_throw(3.0)
        self.assertEqual((tr.foe.lo, tr.foe.hi, tr.beat, tr.turn), before)


class PromptCall(unittest.TestCase):
    """Player.at_their_throw: the shield call sees their energy as they throw, the margin on top; put back after."""

    def test_seen_inside_and_put_back(self):
        import importlib.util, types
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "live"))
        stub = "cv2" not in sys.modules and importlib.util.find_spec("cv2") is None
        if stub:
            sys.modules["cv2"] = types.ModuleType("cv2")
        try:
            import play_android as pa
        finally:
            if stub:
                del sys.modules["cv2"]
        p = object.__new__(pa.Player)
        p.tracker = stunfisk_for(1.5)
        p.last_look, p.fight_frame_t = 1.5, 2.5  # the fight on for 1 s after the last look
        gain = p.tracker.foe.mon.build.fast.energy_gain
        before = (p.tracker.foe.lo, p.tracker.foe.hi, p.tracker.foe.mon.energy)
        with p.at_their_throw(margin=1):
            self.assertEqual(p.tracker.foe.hi, 3 * gain)  # one landed, one under way by then, and the margin
        self.assertEqual((p.tracker.foe.lo, p.tracker.foe.hi, p.tracker.foe.mon.energy), before)


if __name__ == "__main__":
    unittest.main()
