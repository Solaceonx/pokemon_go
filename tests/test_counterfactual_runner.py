import copy
import tempfile
from pathlib import Path
import unittest

import numpy as np

from pogo.dqn import Network, N_FEATURES
from scripts.counterfactual_rl import fit, save_labels


class CounterfactualRunnerTests(unittest.TestCase):
    def test_interrupted_fit_restores_optimizer_and_random_stream_exactly(self):
        rng = np.random.default_rng(42)
        x = rng.normal(0, .1, (12, N_FEATURES)).astype(np.float32)
        mask = np.zeros((12, 9), bool)
        mask[:, :3] = True
        returns = np.zeros((12, 9), np.float32)
        returns[:, :3] = [[1., -1., 0.], [-1., 1., 0.], [0., -1., 1.]] * 4
        groups = list(zip(x, mask, returns, np.zeros(12, int)))
        demo = (x, mask, np.zeros(12, int))
        initial = Network(hidden=8, seed=17)
        initial.steps = 123
        for moment in (*initial.m, *initial.v):
            moment.fill(7)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uninterrupted = fit(copy.deepcopy(initial), groups, demo, 3, .001, .01, 15, root / 'full.npz')
            fit(copy.deepcopy(initial), groups, demo, 1, .001, .01, 15, root / 'resume.npz')
            resumed = fit(Network(hidden=8, seed=999), groups, demo, 3, .001, .01, 15, root / 'resume.npz')
            self.assertEqual(uninterrupted.steps, 3)
            self.assertEqual(resumed.steps, uninterrupted.steps)
            for left, right in zip(uninterrupted.p + uninterrupted.m + uninterrupted.v,
                                   resumed.p + resumed.m + resumed.v):
                np.testing.assert_array_equal(left, right)
            save_labels(root / 'labels.npz', groups, {'episodes': 6})
            with np.load(root / 'labels.npz', allow_pickle=False) as data:
                np.testing.assert_array_equal(data['returns'], returns)
                np.testing.assert_array_equal(data['mask'], mask)


if __name__ == '__main__':
    unittest.main()
