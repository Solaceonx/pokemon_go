import itertools
from pathlib import Path
import tempfile
import unittest

import numpy as np

from pogo.battle import Battle
from pogo.agents import Planner
from pogo.gamedata import GameData
from pogo.dqn import Agent, Network, Replay, N_FEATURES, observation, transitions, double_targets
from scripts.double_dqn import bucket, ci


class DoubleDQNTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.team = [cls.gd.default(s) for s in ('melmetal', 'jellicent', 'altaria')]

    def battle(self):
        return Battle(self.team, list(reversed(self.team)), Planner(seed=1), Planner(seed=2), seed=3)

    def test_hidden_team_and_rng_cannot_enter_observation(self):
        b = self.battle()
        view = b.views[0]
        class PublicOnly:
            def __getattr__(self, name):
                if name.startswith('_'):
                    raise AssertionError('private state accessed: ' + name)
                return getattr(view, name)
        before = b.rng.getstate()
        x, mask = observation(PublicOnly())
        b.sides[1].team[1].hp = 0
        b.sides[1].team[2].energy = 100
        # Public foe_left changes; preserve it when comparing private unrevealed states.
        b.sides[1].team[1].hp = 1
        y, other = observation(PublicOnly())
        np.testing.assert_array_equal(x, y)
        np.testing.assert_array_equal(mask, other)
        self.assertEqual(b.rng.getstate(), before)
        self.assertEqual(x.shape, (N_FEATURES,))

    def test_masks_actions_and_replacement_slots(self):
        b = self.battle()
        v = b.views[0]
        _, m = observation(v)
        self.assertEqual(np.flatnonzero(m).tolist(), [0, 3, 4])
        v.me.mon.energy = 100
        _, m = observation(v)
        self.assertTrue(m[1] and m[2])
        v.me.active = 1
        net = Network()
        net.p[-1][4] = 100
        agent = Agent(net)
        self.assertEqual(agent.act(v), 5)  # second relative bench is actual slot 2
        v.me.switch_wait = 90
        _, m = observation(v)
        self.assertFalse(m[3] or m[4])
        v.me.team[0].hp = 0
        self.assertEqual(agent.replace(v), 2)

    def test_double_target_selects_online_and_evaluates_target(self):
        class Fixed:
            def __init__(self, values): self.values = np.array(values)
            def predict(self, x): return self.values
        online = Fixed([[1., 2., 999.], [4., 3., 0.]])
        target = Fixed([[30., 10., 100.], [5., 50., 0.]])
        actual = double_targets(online, target, np.zeros((2, 1)),
                                np.array([[True, True, False], [True, True, True]]),
                                np.array([.2, -1]), np.array([.5, 0.]))
        np.testing.assert_allclose(actual, [5.2, -1.])

    def test_potential_rewards_telescope_and_terminal_does_not_bootstrap(self):
        x = np.zeros(N_FEATURES, np.float32)
        mask = np.ones(9, bool)
        log = [(x, mask, 0, p) for p in (.1, .2, -.3)]
        rows = list(transitions(log, 1., nstep=1))
        self.assertAlmostEqual(sum(r[3] for r in rows), .9)
        self.assertEqual([r[6] for r in rows], [1., 1., 0.])
        self.assertAlmostEqual(list(transitions(log, 1., nstep=8))[0][3], .9)

    def test_split_is_disjoint_and_independent_of_lead(self):
        names = ('melmetal', 'jellicent', 'altaria')
        self.assertEqual(len({bucket(t) for t in itertools.permutations(names)}), 1)
        pools = {s: set() for s in ('train', 'validation', 'test')}
        for t in itertools.combinations(range(30), 3):
            names = tuple(map(str, t))
            pools[bucket(names)].add(names)
        self.assertTrue(all(pools.values()))
        for a, b in itertools.combinations(pools, 2):
            self.assertFalse(pools[a] & pools[b])

    def test_checkpoint_preserves_optimizer_and_target_and_replay(self):
        rng = np.random.default_rng(2)
        x = rng.normal(0, .2, (8, N_FEATURES)).astype(np.float32)
        actions, y = np.arange(8), np.linspace(-1, 1, 8)
        net, target = Network(hidden=16), Network(seed=3, hidden=16)
        net.update(x, actions, y)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'net.npz'
            net.save(p, {'games': 7}, target)
            other, meta, loaded_target = Network.load(p)
            self.assertEqual(meta['games'], 7)
            for a, b in zip(target.p, loaded_target.p): np.testing.assert_array_equal(a, b)
            net.update(x, actions, y)
            other.update(x, actions, y)
            for a, b in zip(net.p, other.p): np.testing.assert_array_equal(a, b)
            replay = Replay(10)
            replay.add(transitions([(x[0], np.ones(9, bool), 0, .1)], 1.))
            replay.save(Path(d) / 'replay.npz')
            loaded = Replay.load(Path(d) / 'replay.npz')
            self.assertEqual((loaded.size, loaded.cursor), (1, 1))
            np.testing.assert_array_equal(replay.x, loaded.x)

    def test_learning_loss_falls_and_standalone_battle_finishes(self):
        net = Network(hidden=16)
        x = np.zeros((16, N_FEATURES), np.float32)
        actions, y = np.zeros(16, dtype=int), np.ones(16, np.float32)
        before = float(np.mean((net.predict(x)[:, 0] - y) ** 2))
        for _ in range(30): net.update(x, actions, y, rate=.01)
        after = float(np.mean((net.predict(x)[:, 0] - y) ** 2))
        self.assertLess(after, before)
        b = Battle(self.team, list(reversed(self.team)), Agent(net, record=True), Planner(seed=3), seed=5)
        self.assertIn(b.run(), (-1, 0, 1))
        self.assertTrue(b.agents[0].log)

    def test_cluster_interval_counts_mirrored_pair_once(self):
        self.assertEqual(ci([.5] * 100)['score'], .5)
        self.assertGreater(ci([.5] * 100)['margin95'], 0)
        result = ci([0., 1.])
        self.assertEqual(result['clusters'], 2)
        self.assertAlmostEqual(result['margin95'], .98)


if __name__ == '__main__':
    unittest.main()
