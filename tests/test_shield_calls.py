"""Task 41 changes only the trained shield head, with counts from actual battles."""
import hashlib
import json
import math
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bench
import engine_versus as versus
import exam_variants as exam
from pogo.agents import Planner
from pogo.battle import Battle
from pogo.engine import Engine
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData
from pogo.learner import Learner, QNet
from pogo.realtime import WEBSITE


class ShieldSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = GameData().meta(50)
        cls.q = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))

    def player(self, kind=Learner, seed=7, **kw):
        settings = dict(q=self.q, margin=0.02, seed=seed, **kw)
        if kind is Engine:
            return Engine(Evaluator(), self.pool, rollout="bot", samples=1, horizon=4, edge=0.03, **settings)
        return Learner(**settings)

    def battle(self, player, seed=7):
        rng = random.Random(seed)
        return Battle(rng.sample(self.pool, 3), rng.sample(self.pool, 3), player, Planner(seed=seed + 1),
                      seed=seed, record=True)

    def test_default_games_match_before_task_41(self):
        # Winner, final turn and full move-log digest captured on e93f191 before editing.
        before = {
            Learner: [(7, 1, 336, "18cadad34f011079e987d5e3531e19e310ec506e6598e2b1e026bc2b53d1879b"),
                      (41, 0, 412, "ee1043a85dbd93f6885bf176225b325b33f565d50fc76bee7902bddb73994753"),
                      (103, 0, 375, "201cc85a140cbea0ff7051fddfba621f74693f4da46830b371cf2491ff5ce5c3")],
            Engine: [(7, 1, 406, "9af9379405ed8e311650cbecc42658da59f619beb819154ea9421e6de3666684"),
                     (41, 0, 415, "c24511f1a6917bf7f59fe47ca113612acc84ac26c053eaa8dd8d8a616746d34c"),
                     (103, -1, 373, "6d3f1321ac152fc43483bf21ea903955a80b9c3eb6238d04a3fb3accf3c175e1")],
        }
        for kind, games in before.items():
            for seed, winner, turn, digest in games:
                for kw in ({}, {"shield_margin": 0.02}, {"shield_toward": False},
                           {"shield_margin": 0.02, "shield_toward": False}):
                    with self.subTest(kind=kind.__name__, seed=seed, settings=kw):
                        battle = self.battle(self.player(kind, seed, **kw), seed)
                        self.assertEqual(battle.run(), winner)
                        self.assertEqual(battle.turn, turn)
                        self.assertEqual(hashlib.sha256(json.dumps(battle.log).encode()).hexdigest(), digest)

    def test_toward_keeps_rulebook_shields_and_can_add_one(self):
        for kind in (Learner, Engine):
            player = self.player(kind, shield_toward=True)
            view = self.battle(player).views[0]
            for advice in (False, True):
                for values in ([1.0, 0.0], [0.0, 1.0]):
                    with patch.object(Planner, "shield", return_value=advice), patch.object(self.q, "values", return_value=values):
                        self.assertEqual(player.shield(view, 60), advice or values[1] > values[0])
            self.assertNotIn(("shield", 1, 0), player.departures)
            self.assertGreater(player.departures.get(("shield", 0, 1), 0), 0)

    def test_shield_margin_is_separate_and_uses_strict_comparison(self):
        player = self.player(shield_margin=0.1)
        view = self.battle(player).views[0]
        with patch.object(Planner, "shield", return_value=False):
            with patch.object(self.q, "values", return_value=[0.0, 0.1]):
                self.assertFalse(player.shield(view, 60))
            with patch.object(self.q, "values", return_value=[0.0, 0.11]):
                self.assertTrue(player.shield(view, 60))
        with patch.object(self.q, "values", return_value=[0.0, 0.05, 0.0]):
            self.assertEqual(player._decide("swap", view, (True, True, True), lambda: 0), 1)

    def test_margin_one_keeps_rulebook_even_at_probability_endpoints(self):
        for advice in (False, True):
            player = self.player(shield_margin=1)
            view = self.battle(player).views[0]
            with patch.object(Planner, "shield", return_value=advice), \
                    patch.object(self.q, "values", return_value=[float(advice), float(not advice)]):
                self.assertEqual(player.shield(view, 60), advice)

    def test_margin_one_matches_rulebook_on_game_prompts(self):
        prompts = []
        original = Learner.shield

        def checked(player, view, energy):
            advice = Planner.shield(player.clone(), view, energy)
            answer = original(player, view, energy)
            self.assertEqual(answer, advice)
            prompts.append(answer)
            return answer

        with patch.object(Learner, "shield", checked):
            for seed in (7, 41, 103):
                self.battle(self.player(seed=seed, shield_margin=1), seed).run()
        self.assertGreater(len(prompts), 5)

    def test_last_pokemon_and_forced_training_choices_keep_their_paths(self):
        player = self.player(shield_toward=True, shield_margin=1, last_always=False)
        view = self.battle(player).views[0]
        player.force("shield", 0)
        with patch.object(Planner, "shield", return_value=True):
            self.assertFalse(player.shield(view, 60))
        for mon in view.me.team[1:]:
            mon.hp = 0
        with patch.object(Planner, "shield", return_value=False):
            self.assertFalse(player.shield(view, 60))

    def test_imagined_players_keep_defaults(self):
        for kw in ({"shield_margin": 1}, {"shield_toward": True}):
            player = self.player(Engine, **kw)
            view = self.battle(player).views[0]
            made = []

            def learner(**settings):
                bot = Learner(**settings)
                made.append(bot)
                return bot

            with patch("pogo.engine.Learner", side_effect=learner):
                value = player._look(view, "throw", 0, 41)
            self.assertEqual(len(made), 2)
            for bot in made:
                self.assertEqual(bot.shield_margin, bot.margin)
                self.assertFalse(bot.shield_toward)
            baseline = self.player(Engine)
            self.assertEqual(value, baseline._look(view, "throw", 0, 41))
            self.assertEqual(player.clone().shield_margin, player.shield_margin)
            self.assertEqual(player.clone().shield_toward, player.shield_toward)


