"""Two rules from the owner: knock out a Pokémon with no shields left fast, and switch freely to a Pokémon that
beats several of a team we have seen in full."""
import unittest

from pogo.agents import Masher, Planner as _Planner, STANDARD_RULES


def Planner(**settings):
    """These tests pin rule mechanisms down under the rulebook's standard values (pogo.agents.STANDARD_RULES), not
    the evolved ones that became the default on 2026-10-19."""
    return _Planner(**{**STANDARD_RULES, **settings})
from pogo.battle import CHARGED, FAST, SWITCH, Battle, Mon, damage
from pogo.gamedata import GameData

GD = GameData()


class Rush(unittest.TestCase):
    def position(self, rush, energy=45, foe_shields=0):
        pilot = Planner(rush=rush, sac=False, seed=1)
        battle = Battle([Mon(GD.default("medicham"), energy=energy)], [Mon(GD.default("swampert"))],
                        pilot, Masher(), shields=(1, foe_shields), seed=1)
        return pilot, battle

    def test_throws_instead_of_holding_when_they_have_no_shields(self):
        holder, battle = self.position(rush=False)
        self.assertEqual(holder.act(battle.views[0]), FAST)  # the hold rule farms on
        rusher, battle = self.position(rush=True)
        self.assertIn(rusher.act(battle.views[0]), CHARGED)

    def test_only_once_their_shields_are_gone(self):
        rusher, battle = self.position(rush=True, foe_shields=1)
        holder, same = self.position(rush=False, foe_shields=1)
        self.assertEqual(rusher.act(battle.views[0]), holder.act(same.views[0]))

    def test_fastest_kill_counts_turns(self):
        pilot, battle = self.position(rush=True, energy=0)
        view = battle.views[0]
        mon, foe = view.me.mon, view.foe
        hit = [damage(mon, m, foe) for m in mon.build.charged]
        turns, first = pilot._fastest_kill(view, hit, hp=1)
        self.assertEqual((turns, first), (mon.build.fast.turns, FAST))  # one fast move finishes it
        turns, first = pilot._fastest_kill(view, hit, hp=1, energy=100)
        self.assertEqual(turns, 1)  # a charged move takes one turn
        self.assertIn(first, CHARGED)

    def test_off_by_default(self):
        self.assertFalse(Planner().rush)


class KnownTeam(unittest.TestCase):
    def position(self, known_team, shown=(0, 1)):
        pilot = Planner(known_team=known_team, sac=False, win_switch=None, seed=1)
        battle = Battle([GD.default("melmetal"), GD.default("altaria")],
                        [GD.default("corviknight"), GD.default("quagsire")], pilot, Masher(), seed=1)
        battle.sides[1].shown = list(shown)
        return pilot, battle

    def test_switches_to_a_counter_of_both_when_their_team_is_known(self):
        pilot, battle = self.position(known_team=True)
        self.assertEqual(pilot.act(battle.views[0]), SWITCH[1])  # Altaria beats Corviknight and Quagsire
        pilot, battle = self.position(known_team=False)
        self.assertEqual(pilot.act(battle.views[0]), FAST)  # the ordinary rule stays in

    def test_not_while_one_of_theirs_is_unseen(self):
        pilot, battle = self.position(known_team=True, shown=(0,))
        self.assertEqual(pilot.act(battle.views[0]), FAST)

    def test_off_by_default(self):
        self.assertFalse(Planner().known_team)


if __name__ == "__main__":
    unittest.main()
