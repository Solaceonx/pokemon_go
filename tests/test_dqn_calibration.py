import copy
import unittest
import numpy as np
from pogo.dqn import Network
from pogo.dqn_calibration import fit, statistics


class CalibrationTests(unittest.TestCase):
    def test_finds_better_return_choice_and_penalty_can_retain_reference(self):
        q = np.zeros((8, 9), np.float32)
        q[:, 0] = .1
        mask = np.zeros_like(q, bool)
        mask[:, :2] = True
        returns = np.zeros_like(q)
        returns[:, 0], returns[:, 1] = -1, 1
        chosen = np.zeros(8, int)
        fitted = fit(q, mask, returns, chosen, per_scale=100, penalties=(0., 3.))
        self.assertEqual(fitted['0.0']['proxy_return_gain'], 2)
        self.assertEqual(fitted['0.0']['changed_fraction'], 1)
        self.assertEqual(fitted['3.0']['changed_fraction'], 0)
        np.testing.assert_array_equal(fitted['3.0']['offsets'], 0)
        tied = fit(q, mask, np.ones_like(q), chosen, per_scale=100)
        for variant in tied.values():
            np.testing.assert_array_equal(variant['offsets'], 0)

    def test_bias_change_has_no_other_parameter_or_reference_side_effects(self):
        original = Network(seed=34, hidden=8)
        candidate = copy.deepcopy(original)
        offsets = np.array([0, .2, -.1, .3, -.4, 0, .1, 0, -.2], np.float32)
        candidate.p[5] += offsets
        x = np.random.default_rng(35).normal(size=(6, 400)).astype(np.float32)
        np.testing.assert_allclose(candidate.predict(x), original.predict(x) + offsets, atol=1e-6)
        for a, b in zip(original.p[:5], candidate.p[:5]):
            np.testing.assert_array_equal(a, b)
        np.testing.assert_array_equal(candidate.p[5] - original.p[5], offsets)
        mask = np.zeros((6, 9), bool)
        mask[:, [5, 6]] = True
        returns = np.zeros((6, 9), np.float32)
        returns[:, 6] = 1
        q = original.predict(x)
        chosen = np.where(mask, q, -np.inf).argmax(axis=1)
        self.assertGreaterEqual(statistics(q, mask, returns, chosen, offsets)['proxy_return_gain'], 0)


if __name__ == '__main__':
    unittest.main()
