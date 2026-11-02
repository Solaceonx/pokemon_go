import unittest

import numpy as np

from pogo.battle import Battle
from pogo.dqn import Network, N_FEATURES, observation, ordered
from pogo.dqn_symmetry import feature_order, action_order, permute, augment, SymmetricPolicy
from pogo.gamedata import GameData


class DqnSymmetryTests(unittest.TestCase):
    def test_matches_physical_bench_reordering_in_all_decision_types(self):
        gd = GameData()
        team = [gd.default(s) for s in ('melmetal', 'jellicent', 'altaria')]
        original = Battle(team, list(reversed(team)), None, None)
        original.sides[0].active = 1
        original.sides[0].shown = [0, 1, 2]
        original.sides[1].shown = [0, 1, 2]
        for i, side in enumerate(original.sides):
            for j, mon in enumerate(side.team):
                mon.energy, mon.hp = 30 + 10 * j, mon.hp - j * 7
                mon.atk_stage, mon.def_stage = i, -j
        original.sides[0].mon.energy = 100
        for ours in (False, True):
            for foes in (False, True):
                changed = original.clone(None, None)
                if ours:
                    changed.sides[0].team = [changed.sides[0].team[j] for j in (2, 1, 0)]
                    changed.sides[0].shown = [2, 1, 0]
                if foes:
                    changed.sides[1].shown = [0, 2, 1]
                for kind in ('act', 'shield', 'replace'):
                    energy = 70 if kind == 'shield' else None
                    x, mask = observation(original.views[0], kind, energy)
                    actual_x, actual_mask = observation(changed.views[0], kind, energy)
                    action = np.flatnonzero(mask)[-1]
                    px, pm, pa = permute(x, mask, action, ours, foes)
                    np.testing.assert_array_equal(px, actual_x)
                    np.testing.assert_array_equal(pm, actual_mask)
                    self.assertTrue(actual_mask[pa])
                    if kind == 'replace' or (kind == 'act' and action in (3, 4)):
                        offset = 6 if kind == 'replace' else 2
                        a = original.sides[0].team[ordered(original.views[0])[0][action - offset]].build
                        b = changed.sides[0].team[ordered(changed.views[0])[0][pa - offset]].build
                        self.assertEqual(a.species_id, b.species_id)

    def test_invariant_prediction_is_equivariant_to_bench_labels(self):
        net = SymmetricPolicy(Network(hidden=8, seed=11))
        x = np.random.default_rng(12).normal(size=(5, N_FEATURES)).astype(np.float32)
        expected = net.predict(x)
        for ours in (False, True):
            for foes in (False, True):
                changed = net.predict(x[:, feature_order(ours, foes)])[:, action_order(ours)]
                np.testing.assert_allclose(changed, expected, atol=1e-7, rtol=1e-6)
        np.testing.assert_allclose(net.predict(x[0]), expected[0], atol=1e-7)

    def test_augmentation_preserves_legality_and_saved_rng_replays_it(self):
        rng = np.random.default_rng(13)
        x = rng.normal(size=(32, N_FEATURES)).astype(np.float32)
        masks = np.zeros((32, 9), bool)
        masks[:, [0, 3, 7]] = True
        actions = np.resize([0, 3, 7], 32)
        a = augment(x, masks, actions, np.random.default_rng(14))
        b = augment(x, masks, actions, np.random.default_rng(14))
        for left, right in zip(a, b):
            np.testing.assert_array_equal(left, right)
        self.assertTrue(np.all(a[1][np.arange(32), a[2]]))
        for ours in (False, True):
            for foes in (False, True):
                once = permute(x, masks, actions, ours, foes)
                twice = permute(*once, ours, foes)
                for actual, expected in zip(twice, (x, masks, actions)):
                    np.testing.assert_array_equal(actual, expected)


if __name__ == '__main__':
    unittest.main()
