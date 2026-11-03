"""The play-out caches (pogo.agents: duel and the rollouts in Planner._play_out) change nothing but the speed."""
import random
import unittest
from unittest.mock import patch

import pogo.agents as agents
import pogo.battle as battle_module
from pogo.agents import Planner, duel
from pogo.battle import Battle, Mon
from pogo.engine import Engine
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData
from pogo.learner import Learner, QNet
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PlayoutCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.pool = cls.gd.meta(50)
        cls.q = QNet.load(ROOT / "runs" / "general-decide" / "q.npz")
        cls.model = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz").model

    def setUp(self):
        agents.clear_playout_cache()

    def tearDown(self):
        agents.clear_playout_cache()

    def games(self, players):
        logs = []
        for seed in range(3):
            rng = random.Random(seed)
            teams = rng.sample(self.pool, 3), rng.sample(self.pool, 3)
            battle = Battle(*teams, *players(rng), seed=rng.getrandbits(32), record=True)
            battle.run()
            logs.append(battle.log)
        return logs

    def test_the_same_games_with_and_without_it(self):
        kinds = {
            "the trained bot": lambda rng: [Learner(q=self.q, margin=0.02, seed=rng.getrandbits(32)) for _ in range(2)],
            "the rulebook": lambda rng: [Planner(seed=rng.getrandbits(32)) for _ in range(2)],
            "the engine": lambda rng: [Engine(Evaluator(self.model), self.pool, rollout="bot", samples=2, horizon=4,
                                              edge=0.03, q=self.q, margin=0.02, seed=rng.getrandbits(32))
                                       for _ in range(2)],
        }
        for name, players in kinds.items():
            agents.clear_playout_cache()
            with patch.object(agents, "PLAYOUT_CACHE", False):
                plain = self.games(players)
            self.assertFalse(agents._duels or agents._rollouts)
            cached = self.games(players)
            self.assertTrue(agents._duels and agents._rollouts, name)
            self.assertEqual(cached, plain, name)
            self.assertEqual(self.games(players), plain, name)  # again, now mostly from the cache

    def test_a_hit_is_the_play_out_itself(self):
        rng = random.Random(5)
        for _ in range(20):
            a, b = (Mon(build, energy=rng.randrange(0, 101, 5)) for build in rng.sample(self.pool, 2))
            a.hp = rng.randint(1, a.build.hp)
            shields = rng.randint(0, 2), rng.randint(0, 2)
            first = duel(a, b, *shields)
            with patch.object(agents, "PLAYOUT_CACHE", False):
                self.assertEqual(duel(a, b, *shields), first)
            self.assertEqual(duel(a, b, *shields), first)

    def test_the_morpeko_rule_and_the_size_limit(self):
        mine, theirs = Mon(self.gd.default("morpeko_full_belly")), Mon(self.pool[0])
        duel(mine, theirs, 1, 1)
        with patch.object(battle_module, "MORPEKO_TOGGLES", False):
            duel(mine, theirs, 1, 1)  # scripts/check_pvpoke.py's setting is a position of its own
        self.assertEqual(len(agents._duels), 2)
        with patch.object(agents, "_CACHE_SIZE", 3):
            for hp in range(1, 8):
                theirs.hp = hp
                duel(mine, theirs, 1, 1)
                self.assertLessEqual(len(agents._duels), 3)


if __name__ == "__main__":
    unittest.main()
