"""Public-information boundary, actual learning, checkpoint/resume and fair scoring."""
import itertools
import json
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from pogo.battle import Battle
from pogo.gamedata import GameData
from pogo.rl_experiment import BASELINE, FrozenRuntime, evaluate, freeze, intervals, schedule, stream_seed, team_key, team_split
from pogo.standalone_rl import ActorCritic, N_FEATURES, StandaloneAgent, encode, mask_for
from scripts.standalone_rl import advantages


class StandaloneRL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.teams = [[cls.gd.default(sp) for sp in species] for species in
                     (("melmetal", "jellicent", "altaria"), ("azumarill", "umbreon", "medicham"))]

    def battle(self):
        return Battle(*self.teams, None, None, seed=12)

    def test_only_public_properties_and_legal_actions_are_required(self):
        view = self.battle().views[0]
        public = SimpleNamespace(**{name: getattr(view, name) for name in
                                   ("me", "foe", "foe_shown", "foe_left", "foe_shields", "foe_switch_wait", "foe_busy", "turn", "legal")})
        x = encode(public)
        self.assertEqual(x.shape, (N_FEATURES,))
        self.assertTrue(np.isfinite(x).all())
        agent = StandaloneAgent(ActorCritic(hidden=16), seed=3)
        self.assertIn(agent.act(public), view.legal())
        self.assertIn(agent.replace(public), view.me.bench())

    def test_unrevealed_opponent_cannot_change_features_or_policy(self):
        battle = self.battle()
        x = encode(battle.views[0])
        hidden = battle.sides[1].team[1]
        hidden.build, hidden.hp, hidden.energy = self.gd.default("mimikyu"), 5, 100
        np.testing.assert_array_equal(x, encode(battle.views[0]))
        model = ActorCritic(hidden=16)
        a, b = StandaloneAgent(model, 19), StandaloneAgent(model, 19)
        self.assertEqual(a.act(battle.views[0]), b.act(battle.views[0]))

    def test_public_revealed_bench_and_form_features_are_visible(self):
        battle = self.battle()
        x = encode(battle.views[0])
        battle.sides[1].shown.append(1)
        self.assertFalse(np.array_equal(x, encode(battle.views[0])))
        battle.sides[0].team[0].build = self.gd.default("mimikyu")
        self.assertTrue(np.isfinite(encode(battle.views[0])).all())

    def test_masking_gives_illegal_actions_exactly_zero_probability(self):
        view, model = self.battle().views[0], ActorCritic(hidden=16)
        mask = mask_for(view, "act")
        p = model.forward(encode(view)[None], "act", mask[None])[0][0]
        self.assertTrue(np.all(p[~mask] == 0))
        self.assertAlmostEqual(float(p.sum()), 1., places=6)
        view.me.shields = 0
        self.assertFalse(StandaloneAgent(model).shield(view, 100))

    def test_positive_advantage_increases_selected_action_probability(self):
        model, view = ActorCritic(hidden=16), self.battle().views[0]
        x, mask = encode(view)[None], mask_for(view, "act")[None]
        p, value, _ = model.forward(x, "act", mask)
        action = np.array([4])
        model.update("act", x, mask, action, value, advantages=np.array([1.]), old_logp=np.log(p[:, 4]),
                     entropy=0., rate=.001)
        self.assertGreater(model.forward(x, "act", mask)[0][0, 4], p[0, 4])

    def test_ppo_clips_an_already_overlarge_positive_ratio(self):
        model, view = ActorCritic(hidden=16), self.battle().views[0]
        x, mask = encode(view)[None], mask_for(view, "act")[None]
        p, value, _ = model.forward(x, "act", mask)
        old = {k: v.copy() for k, v in model.params.items()}
        model.update("act", x, mask, np.array([0]), value, advantages=np.array([1.]),
                     old_logp=np.log(p[:, 0]) - np.log(2), entropy=0.)
        for k, expected in old.items():
            np.testing.assert_array_equal(expected, model.params[k])

    def test_checkpoint_restores_optimizer_for_identical_next_update(self):
        model, view = ActorCritic(hidden=16), self.battle().views[0]
        x, mask = encode(view)[None], mask_for(view, "act")[None]
        args = ("act", x, mask, np.array([0]), np.array([1.], np.float32))
        model.update(*args, imitation=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checkpoint.npz"
            model.save(path, {"round": 7})
            restored, meta = ActorCritic.load(path)
        self.assertEqual(meta["round"], 7)
        model.update(*args, imitation=True)
        restored.update(*args, imitation=True)
        for k in model.params:
            np.testing.assert_array_equal(model.params[k], restored.params[k])

    def test_episode_advantages_do_not_bootstrap_from_next_game(self):
        rows = [("act", None, None, 0, 0., value) for value in (.2, -.3, .5)]
        result = advantages(rows, 1., lam=1.)
        np.testing.assert_allclose([r[7] for r in result], 1.)
        np.testing.assert_allclose([r[6] for r in result], [.8, 1.3, .5])
        self.assertEqual(advantages([], -1.), [])

    def test_all_team_orders_and_leads_share_partition(self):
        team = self.teams[0]
        for order in itertools.permutations(team):
            self.assertEqual(team_split(order), team_split(team))
            self.assertEqual(team_key(order), team_key(team))
        self.assertEqual(team_split([b.species_id for b in team]), team_split(team))

    def test_seed_domains_and_pairing_bootstrap(self):
        self.assertNotEqual(stream_seed(1, "train", 1), stream_seed(1, "test", 1))
        report = intervals([0., .5, 1., 1.], seed=3)
        self.assertEqual(report, intervals([0., .5, 1., 1.], seed=3))
        self.assertEqual(report["battles"], 8)
        self.assertEqual(report["score"], .625)
        self.assertLessEqual(report["hoeffding_lower97_5"], report["score"])
        self.assertEqual(intervals([.5] * 40)["ci95"], [.5, .5])
        with self.assertRaises(ValueError):
            intervals([1.])

    def test_agent_can_play_a_complete_battle_without_rules(self):
        model = ActorCritic(hidden=16)
        battle = Battle(*self.teams, StandaloneAgent(model, 1), StandaloneAgent(model, 2), seed=3)
        self.assertIn(battle.run(), (-1, 0, 1))


class FrozenExperiment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = freeze("59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9")
        cls.runtime = FrozenRuntime(cls.path)

    def test_source_namespace_settings_and_evaluator_caches_are_independent(self):
        runtime = self.runtime
        a, b = runtime.engine(1), runtime.engine(2)
        self.assertNotEqual(type(a).__module__, "pogo.engine")
        self.assertEqual(a.samples, 32)
        self.assertEqual(a.rollout, "bot")
        self.assertIsNot(a.evaluator, b.evaluator)
        self.assertIsNot(a.evaluator._agent._outlooks, b.evaluator._agent._outlooks)
        self.assertEqual(runtime.manifest["baseline"], BASELINE)

    def test_schedules_repeat_and_obey_team_partitions(self):
        a = schedule(self.runtime, "validation", "mixed", 41, 10)
        self.assertEqual(a, schedule(self.runtime, "validation", "mixed", 41, 10))
        for case in a:
            for team in case["teams"]:
                self.assertEqual(team_split(team), "validation")
            self.assertEqual(len(set(sum(case["seeds"], []))), 6)

    def test_snapshot_tampering_is_rejected(self):
        from pogo.rl_experiment import verify_snapshot, atomic_json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "engine.py").write_text("modified")
            atomic_json(root / "manifest.json", {"files": {"engine.py": "bad_hash"}, "baseline": BASELINE})
            with self.assertRaisesRegex(ValueError, "modified"):
                verify_snapshot(root)

    def test_evaluation_resume_binds_weights_and_discards_partial_row(self):
        model = ActorCritic(hidden=16)
        cases = schedule(self.runtime, "validation", "standard", 45, 2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.jsonl"
            first = evaluate(self.runtime, model, cases, path, opponent="learner")
            with path.open("ab") as f:
                f.write(b'{"index":2')
            second = evaluate(self.runtime, model, cases, path, opponent="learner")
            self.assertEqual(first, second)
            model.params["act.b"][0] += .1
            with self.assertRaisesRegex(ValueError, "provenance mismatch"):
                evaluate(self.runtime, model, cases, path, opponent="learner")

    def test_pairing_reverses_agent_seat_and_team_allocation(self):
        calls = []
        runtime = self.runtime
        class FakeBattle:
            def __init__(self, a, b, agent_a, agent_b, seed):
                calls.append(([m.species_id for m in a], [m.species_id for m in b],
                              isinstance(agent_a, StandaloneAgent), isinstance(agent_b, StandaloneAgent)))
            def run(self):
                return 0
        fake = SimpleNamespace(gd=runtime.gd, manifest=runtime.manifest, Battle=FakeBattle,
                               opponent=lambda *args: object())
        cases = schedule(runtime, "validation", "standard", 45, 2)
        with tempfile.TemporaryDirectory() as folder:
            result = evaluate(fake, ActorCritic(hidden=16), cases, Path(folder) / "r.jsonl")
        self.assertEqual(result["score"], .5)
        self.assertEqual(result["wins"], 2)
        self.assertEqual(result["losses"], 2)
        for a, b in zip(calls[::2], calls[1::2]):
            self.assertEqual(a[:2], b[:2])
            self.assertEqual(a[2:], (True, False))
            self.assertEqual(b[2:], (False, True))


if __name__ == "__main__":
    unittest.main()
