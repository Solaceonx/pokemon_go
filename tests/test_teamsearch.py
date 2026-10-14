"""Team-mixture integration: weighting, zero-sum solving, and honest paired tests."""
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
from pogo.gamedata import GameData
from pogo.teamlist import drawer, weights_for
from pogo.teamsearch import all_lineups, equilibrium, legal, play, schedule, seed_for, setup


class MixtureWeights(unittest.TestCase):
    def test_old_lists_keep_the_same_weights(self):
        entries = [{"score": 0.7, "seen": 2}, {"score": 0.3, "seen": 0}]
        self.assertEqual(weights_for(entries), [max(e["score"] - 0.4, 0.02) * (1 + e["seen"]) for e in entries])

    def test_explicit_weights_do_not_get_reweighted_by_seen_or_score(self):
        self.assertEqual(weights_for([{"weight": 0, "score": 1, "seen": 500},
                                      {"weight": 1, "score": 0, "seen": 0}]), [0, 1])

    def test_reject_invalid_mixtures(self):
        for entries in ([], [{"weight": 0}], [{"weight": -1}], [{"weight": float("nan")}],
                        [{"weight": float("inf")}], [{"weight": 1}, {"score": 0.5}]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                weights_for(entries)

    def test_drawer_obeys_zero_weight_even_with_many_sightings(self):
        gd = GameData()
        entries = [{"team": ["altaria", "charjabug", "corviknight"], "weight": 0, "seen": 1000},
                   {"team": ["melmetal", "altaria", "jellicent"], "weight": 1, "seen": 0}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "teams.json"
            path.write_text(json.dumps({"teams": entries}))
            draw = drawer(gd, gd.meta(100), path, share=1)
            rng = random.Random(42)
            for _ in range(20):
                self.assertEqual([b.species_id for b in draw(rng)], entries[1]["team"])


class ZeroSum(unittest.TestCase):
    def test_counter_cycle_does_not_collapse_to_latest_winner(self):
        rps = np.array([[0, -0.5, 0.5], [0.5, 0, -0.5], [-0.5, 0.5, 0]])
        # Fourth strategy loses to all three; a uniform mix is not the answer.
        a = np.zeros((4, 4))
        a[:3, :3], a[:3, 3], a[3, :3] = rps, 0.5, -0.5
        weights = equilibrium(a)
        self.assertAlmostEqual(float(weights.sum()), 1)
        self.assertLess(float(max(a @ weights)), 0.005)
        self.assertLess(weights[3], 0.001)

    def test_dominant_strategy(self):
        a = np.array([[0, .5], [-.5, 0]])
        self.assertGreater(equilibrium(a)[0], .999)

    def test_reject_non_zero_sum_matrix(self):
        with self.assertRaises(ValueError):
            equilibrium([[0, 1], [1, 0]])


class PairedEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.ids = [b.species_id for b in cls.gd.meta(100)]
        cls.dex = {s: cls.gd.species[s]["dex"] for s in cls.ids}

    def test_list_changes_only_opponents_not_pilot_or_battle_seeds(self):
        a = [("altaria", "charjabug", "corviknight")]
        b = [("melmetal", "altaria", "jellicent")]
        one = schedule(a, [1], self.ids, self.dex, 50, 42, listed=.8)
        two = schedule(b, [1], self.ids, self.dex, 50, 42, listed=.8)
        self.assertEqual([r[1:] for r in one], [r[1:] for r in two])
        self.assertTrue(any(x[0] != y[0] for x, y in zip(one, two)))
        # Random slots agree exactly, even with normal/shadow legality rejection.
        self.assertTrue(any(x[0] == y[0] for x, y in zip(one, two)))
        self.assertTrue(all(legal(x[0], self.dex) for x in one + two))
        self.assertEqual(one, schedule(a, [1], self.ids, self.dex, 50, 42, listed=.8))

    def test_streams_for_fitting_search_and_final_are_separate(self):
        seeds = {seed_for(42, phase, i) for phase in ("matrix", "search", "stop", "untouched-final") for i in range(20)}
        self.assertEqual(len(seeds), 80)

    def test_lineups_enforce_species_clause_and_all_leads(self):
        dex = {"a": 1, "shadow_a": 1, "b": 2, "c": 3}
        rows = all_lineups(dex, dex)
        self.assertEqual(len(rows), 6)
        self.assertEqual(len(set(rows)), 6)
        self.assertTrue(all(legal(t, dex) for t in rows))
        self.assertEqual({t[0] for t in rows}, set(dex))

    def test_results_ignore_worker_history_and_mirror_correctly(self):
        setup(str(ROOT / "runs" / "general-decide" / "q.npz"), 100)
        a = ("altaria", "charjabug", "corviknight")
        b = ("melmetal", "altaria", "jellicent")
        rows = schedule([b], [1], [], {}, 3, 42)
        first = play((a, rows, False))[1]
        reverse = [(a, dice, sb, sa) for _, dice, sa, sb in rows]
        other = play((b, reverse, False))[1]
        self.assertEqual(first, [1 - x for x in other])
        self.assertEqual(first, play((a, rows, False))[1])


if __name__ == "__main__":
    unittest.main()
