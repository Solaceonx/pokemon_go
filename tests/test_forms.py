"""Form-changing Pokémon (task 10): PvPoke's battles reproduced, and what happens on switching out."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_pvpoke  # noqa: E402
from pogo.battle import Mon, change_form, leave_field  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402


class Forms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()

    def test_pvpoke_form_battles(self):
        ids, moves, lines = check_pvpoke.load(check_pvpoke.FORMS)
        problems = [p for p in (check_pvpoke.check(self.gd, ids, moves, line) for line in lines) if p]
        self.assertEqual(problems, [])
        self.assertGreaterEqual(len(lines), 40)

    def test_switching_out(self):
        aegislash = Mon(self.gd.default("aegislash_shield"))
        change_form(aegislash, "aegislash_blade")
        self.assertEqual(aegislash.build.species_id, "aegislash_blade")
        leave_field(aegislash)
        self.assertEqual(aegislash.build.species_id, "aegislash_shield")
        mimikyu = Mon(self.gd.default("mimikyu"))
        change_form(mimikyu, "mimikyu_busted")
        leave_field(mimikyu)
        self.assertEqual((mimikyu.build.species_id, mimikyu.def_stage), ("mimikyu_busted", -1))

    def test_cheapest_move_into_a_disguise(self):
        """The owner's rule: while the Disguise is up, the cheapest ready charged move; then the usual choice."""
        from pogo.agents import Planner
        from pogo.battle import CHARGED, Battle
        from pogo.learner import Learner, QNet
        net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
        for agent in (Planner(seed=0), Learner(q=net, margin=0.02, seed=0)):
            # Without shields to bait, Corviknight would throw Iron Head (50) rather than Air Cutter (40).
            battle = Battle([self.gd.default("corviknight")], [self.gd.default("mimikyu")], agent, Planner(seed=1), seed=0,
                            shields=(1, 0))
            me = battle.sides[0].mon
            me.energy = 100
            moves = me.build.charged
            cheap = CHARGED[min(range(len(moves)), key=lambda k: moves[k].energy)]
            agent.disguise = False
            self.assertNotEqual(agent.act(battle.views[0]), cheap)
            agent.disguise = True
            self.assertEqual(agent.act(battle.views[0]), cheap)
            change_form(battle.sides[1].mon, "mimikyu_busted")
            agent.disguise = False
            usual = agent.act(battle.views[0])
            agent.disguise = True
            self.assertEqual(agent.act(battle.views[0]), usual)

    def test_blade_stats_match_pvpoke(self):
        blade = self.gd.default("aegislash_shield").forms["aegislash_blade"]
        self.assertEqual((blade.level, blade.hp), (22, 139))
        self.assertAlmostEqual(blade.atk, 172.93, places=1)
        self.assertAlmostEqual(blade.defense, 69.55, places=1)

    def test_morpeko_changes_mode_every_charged_attack(self):
        from pogo.battle import Battle, CHARGED, FAST

        class ThrowAll:
            def act(self, view):
                m = view.me.mon
                return CHARGED[0] if m.energy >= m.build.charged[0].energy else FAST

            def shield(self, view, energy, *move):
                return False

            def replace(self, view):
                return view.me.bench()[0]

        morpeko = Mon(self.gd.default("morpeko_full_belly"), energy=100)
        battle = Battle([morpeko], [self.gd.default("dondozo")], ThrowAll(), ThrowAll(), seed=1, record=True)
        battle.step()
        self.assertEqual(morpeko.build.species_id, "morpeko_hangry")
        battle.step()
        self.assertEqual(morpeko.build.species_id, "morpeko_full_belly")

    def test_pools_unchanged(self):
        self.assertFalse(any(b.forms for b in self.gd.meta(50)))
        self.assertTrue(any(b.forms for b in self.gd.meta(60, forms=True)))


if __name__ == "__main__":
    unittest.main()