class Measurement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        versus.setup()
        bench.setup()

    def test_keys_reach_all_three_judges(self):
        # The exam's answer files are private; only build its candidate, without replaying an exam.
        with patch.object(exam.E, "versions", return_value={}), \
                patch.dict(exam.E._s, ev=Evaluator()), \
                patch.dict(exam.E.L._state, net=versus._state["net"], pool=versus._state["pool"]):
            for spec in ("shield_margin=0.05", "shield_margin=0.1", "shield_margin=1", "shield_toward=1", "shield_toward=0"):
                with patch.object(exam, "_variants", [spec]):
                    players = [versus.pilot(versus.parse("samples=32," + spec), 3),
                               bench.build("samples=32," + spec, 3), exam.builds(3)[spec]]
                settings = exam.parse(spec)
                for player in players:
                    for key, value in settings.items():
                        self.assertEqual(getattr(player, key), value)
                    for key, value in WEBSITE.items():
                        self.assertEqual(getattr(player, key), value)
        for parse in (versus.parse, exam.parse):
            with self.assertRaises(SystemExit):
                parse("shield_toward=2")

    def test_counting_does_not_change_the_game_or_count_copies(self):
        pool = versus._state["pool"]
        plain = versus.pilot(None, 3)
        counted = versus.ShieldCalls(versus.pilot(None, 3))
        games = [Battle(pool[:3], pool[10:13], p, Planner(seed=4), seed=5, record=True) for p in (plain, counted)]
        self.assertEqual(games[0].run(), games[1].run())
        self.assertEqual(games[0].log, games[1].log)
        blocks = sum(side == 0 and "shield" in note.lower() for _, side, note in games[1].log)
        self.assertEqual(counted.shields, blocks)
        self.assertGreaterEqual(counted.prompts, counted.shields)
        counts = counted.counts()
        counted.clone().shield(games[1].views[0], 60)
        self.assertEqual(counted.counts(), counts)

    def test_worker_chunks_add_counts_and_repeated_results_do_not_double_them(self):
        for field in ("h2h", "crowd", "pvpoke", "reader"):
            # The reader has its own search; one cheap look keeps this aggregation check small.
            with patch.dict(versus.CONFIRMED, samples=1, horizon=2):
                whole = versus.job((field, "bot", "bot", "bot", 0, 2, 41))
                parts = [versus.job((field, "bot", "bot", "bot", n, 1, 41)) for n in (0, 1)]
            saved = {}
            for part in reversed(parts):
                versus.record(saved, part)
            versus.record(saved, parts[0])
            self.assertEqual(saved["results"][field]["bot"], {str(n): v for n, v in whole[2].items()})
            calls = saved["shield_calls"][field]["bot"]
            self.assertEqual(calls, {str(n): v for n, v in whole[4].items()})
            self.assertGreater(sum(r["prompts"] for r in calls.values()), 0)
            if field == "h2h":
                self.assertGreater(sum(r["baseline"]["prompts"] for r in calls.values()), 0)
            for r in calls.values():
                self.assertLessEqual(r["shields"], 4 if field in ("h2h", "reader") else 2)
                self.assertLessEqual(r["shields"], r["prompts"])

    def test_zero_prompts_are_reported_without_a_rate(self):
        self.assertEqual(versus.shield_rate([{"shields": 0, "prompts": 0}]), "0 / 0 (n/a)")

    def test_one_battle_smoke_has_no_estimated_margin(self):
        score, margin = versus.estimate([1.0])
        self.assertEqual(score, 1.0)
        self.assertTrue(math.isnan(margin))
        self.assertEqual(versus.summary([1.0]), "100.0% ± nan")


if __name__ == "__main__":
    unittest.main()
