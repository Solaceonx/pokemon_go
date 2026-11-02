import ast
from pathlib import Path
import random
import unittest

import numpy as np

from pogo.agents import Planner
from pogo.battle import Battle
from pogo.dqn import Agent, Network
from pogo.gamedata import GameData
from pogo.rl_search import RolloutAgent, public_world


class IndependentSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.team = [cls.gd.default(s) for s in ('melmetal', 'jellicent', 'altaria')]

    def test_public_reconstruction_cannot_read_private_state_or_change_live_dice(self):
        b = Battle(self.team, list(reversed(self.team)), Planner(seed=1), Planner(seed=2), seed=3)
        view = b.views[0]
        class PublicOnly:
            def __getattr__(self, name):
                if name.startswith('_'):
                    raise AssertionError('Hidden state accessed: ' + name)
                return getattr(view, name)
        before = b.rng.getstate()
        mine = Agent(Network(hidden=16))
        a = public_world(PublicOnly(), self.gd.meta(50), random.Random(10), mine, mine.clone())
        b.sides[1].team[1].energy = 100
        b.sides[1].team[2].hp = 1  # alive count unchanged; neither hidden value is public
        other = public_world(PublicOnly(), self.gd.meta(50), random.Random(10), mine, mine.clone())
        key = lambda game: [[(m.build.species_id, m.hp, m.energy) for m in s.team] for s in game.sides]
        self.assertEqual(key(a), key(other))
        self.assertEqual(before, b.rng.getstate())

    def test_reconstruction_keeps_public_clocks_stages_and_revelations(self):
        b = Battle(self.team, list(reversed(self.team)), Planner(seed=1), Planner(seed=2), seed=3)
        b.sides[0].active, b.sides[0].shown = 2, [0, 2]
        b.sides[0].switch_wait, b.sides[0].busy = 22, 1
        b.sides[1].active, b.sides[1].shown = 1, [0, 1]
        b.sides[1].mon.energy, b.sides[1].mon.atk_stage = 66, -2
        b.turn = 101
        p = Agent(Network(hidden=16))
        world = public_world(b.views[0], self.gd.meta(50), random.Random(1), p, p.clone())
        self.assertEqual((world.turn, world.sides[0].active, world.sides[0].shown), (101, 2, [0, 2]))
        self.assertEqual((world.sides[0].switch_wait, world.sides[0].busy), (22, 1))
        self.assertEqual((world.sides[1].active, world.sides[1].mon.energy, world.sides[1].mon.atk_stage), (1, 66, -2))
        self.assertEqual(world.sides[1].shown, [0, 1])

    def test_zero_search_matches_neural_policy_and_search_game_finishes(self):
        net = Network(hidden=16)
        a = Battle(self.team, list(reversed(self.team)), Agent(net, seed=2), Planner(seed=3), seed=4, record=True)
        b = Battle(self.team, list(reversed(self.team)), RolloutAgent(net, self.gd.meta(50), samples=0, seed=2),
                   Planner(seed=3), seed=4, record=True)
        self.assertEqual(a.run(), b.run())
        self.assertEqual(a.log, b.log)
        player = RolloutAgent(net, self.gd.meta(50), samples=1, stride=20, seed=2)
        game = Battle(self.team, list(reversed(self.team)), player, Planner(seed=3), seed=4)
        self.assertIn(game.run(), (-1, 0, 1))
        self.assertGreater(player.stats['rollouts'], 0)

    def test_search_has_no_engine_or_rule_player_import(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'pogo/rl_search.py').read_text())
        modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertFalse(any(m in ('engine', 'agents', 'learner') for m in modules))


if __name__ == '__main__':
    unittest.main()
