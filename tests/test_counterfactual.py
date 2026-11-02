import unittest
import numpy as np

from pogo.agents import Planner
from pogo.battle import Battle
from pogo.dqn import Agent, Network, N_FEATURES
from pogo.engine import Engine
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData
from pogo.counterfactual import (advantage_loss, classification_loss, imitate, improve,
                                 isolated_clone, StepRecorder, replay_choice)


class CounterfactualTests(unittest.TestCase):
    def test_classification_gradient_masks_and_finite_difference(self):
        q = np.array([[.2, -.1, .7], [0., .4, .8]], dtype=float)
        mask = np.array([[True, True, False], [False, True, True]])
        action = np.array([1, 2])
        weights = np.array([.5, 3.])
        loss, derivative = classification_loss(q, mask, action, weights, .3)
        self.assertGreater(loss, 0)
        np.testing.assert_array_equal(derivative[~mask], 0)
        for i in range(2):
            for j in range(3):
                a, b = q.copy(), q.copy()
                a[i, j] += 1e-6
                b[i, j] -= 1e-6
                numerical = (classification_loss(a, mask, action, weights, .3)[0]
                             - classification_loss(b, mask, action, weights, .3)[0]) / 2e-6
                self.assertAlmostEqual(numerical, derivative[i, j], places=6)

    def test_advantage_is_invariant_to_common_return_offset(self):
        q = np.array([[.2, -.4, 99.], [.1, .3, .9]])
        mask = np.array([[True, True, False], [True, True, True]])
        returns = np.array([[1., -1., 0.], [.2, .5, -.7]])
        loss, grad = advantage_loss(q, mask, returns)
        other_loss, other_grad = advantage_loss(q + 10, mask, returns + 4)
        self.assertAlmostEqual(loss, other_loss)
        np.testing.assert_allclose(grad, other_grad, atol=1e-12)
        np.testing.assert_allclose(grad.sum(axis=1), 0, atol=1e-12)
        self.assertEqual(grad[0, 2], 0)

    def test_equal_outcomes_do_not_erase_existing_policy(self):
        q = np.array([[.2, -.8, 1.5]])
        loss, grad = advantage_loss(q, np.ones_like(q, bool), np.ones_like(q))
        self.assertEqual(loss, 0)
        np.testing.assert_array_equal(grad, 0)

    def test_paired_advantage_gradient_finite_difference(self):
        q = np.array([[.2, -.4, .1], [.1, .3, .9]])
        mask = np.array([[True, True, False], [True, True, True]])
        returns = np.array([[.2, -.1, 0.], [.2, .1, -.1]])
        _, grad = advantage_loss(q, mask, returns)
        for i in range(2):
            for j in range(3):
                a, b = q.copy(), q.copy()
                a[i, j] += 1e-6
                b[i, j] -= 1e-6
                numerical = (advantage_loss(a, mask, returns)[0] - advantage_loss(b, mask, returns)[0]) / 2e-6
                self.assertAlmostEqual(numerical, grad[i, j], places=6)

    def test_classification_and_counterfactual_updates_learn(self):
        net = Network(hidden=16)
        x = np.ones((8, N_FEATURES), np.float32) * .1
        mask = np.zeros((8, 9), bool)
        mask[:, :2] = True
        actions = np.ones(8, int)
        before = classification_loss(net.predict(x), mask, actions)[0]
        for _ in range(40): imitate(net, x, mask, actions, rate=.003)
        self.assertLess(classification_loss(net.predict(x), mask, actions)[0], before)
        y = np.zeros((8, 9), np.float32)
        y[:, 0], y[:, 1] = 1, -1
        old = advantage_loss(net.predict(x), mask, y)[0]
        for _ in range(100): improve(net, x, mask, y, rate=.001)
        self.assertLess(advantage_loss(net.predict(x), mask, y)[0], old)

    def test_engine_cache_copies_preserve_bookkeeping(self):
        gd = GameData()
        engine = Engine(Evaluator(), gd.meta(8), samples=1)
        engine._outlooks['test'] = .2
        engine.evaluator._agent._outlooks['other'] = -.3
        engine._their_throw = 1
        clone = isolated_clone(engine)
        clone._outlooks['test'] = .9
        clone.evaluator._agent._outlooks['other'] = .5
        self.assertEqual(engine._outlooks['test'], .2)
        self.assertEqual(engine.evaluator._agent._outlooks['other'], -.3)
        self.assertEqual(clone._their_throw, 1)

    def test_replaying_actual_choice_reproduces_whole_game_for_both_sides(self):
        gd, net = GameData(), Network(hidden=16)
        net.p[-1][1] = 10
        team = [gd.default(s) for s in ('melmetal', 'jellicent', 'altaria')]
        for side in (0, 1):
            players = [Planner(seed=2), Planner(seed=3)]
            players[side] = Agent(net, seed=4)
            recorder = StepRecorder(players[side])
            agents = list(players)
            agents[side] = recorder
            b = Battle(team, list(reversed(team)), *agents, seed=8)
            cases = []
            by_kind = {}
            while b.winner is None:
                recorder.calls.clear()
                snapshot = (b.clone(None, None), [isolated_clone(p) for p in players])
                b.step()
                # Include actions, shields and replacements, irrespective of the eventual win/loss.
                for index, call in enumerate(recorder.calls):
                    if len(call['options']) > 1 and by_kind.get(call['kind'], 0) < 3:
                        cases.append((snapshot, index, call['native']))
                        by_kind[call['kind']] = by_kind.get(call['kind'], 0) + 1
            expected = 0. if b.winner == -1 else 1. if b.winner == side else -1.
            self.assertTrue(cases)
            self.assertEqual(set(by_kind), {'act', 'shield', 'replace'})
            for snapshot, index, choice in cases:
                self.assertEqual(replay_choice(snapshot, index, choice, side), expected)


if __name__ == '__main__':
    unittest.main()
