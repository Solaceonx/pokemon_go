import copy
import io
from contextlib import redirect_stderr
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from pogo.agents import Planner
from pogo.battle import Battle
from pogo.dqn import Agent, Network as FlatNetwork, Replay, transitions, N_FEATURES, N_MON
from pogo.dqn_relational import Network
from pogo.dqn_symmetry import feature_order, action_order
from pogo.gamedata import GameData


def inputs(n=4):
    x = np.random.default_rng(33).normal(.1, .2, (n, N_FEATURES)).astype(np.float32)
    for i in range(6): x[:, 13 + i * N_MON] = 1
    x[::2, 13 + 5 * N_MON] = 0  # an unrevealed opponent slot
    return x


class RelationalTests(unittest.TestCase):
    def test_shared_encoder_gradient_matches_finite_differences(self):
        net = Network(seed=13, hidden=8)
        net.p = [p.astype(np.float64) for p in net.p]
        for i in (1, 3, 5, 9): net.p[i].fill(.2)
        x = inputs().astype(np.float64)
        dq = np.random.default_rng(34).normal(size=(len(x), 9))
        _, cache = net.forward(x)
        gradients = net.backward(cache, dq)
        rng = np.random.default_rng(35)
        for i, p in enumerate(net.p):
            for index in rng.choice(p.size, min(4, p.size), replace=False):
                original = p.flat[index]
                p.flat[index] = original + 1e-6
                high = float((net.predict(x) * dq).sum())
                p.flat[index] = original - 1e-6
                low = float((net.predict(x) * dq).sum())
                p.flat[index] = original
                self.assertAlmostEqual((high - low) / 2e-6, gradients[i].flat[index], places=7)

    def test_bench_labels_are_equivariant_before_and_after_learning(self):
        net, x = Network(seed=14, hidden=8), inputs()
        for learned in (False, True):
            if learned:
                masks = np.ones((len(x), 9), bool)
                net.imitate(x, masks, np.array([3, 4, 7, 8]), rate=.01)
            expected = net.predict(x)
            for ours in (False, True):
                for foes in (False, True):
                    actual = net.predict(x[:, feature_order(ours, foes)])[:, action_order(ours)]
                    np.testing.assert_allclose(actual, expected, atol=1e-7, rtol=1e-5)
            np.testing.assert_allclose(net.predict(x[0]), expected[0], atol=1e-7)
        with self.assertRaises(ValueError): net.predict(np.zeros(800))
        with self.assertRaises(ValueError): net.predict(np.zeros((4, 122)))

    def test_classification_and_td_updates_reduce_their_losses(self):
        from pogo.counterfactual import classification_loss
        net, x = Network(seed=15, hidden=8), inputs(8)
        mask = np.zeros((8, 9), bool)
        mask[:, :2] = True
        actions = np.ones(8, int)
        before = classification_loss(net.predict(x), mask, actions)[0]
        for _ in range(30): net.imitate(x, mask, actions, rate=.003)
        self.assertLess(classification_loss(net.predict(x), mask, actions)[0], before)
        for moment in net.m + net.v: moment.fill(0)
        net.steps = 0
        targets = np.full(8, -.5)
        before = np.mean(abs(net.predict(x)[:, 1] - targets))
        for _ in range(70): net.update(x, actions, targets, rate=.003)
        self.assertLess(np.mean(abs(net.predict(x)[:, 1] - targets)), before)

    def test_checkpoint_restores_target_optimizer_and_exact_next_update(self):
        net, x = Network(seed=16, hidden=8), inputs()
        actions, targets = np.array([0, 3, 6, 8]), np.array([1., -.2, .5, -1.])
        net.update(x, actions, targets, rate=.001)
        target = copy.deepcopy(net)
        target.p[-1] += .2
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'relational.npz'
            net.save(path, {'epoch': 1}, target)
            restored, meta, restored_target = Network.load(path)
            self.assertEqual(meta, {'epoch': 1})
            for a, b in zip(target.p, restored_target.p): np.testing.assert_array_equal(a, b)
            net.update(x, actions, targets, rate=.001)
            restored.update(x, actions, targets, rate=.001)
            for a, b in zip(net.p + net.m + net.v, restored.p + restored.m + restored.v):
                np.testing.assert_array_equal(a, b)
            with self.assertRaises(ValueError): FlatNetwork.load(path)
            flat = Path(directory) / 'flat.npz'
            FlatNetwork(hidden=8).save(flat)
            with self.assertRaises(ValueError): Network.load(flat)

    def test_existing_public_agent_completes_a_legal_game(self):
        gd, net = GameData(), Network(seed=17, hidden=8)
        team = [gd.default(s) for s in ('melmetal', 'jellicent', 'altaria')]
        pilot = Agent(net, seed=18, record=True)
        game = Battle(team, list(reversed(team)), pilot, Planner(seed=19), seed=20)
        self.assertIn(game.run(), (-1, 0, 1))
        self.assertTrue(pilot.log)
        self.assertTrue(all(mask[action] for _, mask, action, _ in pilot.log))
        # Exercise the real trainer's atomic network/target/replay checkpoint interface.
        from scripts import double_dqn as trainer
        from scripts.double_dqn_relational import relational_backend
        replay = Replay(capacity=8)
        replay.add(transitions(pilot.log, 1.))
        target = copy.deepcopy(net)
        target.p[-1] += .1
        meta = {'numpy_rng': np.random.default_rng(21).bit_generator.state}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trainer.checkpoint(root, net, target, replay, meta)
            with relational_backend():
                restored, _, restored_target, restored_replay, _ = trainer.load_training(root, 21)
            self.assertEqual(restored_replay.size, replay.size)
            for a, b in zip(net.p, restored.p): np.testing.assert_array_equal(a, b)
            for a, b in zip(target.p, restored_target.p): np.testing.assert_array_equal(a, b)

    def test_trainer_backend_selection_is_explicit_and_restored_on_failure(self):
        from scripts import double_dqn as trainer
        from scripts.double_dqn_relational import relational_backend
        original = trainer.Network, trainer.ALGORITHM
        with self.assertRaisesRegex(RuntimeError, 'deliberate'):
            with relational_backend():
                self.assertIs(trainer.Network, Network)
                raise RuntimeError('deliberate')
        self.assertIs(trainer.Network, original[0])
        self.assertEqual(trainer.ALGORITHM, original[1])
        from scripts.double_dqn_relational import main
        with mock.patch('sys.argv', ['research', 'evaluate', '--run', 'unittest-no-final', '--split', 'test']), \
                mock.patch.object(trainer, 'main') as invoked, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): main()
            invoked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
