"""The private exam's engine factory can be exercised on constructed positions."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import exam_variants as exam

from pogo.agents import Planner
from pogo.battle import Battle
from pogo.engine import Engine
from pogo.evaluation import Evaluator
from pogo.lab.tree import TreeEngine
from pogo.learner import QNet


STAY = "website,engine=tree,fix_stay=1"
TREE = STAY + ",fix_judged=1,depth=3,root=sh"
SAFE = TREE + ",shield_mix=0,finish_safe=1"
POP = SAFE + ",q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz"
SPECS = [STAY, TREE, SAFE, POP, "switch_edge=0.1"]


class ExamVariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        exam.E.setup()  # Loads public models/data only, no exam key or answer files.
        cls.gd = exam.E.L._state["gd"]

    def position(self, player):
        teams = [[self.gd.default(s) for s in species] for species in
                 (("swampert", "altaria", "umbreon"), ("azumarill", "skarmory", "venusaur"))]
        battle = Battle(*teams, player, Planner(seed=52), seed=53)
        battle.sides[0].mon.energy = battle.sides[1].mon.energy = 100
        return battle, battle.views[0]

    def test_requested_variants_build_and_decide_without_answers(self):
        # No engine_versus.setup(), and no dependency on its worker state.
        with patch.dict(exam.V._state, {}, clear=True), patch.object(exam, "_variants", SPECS):
            players = exam.builds(7)
            self.assertEqual(exam.V._state, {})
        self.assertEqual(set(players), {"engine", "trained", "rulebook", *SPECS})
        self.assertIs(type(players["engine"]), Engine)
        for spec in SPECS:
            with self.subTest(spec=spec):
                player = players[spec]
                self.assertIs(player.pool, exam.E.L._state["pool"])
                self.assertIs(player.evaluator.model, exam.E._s["ev"].model)
                self.assertIsNot(player.evaluator, players["engine"].evaluator)
                self.assertEqual((player.samples, player.horizon, player.edge, player.margin), (32, 20, .03, .02))
                self.assertEqual(player.rng.getstate(), players["engine"].rng.getstate())
                if spec != "switch_edge=0.1":
                    self.assertIsInstance(player, TreeEngine)
                    self.assertTrue(player.fix_stay)
                    if spec != STAY:
                        self.assertEqual((player.fix_judged, player.depth, player.root), (True, 3, "sh"))
                    if spec in (SAFE, POP):
                        self.assertEqual((player.shield_mix, player.finish_safe), (0, True))
                        self.assertIn("shield", player.heads)
                else:
                    self.assertEqual(player.switch_edge, .1)
                _, view = self.position(player)
                self.assertIn(player.act(view), view.legal())
                self.assertGreater(player.looks, 0)  # Real search, not just a forced fast move.
                self.assertIsInstance(player.shield(view, 100), bool)
        population = QNet.load(ROOT / "runs/lab-pop-q.npz")
        for actual, expected in ((players[POP].q, population),
                                 (players[POP].opp_q, exam.E.L._state["net"])):
            self.assertEqual(set(actual.params), set(expected.params))
            for head in expected.params:
                for a, b in zip(actual.params[head], expected.params[head]):
                    np.testing.assert_array_equal(a, b)

    def test_legacy_decisions_and_dice_match_previous_construction(self):
        settings = [({}, ""), ({"switch_edge": .1}, "switch_edge=0.1"),
                    ({"switch_edge": .05, "stay_after_replace": True}, "switch_edge=0.05,stay_after_replace=1"),
                    ({"stay_after_replace": False}, "stay_after_replace=2")]
        settings += [({"shield_margin": margin}, f"shield_margin={margin}") for margin in (.05, .1, 1)]
        settings += [({"shield_toward": toward}, f"shield_toward={int(toward)}") for toward in (False, True)]
        settings += [({"mid_swap_search": gate, "switch_edge": .05}, f"mid_swap_search={gate},switch_edge=0.05")
                     for gate in ("ready", "hit", "both")]
        for seed in (7, 17):  # Both sides' offsets in the exam replay.
            with patch.object(exam, "_variants", [spec for _, spec in settings]):
                players = exam.builds(seed)
            for options, spec in settings:
                with self.subTest(seed=seed, spec=spec):
                    old = Engine(Evaluator(exam.E._s["ev"].model), exam.E.L._state["pool"],
                                 rollout="bot", samples=32, edge=.03, q=exam.E.L._state["net"],
                                 margin=.02, seed=seed + 2, **options)
                    new = players[spec]
                    snapshots = []
                    for player in (old, new):
                        battle, view = self.position(player)
                        action = player.act(view)
                        shield = player.shield(view, 100)
                        battle.sides[0].mon.hp = 0
                        replacement = player.replace(view)
                        snapshots.append((action, shield, replacement, player.looks,
                                          player.rng.getstate(), player._mix_rng.getstate()))
                    self.assertEqual(*snapshots)


if __name__ == "__main__":
    unittest.main()
