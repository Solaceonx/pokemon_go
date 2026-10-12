"""A catch must be a legal read from the View, including in an old matchup."""
import unittest
from types import SimpleNamespace

from pogo.agents import Masher, Planner
from pogo.battle import FAST, SWITCH, Battle, Mon, damage
from pogo.gamedata import GameData


GD = GameData()


class Catch(unittest.TestCase):
    def position(self, bench=("azumarill",), energy=40, shields=0, **settings):
        options = dict(catch=True, sac=False, bad_matchup=-2, win_switch=None, seed=7)
        options.update(settings)
        pilot = Planner(**options)
        foe = Mon(GD.build("feraligatr", ["SHADOW_CLAW", "HYDRO_CANNON", "ICE_BEAM"]), energy=energy)
        battle = Battle([GD.default("talonflame"), *(GD.default(s) for s in bench)],
                        [foe], pilot, Masher(), shields=(shields, 0), seed=7)
        return pilot, battle

    def test_switch_catches_the_charge_before_it_lands(self):
        pilot, battle = self.position()
        lead, resist = battle.sides[0].team
        foe = battle.sides[1].mon
        hit = damage(foe, foe.build.charged[0], resist)
        self.assertEqual(pilot.act(battle.views[0]), SWITCH[1])
        battle.step()
        self.assertEqual(battle.sides[0].active, 1)
        self.assertEqual(lead.hp, lead.build.hp)
        self.assertEqual(resist.hp, resist.build.hp - hit)
        self.assertEqual(foe.energy, 0)

    def test_reconsiders_a_matchup_when_exact_energy_reaches_the_cost(self):
        pilot, battle = self.position(energy=39)
        self.assertEqual(pilot.act(battle.views[0]), FAST)
        self.assertIsNotNone(pilot._judged)
        battle.sides[1].mon.energy = 40
        self.assertEqual(pilot.act(battle.views[0]), SWITCH[1])

    def test_off_by_default_and_respects_switches_flag(self):
        self.assertFalse(Planner().catch)
        for options in (dict(catch=False), dict(switches=False)):
            with self.subTest(options=options):
                pilot, battle = self.position(**options)
                self.assertEqual(pilot.act(battle.views[0]), FAST)

    def test_cannot_catch_while_locked_or_either_fast_move_is_running(self):
        for side, attribute in ((0, "switch_wait"), (0, "busy"), (1, "busy")):
            with self.subTest(side=side, attribute=attribute):
                pilot, battle = self.position()
                setattr(battle.sides[side], attribute, 1)
                self.assertIsNone(pilot._pick_catch(battle.views[0]))

    def test_requires_a_living_resist_that_survives_the_hit(self):
        for bench, hp in (((), None), (("medicham",), None), (("azumarill",), 0), (("azumarill",), 36)):
            with self.subTest(bench=bench, hp=hp):
                pilot, battle = self.position(bench=bench)
                if hp is not None:
                    battle.sides[0].team[1].hp = hp
                self.assertEqual(pilot.act(battle.views[0]), FAST)

    def test_picks_the_largest_health_saving_and_applies_threshold(self):
        pilot, battle = self.position(bench=("jellicent", "azumarill"))
        self.assertEqual(pilot.act(battle.views[0]), SWITCH[2])
        pilot.catch_gain = 0.7
        self.assertEqual(pilot.act(battle.views[0]), FAST)

    def test_accounts_for_the_other_affordable_move_into_shields(self):
        pilot, battle = self.position(bench=("altaria",), shields=1)
        self.assertEqual(pilot.act(battle.views[0]), SWITCH[1])  # only Hydro Cannon is payable
        battle.sides[1].mon.energy = 55
        self.assertEqual(pilot.act(battle.views[0]), FAST)  # Ice Beam would punish this catch
        battle.sides[0].shields = 0
        self.assertEqual(pilot.act(battle.views[0]), SWITCH[1])  # read Hydro Cannon's higher damage per energy

    def test_uses_only_public_view_fields_and_does_not_change_them(self):
        pilot, battle = self.position()
        source = battle.views[0]
        view = SimpleNamespace(me=source.me, foe=source.foe, foe_busy=source.foe_busy)
        view.me.mon.atk_stage = 2
        view.me.team[1].def_stage = -2

        def state():
            return [(m.hp, m.energy, m.atk_stage, m.def_stage) for m in (*view.me.team, view.foe)]

        before = state()
        self.assertEqual(pilot._pick_catch(view), 1)
        self.assertEqual(pilot.clone()._pick_catch(view), 1)
        self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
