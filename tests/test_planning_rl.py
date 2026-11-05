"""Public-world reconstruction and independent learned-policy rollouts."""
import random
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from pogo.battle import Battle, Mon
from pogo.gamedata import GameData
from pogo.planning_rl import FirstAction, PlanningAgent, public_world
from pogo.standalone_rl import StandaloneAgent, encode, mask_for
from pogo.standalone_rl_v2 import ActorCritic


class IndependentPolicyRollouts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.pool = [cls.gd.default(s) for s in ("melmetal", "altaria", "jellicent", "azumarill", "skarmory", "registeel")]

    def battle(self):
        model = ActorCritic(hidden=8)
        return Battle(self.pool[:3], self.pool[3:], StandaloneAgent(model, 1),
                      StandaloneAgent(model, 2), seed=3)

    @staticmethod
    def state(battle):
        return (battle.winner, battle.turn,
                [(s.active, s.shields, s.switch_wait, s.busy,
                  [(m.build.species_id, m.hp, m.energy, m.atk_stage, m.def_stage) for m in s.team])
                 for s in battle.sides])

    def test_fully_public_reconstruction_replays_complete_battle(self):
        battle = self.battle()
        for _ in range(6):
            battle.step()
        for side in battle.sides:
            side.shown = [0, 1, 2]
        world = public_world(battle.views[0], self.pool, *(p.clone() for p in battle.agents), random.Random(9))
        world.rng.setstate(battle.rng.getstate())
        self.assertEqual(self.state(world), self.state(battle))
        battle.run()
        world.run()
        self.assertEqual(self.state(world), self.state(battle))
        self.assertEqual(world.rng.getstate(), battle.rng.getstate())

    def test_world_and_planning_choice_ignore_unseen_real_teammates(self):
        battle = self.battle()
        view = battle.views[0]
        model = ActorCritic(hidden=8)
        before = public_world(view, self.pool, StandaloneAgent(model), StandaloneAgent(model), random.Random(10))
        first = PlanningAgent(model, model, self.pool, samples=1, confidence=1., seed=11).act(view)
        battle.sides[1].team[1:] = [Mon(self.gd.default("tinkaton")), Mon(self.gd.default("mimikyu"))]
        after = public_world(view, self.pool, StandaloneAgent(model), StandaloneAgent(model), random.Random(10))
        second = PlanningAgent(model, model, self.pool, samples=1, confidence=1., seed=11).act(view)
        self.assertEqual(self.state(before), self.state(after))
        self.assertEqual(first, second)

    def test_zero_budget_matches_policy_and_ties_keep_its_preference(self):
        battle = self.battle()
        view, model = battle.views[0], battle.agents[0].model
        baseline = StandaloneAgent(model, greedy=True).act(view)
        agent = PlanningAgent(model, model, self.pool, samples=0)
        self.assertEqual(agent.act(view), baseline)
        self.assertEqual(agent.rollouts, 0)
        class World:
            turn = 0
            def clone(self, *players):
                return SimpleNamespace(run=lambda: 0, turn=1)
        agent = PlanningAgent(model, model, self.pool, samples=2, confidence=1.)
        with patch("pogo.planning_rl.public_world", return_value=World()):
            self.assertEqual(agent.act(view), baseline)
        self.assertEqual(agent.rollouts, 2 * len(view.legal()))

    def test_forced_real_action_consumes_the_same_policy_dice(self):
        battle = self.battle()
        view, pilot = battle.views[0], battle.agents[0]
        clone = pilot.clone()
        choice = pilot.act(view)
        self.assertEqual(FirstAction(clone, choice).act(view), choice)
        self.assertEqual(pilot.rng.bit_generator.state, clone.rng.bit_generator.state)

    def test_runtime_imports_no_search_player_or_teacher(self):
        code = ("import sys; import pogo.planning_rl; "
                "assert not {'pogo.engine','pogo.agents','pogo.learner'} & set(sys.modules)")
        subprocess.run([sys.executable, "-c", code], check=True)


if __name__ == "__main__":
    unittest.main()
