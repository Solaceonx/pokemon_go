import unittest
import numpy as np

from pogo.offline_returns import initialize_q, objective, update
from pogo.standalone_rl import N_FEATURES
from pogo.standalone_rl_v2 import ActorCritic


class OfflineReturnTests(unittest.TestCase):
    def test_objective_gradient_and_illegal_actions(self):
        q = np.array([[.2, -.3, 5.], [-.4, .7, .1]], dtype=float)
        mask = np.array([[True, True, False], [True, True, True]])
        actions, targets = np.array([1, 2]), np.array([-1., 1.])
        _, gradient, _ = objective(q, mask, actions, targets, .1)
        for i in range(2):
            for j in range(3):
                plus, minus = q.copy(), q.copy()
                plus[i, j] += 1e-6
                minus[i, j] -= 1e-6
                numerical = (objective(plus, mask, actions, targets, .1)[0] -
                             objective(minus, mask, actions, targets, .1)[0]) / 2e-6
                self.assertAlmostEqual(gradient[i, j], numerical, places=7)
        self.assertEqual(gradient[0, 2], 0)
        with self.assertRaisesRegex(ValueError, "legal"):
            objective(q, mask, np.array([2, 2]), targets)

    def test_positive_scaling_preserves_greedy_choices_and_resets_moments(self):
        model = ActorCritic(4, hidden=4)
        x = np.random.default_rng(2).normal(size=(16, N_FEATURES)).astype(np.float32)
        mask = np.ones((16, 6), bool)
        before = model.forward(x, "act", mask)[0].argmax(axis=1)
        model.m['act.out_b'][:] = 1
        initialize_q(model, .1)
        np.testing.assert_array_equal(before, model.forward(x, "act", mask)[0].argmax(axis=1))
        self.assertTrue(all(not a.any() for a in model.m.values()))

    def test_return_fit_moves_observed_q_and_leaves_other_heads_unchanged(self):
        model = ActorCritic(9, hidden=4)
        initialize_q(model)
        x = np.zeros((8, N_FEATURES), np.float32)
        mask = np.ones((8, 2), bool)
        actions, returns = np.ones(8, int), np.ones(8, np.float32)
        untouched = {k: v.copy() for k, v in model.params.items() if not k.startswith('shield.')}
        before = objective(model._branch(x, 'shield')[0], mask, actions, returns)[0]
        for _ in range(30):
            update(model, 'shield', x, mask, actions, returns, rate=.01)
        after = objective(model._branch(x, 'shield')[0], mask, actions, returns)[0]
        self.assertLess(after, before)
        for k, value in untouched.items():
            np.testing.assert_array_equal(value, model.params[k])


if __name__ == '__main__':
    unittest.main()
