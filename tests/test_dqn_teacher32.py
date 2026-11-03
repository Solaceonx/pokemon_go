import copy
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

import numpy as np
from pogo.agents import Planner
from pogo.battle import Battle
from pogo.dqn import Replay
from pogo.dqn_relational import Network
from pogo.gamedata import GameData
from pogo.teamlist import drawer
from scripts.dqn_teacher32_trial import collect, fit


class StandInFrozen:
    """Exercise real public recorder/game semantics without starting another engine-search worker."""
    def __init__(self):
        gd = GameData()
        self.mixed_draw = drawer(gd, gd.meta(15))
        self.sample_calls, self.games = [], []

    def engine(self, seed, samples):
        self.sample_calls.append(samples)
        return Planner(seed=seed)

    def game(self, a, b, p, q, seed):
        game = Battle(a, b, p, q, seed=seed)
        winner = game.run()
        result = 0. if winner == -1 else 1. if winner == 0 else -1.
        self.games.append((list(p.log), list(q.log), result))
        return result, game


class Teacher32Tests(unittest.TestCase):
    def settings(self):
        return {'capacity': 4096, 'seed': 38801, 'maximum_games': 2, 'teacher_samples': 32,
                'checkpoint_every_games': 1, 'reference_sha256': 'unit-reference'}

    def test_both_public_teachers_record_correct_signed_returns_and_resume_exactly(self):
        reference = Network(seed=36, hidden=8)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            whole_f = StandInFrozen()
            whole = collect(whole_f, reference, root / 'whole.npz', self.settings(), lambda: False)
            first_f = StandInFrozen()
            collect(first_f, reference, root / 'resumed.npz', self.settings(), lambda: len(first_f.games) >= 1)
            resumed_f = StandInFrozen()
            resumed = collect(resumed_f, reference, root / 'resumed.npz', self.settings(), lambda: False)
            self.assertEqual(whole_f.sample_calls, [32] * 4)
            self.assertEqual(first_f.sample_calls + resumed_f.sample_calls, [32] * 4)
            self.assertEqual(whole.info, resumed.info)
            self.assertEqual(whole.info['games'], 2)
            self.assertGreater(whole.size, 0)
            for name in ('x', 'mask', 'action', 'reward', 'next_x', 'next_mask', 'discount', 'mc', 'priority'):
                np.testing.assert_array_equal(getattr(whole, name)[:whole.size], getattr(resumed, name)[:resumed.size])
            expected = []
            for p_log, q_log, result in whole_f.games:
                expected.extend(result - phi for _, _, _, phi in p_log)
                expected.extend(-result - phi for _, _, _, phi in q_log)
            np.testing.assert_allclose(whole.mc[:whole.size], expected, atol=1e-7)
            self.assertTrue(whole.mask[np.arange(whole.size), whole.action[:whole.size]].all())

    def test_changed_teacher_settings_are_rejected_before_any_more_games(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            path = Path(directory) / 'data.npz'
            f = StandInFrozen()
            net = Network(seed=37, hidden=8)
            collect(f, net, path, self.settings(), lambda: len(f.games) >= 1)
            second = StandInFrozen()
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                collect(second, net, path, dict(self.settings(), seed=38802), lambda: False)
            self.assertFalse(second.sample_calls)

    def test_teacher_fit_restores_exact_next_epoch_and_preserves_reference(self):
        reference = Network(seed=38, hidden=8)
        original = copy.deepcopy(reference)
        demos = Replay(capacity=8)
        demos.size = 8
        demos.x[:] = np.random.default_rng(39).normal(.1, .2, (8, 400))
        for mon in range(6): demos.x[:, 13 + mon * 48] = 1
        demos.mask[:, :2] = True
        demos.action[:] = 1
        settings = {'seed': 38802, 'epochs': 6, 'batch': 4, 'rate': .003}
        identity = {'dataset_sha256': 'unit-data', 'reference_sha256': 'unit-reference'}
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            whole_path, resumed_path = Path(directory) / 'whole.npz', Path(directory) / 'resumed.npz'
            calls = 0
            def interrupted_after_one_epoch():
                nonlocal calls
                calls += 1
                return calls > 2
            self.assertIsNone(fit(reference, demos, resumed_path, settings, identity, interrupted_after_one_epoch))
            _, meta, _ = Network.load(resumed_path)
            self.assertEqual(meta['epoch'], 1)
            self.assertEqual(meta['settings'], settings)
            resumed = fit(reference, demos, resumed_path, settings, identity, lambda: False)
            whole = fit(reference, demos, whole_path, settings, identity, lambda: False)
            for a, b in zip(resumed.p + resumed.m + resumed.v, whole.p + whole.m + whole.v):
                np.testing.assert_array_equal(a, b)
            for a, b in zip(reference.p + reference.m + reference.v, original.p + original.m + original.v):
                np.testing.assert_array_equal(a, b)
            from pogo.counterfactual import classification_loss
            before = classification_loss(reference.predict(demos.x), demos.mask, demos.action)[0]
            after = classification_loss(whole.predict(demos.x), demos.mask, demos.action)[0]
            self.assertLess(after, before)


if __name__ == '__main__':
    unittest.main()
