"""pogo.controls: decisions become touches in the right places, and never in the keep-out zones."""
import unittest

from pogo import controls as c
from pogo.battle import CHARGED, FAST, SWITCH, Battle, Mon
from pogo.gamedata import GameData


class Controls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gd = GameData()
        cls.team = [gd.default(s) for s in ("melmetal", "altaria", "jellicent")]
        cls.foes = [gd.default(s) for s in ("corviknight", "tinkaton", "mandibuzz")]

    def view(self, active=0, fainted=()):
        mons = [Mon(b) for b in self.team]
        for j in fainted:
            mons[j].hp = 0
        battle = Battle(mons, self.foes, None, None, seed=1)
        battle.sides[0].active = active
        return battle.views[0]

    def test_actions(self):
        v = self.view()
        self.assertEqual(c.for_action(FAST, v)[0].points, [c.FIELD])
        self.assertEqual(c.for_action(CHARGED[1], v)[0].points, [c.CHARGED_BUTTONS[1]])
        self.assertEqual(c.for_action(SWITCH[1], v)[0].points, [c.BENCH[0]])  # Altaria: the top portrait
        self.assertEqual(c.for_action(SWITCH[2], v)[0].points, [c.BENCH[1]])
        one_left = self.view(fainted=(1,))
        self.assertEqual(c.for_action(SWITCH[2], one_left)[0].points, [c.BENCH[0]])  # the only portrait moves up
        with self.assertRaises(c.UnsafeTouch):
            c.for_action(SWITCH[1], one_left)

    def test_shield_and_replace(self):
        self.assertEqual(c.for_shield(True)[0].points, [c.SHIELD_YES])
        self.assertEqual(c.for_shield(False)[0].points, [c.SHIELD_NO])
        v = self.view(active=0, fainted=(0,))
        self.assertEqual(c.for_replace(2, v)[0].points, [c.REPLACE_TWO[1]])
        v = self.view(active=0, fainted=(0, 1))
        self.assertEqual(c.for_replace(2, v)[0].points, [c.REPLACE_ONE])

    def test_keep_out(self):
        with self.assertRaises(c.UnsafeTouch):
            c.tap((0.075, 0.18), "flee button")
        controller = c.Controller(live=False, max_touches=2)
        controller.send(c.for_shield(True) + c.for_shield(False))
        with self.assertRaises(c.UnsafeTouch):
            controller.send(c.for_shield(True))
        self.assertTrue(all(not entry[-1] for entry in controller.log))  # nothing was sent live


if __name__ == "__main__":
    unittest.main()
