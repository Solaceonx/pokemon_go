"""The losing-lead setup rule, including its information boundary."""
import unittest

from pogo.agents import Masher, Planner, duel
from pogo.battle import SWITCH, Battle, Mon
from pogo.gamedata import GameData


GD = GameData()


class Sweeper(unittest.TestCase):
    def position(self):
        agent = Planner(sweeper=0.5, field=[GD.default("torterra")], seed=1, good_matchup=False)  # the sweeper rule on its own
        battle = Battle(
            [GD.default(s) for s in ("snorlax_shadow", "marowak", "annihilape")],
            [GD.default(s) for s in ("carbink", "empoleon", "feraligatr")],
            agent, Masher(), seed=1,
        )
        return agent, battle, battle.views[0]

    def counter_swap(self):
        agent, battle, view = self.position()
        self.assertEqual(agent.act(view), SWITCH[1])
        me, foe = battle.sides
        me.active, me.shown, me.switch_wait = 1, [0, 1], 85
        me.mon.energy = 10
        # They can take a few turns to answer our swap; keep the pending setup.
        self.assertIsNone(agent._sweeper_slot(view))
        self.assertIsNotNone(agent._setup_swap)
        foe.active, foe.shown, foe.switch_wait = 1, [0, 1], 89
        return agent, battle, view

    def test_off_by_default(self):
        self.assertEqual(Planner().sweeper, 0.0)
        agent, battle, view = self.counter_swap()
        agent.sweeper = 0.0
        self.assertIsNone(agent._sweeper_slot(view))

    def test_recognizes_the_sequence_and_selects_a_teammate(self):
        agent, battle, view = self.counter_swap()
        self.assertGreater(agent._outlook(view, view.me.active), 0)
        self.assertEqual(agent._sweeper_slot(view), 2)

    def test_no_setup_without_a_losing_lead_swap(self):
        agent, battle, view = self.counter_swap()
        agent._setup_swap = None
        self.assertIsNone(agent._sweeper_slot(view))
        # A winning lead does not initiate a setup.
        agent, battle, view = self.position()
        battle.sides[1].team[0] = Mon(GD.default("jellicent"), hp=1)
        agent.act(view)
        self.assertIsNone(agent._setup_swap)

    def test_unwinnable_counter_swap_does_not_qualify(self):
        agent, battle, view = self.counter_swap()
        view.me.mon.hp = 1
        self.assertIsNone(agent._sweeper_slot(view))

    def test_weak_candidate_does_not_qualify(self):
        agent, battle, view = self.counter_swap()
        for j in view.me.bench():
            view.me.team[j].hp = 1
        self.assertIsNone(agent._sweeper_slot(view))

    def test_health_energy_and_shields_carry_across_opponents(self):
        agent, battle, view = self.counter_swap()
        agent.field = [GD.default("corsola_galarian")]
        candidate = view.me.team[2]
        for foe in (view.foe_shown[0], Mon(agent.field[0])):
            self.assertGreater(duel(candidate, foe, 2, 0), 0)
        # Each isolated duel wins, but one continuous sweep cannot win both.
        before = [(m.hp, m.energy, m.atk_stage, m.def_stage)
                  for side in battle.sides for m in side.team]
        self.assertEqual(agent._sweep_chance(view, 2), 0)
        self.assertEqual(before, [(m.hp, m.energy, m.atk_stage, m.def_stage)
                                 for side in battle.sides for m in side.team])

    def test_unseen_roster_is_not_read(self):
        agent, battle, view = self.counter_swap()
        chance = agent._sweep_chance(view, 2)
        battle.sides[1].team[2] = Mon(GD.default("wigglytuff"), energy=100)
        self.assertEqual(agent._sweep_chance(view, 2), chance)
        # Once revealed, it is evidence and replaces the prior.
        battle.sides[1].shown.append(2)
        self.assertEqual(agent._sweep_chance(view, 2), 0)

    def test_saves_a_shield_for_the_sweeper_and_sends_it_in(self):
        agent, battle, view = self.counter_swap()
        self.assertEqual(agent._sweeper_slot(view), 2)
        view.me.mon.hp, view.me.mon.energy = 20, 90
        view.foe.energy = 70
        standard = agent.clone()
        standard.sweeper = 0
        self.assertTrue(standard.shield(view, 70))
        self.assertFalse(agent.shield(view, 70))
        view.me.mon.hp = 0
        self.assertEqual(agent.replace(view), 2)

    def test_plan_expires_and_clone_keeps_its_own_plan(self):
        for change in ("our slot", "their slot", "our timer", "their timer", "sweeper faints"):
            with self.subTest(change=change):
                agent, battle, view = self.counter_swap()
                self.assertEqual(agent._sweeper_slot(view), 2)
                twin = agent.clone()
                if change == "our slot":
                    view.me.active = 0
                elif change == "their slot":
                    battle.sides[1].active = 0
                elif change == "our timer":
                    view.me.switch_wait = 0
                elif change == "their timer":
                    battle.sides[1].switch_wait = 0
                else:
                    view.me.team[2].hp = 0
                self.assertIsNone(agent._sweeper_slot(view))
                self.assertIsNone(agent._sweep_plan)
                self.assertIsNotNone(twin._sweep_plan)


if __name__ == "__main__":
    unittest.main()
