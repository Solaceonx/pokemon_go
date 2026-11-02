import unittest

import numpy as np

from pogo.dqn_residual import centered_residual_loss


class ResidualObjectiveTests(unittest.TestCase):
    def test_equal_returns_retain_the_reference_preferences_exactly(self):
        reference = np.array([[.4, .1, -.3, 99.], [-.2, .5, .3, 88.]], np.float32)
        mask = np.array([[1, 1, 1, 0], [1, 1, 1, 0]], bool)
        loss, gradient = centered_residual_loss(reference, mask, reference, np.ones_like(reference), .1)
        self.assertEqual(loss, 0)
        np.testing.assert_array_equal(gradient, 0)
        # Two equally winning options retain their original preference, while the losing one is demoted.
        returns = np.array([[1., 1., -1., 0.], [-1., 1., 1., 0.]])
        updated = reference.astype(float) + .25 * returns
        loss, gradient = centered_residual_loss(updated, mask, reference, returns, .25)
        self.assertAlmostEqual(loss, 0, places=14)
        np.testing.assert_allclose(gradient, 0, atol=1e-14)
        self.assertAlmostEqual(updated[0, 0] - updated[0, 1], reference[0, 0] - reference[0, 1])

    def test_gradient_matches_finite_differences_in_both_huber_regions(self):
        q = np.array([[2.1, -.4, 0., 9.], [.1, .3, .5, -.8]])
        reference = np.array([[.1, .2, -.3, 8.], [.4, -.2, .2, .1]])
        mask = np.array([[1, 1, 1, 0], [0, 1, 1, 1]], bool)
        returns = np.array([[1., -1., 1., 0.], [0., 1., -1., 1.]])
        _, gradient = centered_residual_loss(q, mask, reference, returns)
        for i in range(2):
            for j in range(4):
                high, low = q.copy(), q.copy()
                high[i, j] += 1e-6
                low[i, j] -= 1e-6
                numerical = (centered_residual_loss(high, mask, reference, returns)[0]
                             - centered_residual_loss(low, mask, reference, returns)[0]) / 2e-6
                self.assertAlmostEqual(numerical, gradient[i, j], places=7)
        np.testing.assert_array_equal(gradient[~mask], 0)
        np.testing.assert_allclose(gradient.sum(axis=1), 0, atol=1e-14)

    def test_reference_anchor_and_common_offsets(self):
        reference = np.array([[.2, -.4, .8]])
        q = np.array([[.4, .2, -.1]])
        mask = np.ones_like(q, bool)
        returns = np.array([[1., -1., 0.]])
        loss, gradient = centered_residual_loss(q, mask, reference, returns)
        other, shifted = centered_residual_loss(q + 7, mask, reference - 3, returns + 4)
        self.assertAlmostEqual(loss, other)
        np.testing.assert_allclose(gradient, shifted, atol=1e-14)
        self.assertEqual(centered_residual_loss(reference, mask, reference)[0], 0)
        self.assertGreater(centered_residual_loss(q, mask, reference)[0], 0)


if __name__ == '__main__':
    unittest.main()
