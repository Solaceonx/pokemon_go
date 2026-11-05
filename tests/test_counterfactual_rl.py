"""Training forks must replay real play exactly and never share evaluator caches."""
import random
import unittest

import numpy as np

from pogo.counterfactual_rl import CounterfactualModel, action_returns, branch, capture
from pogo.rl_experiment import FrozenRuntime, freeze
from pogo.standalone_rl import N_FEATURES, StandaloneAgent


class CompleteActionReturns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = FrozenRuntime(freeze("59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9"))

    def position(self, seat):
        rt = self.runtime
        rng = random.Random(91)
        teams = [rt.draw(rng, "train") for _ in range(2)]
        pilot = StandaloneAgent(CounterfactualModel(hidden=16), seed=11)
        foe = rt.engine(12, samples=1)
        agents = (pilot, foe) if seat == 0 else (foe, pilot)
        battle = rt.Battle(*teams, *agents, seed=13)
        # Exercise nonempty caches and histories, not just an opening position.
        for _ in range(6):
            battle.step()
        while battle.sides[seat].busy:
            battle.step()
        self.assertIsNone(battle.winner)
        return battle, capture(battle, seat)

    def test_forcing_the_real_choice_reproduces_complete_battles_on_both_seats(self):
        for seat in (0, 1):
            battle, position = self.position(seat)
            action = battle.agents[seat].clone().act(battle.views[seat])
            replay = branch(position, action)
            self.assertEqual(battle.run(), replay.run())
            self.assertEqual(battle.turn, replay.turn)
            for a, b in zip(battle.sides, replay.sides):
                self.assertEqual((a.active, a.shields, a.switch_wait), (b.active, b.shields, b.switch_wait))
                self.assertEqual([(m.hp, m.energy, m.build.species_id) for m in a.team],
                                 [(m.hp, m.energy, m.build.species_id) for m in b.team])

    def test_alternatives_have_private_controller_and_evaluator_caches(self):
        battle, position = self.position(0)
        option = int(np.flatnonzero(position.mask)[0])
        a, b = branch(position, option), branch(position, option)
        original, left, right = battle.agents[1], a.agents[1], b.agents[1]
        self.assertIsNot(left._outlooks, right._outlooks)
        self.assertIsNot(left._outlooks, original._outlooks)
        self.assertIsNot(left.evaluator._agent._outlooks, right.evaluator._agent._outlooks)
        before = dict(right.evaluator._agent._outlooks)
        left.evaluator._agent._outlooks["sentinel"] = 123
        self.assertEqual(right.evaluator._agent._outlooks, before)
        self.assertNotIn("sentinel", original.evaluator._agent._outlooks)
        left.departures["sentinel"] = 1
        self.assertNotIn("sentinel", right.departures)
        self.assertNotIn("sentinel", original.departures)

    def test_terminal_labels_repeat_and_preserve_the_training_position(self):
        _, position = self.position(0)
        before = [(m.hp, m.energy) for s in position.battle.sides for m in s.team]
        a = action_returns(position, playouts=1, seed=42)
        b = action_returns(position, playouts=1, seed=42)
        np.testing.assert_array_equal(a, b)
        self.assertTrue(np.isnan(a[~position.mask]).all())
        self.assertTrue(np.isin(a[position.mask], [0., .5, 1.]).all())
        self.assertEqual(before, [(m.hp, m.energy) for s in position.battle.sides for m in s.team])

    def test_later_training_cannot_change_the_captured_continuation_policy(self):
        battle, position = self.position(0)
        before = position.battle.agents[0].model.params["act.out_b"].copy()
        battle.agents[0].model.params["act.out_b"] += 10
        np.testing.assert_array_equal(position.battle.agents[0].model.params["act.out_b"], before)


class FullOptionPolicyGradient(unittest.TestCase):
    def test_better_return_increases_its_probability_without_moving_other_heads(self):
        model = CounterfactualModel(hidden=16)
        x = np.ones((1, N_FEATURES), np.float32)
        mask = np.array([[True, True, False, False, False, False]])
        targets = np.array([[0., 1., np.nan, np.nan, np.nan, np.nan]], np.float32)
        before = model.forward(x, "act", mask)[0]
        other = {k: v.copy() for k, v in model.params.items() if not k.startswith("act.")}
        model.improve_actions(x, mask, targets, entropy=0.)
        self.assertGreater(model.forward(x, "act", mask)[0][0, 1], before[0, 1])
        for k, expected in other.items():
            np.testing.assert_array_equal(model.params[k], expected)

    def test_equal_returns_supply_no_action_preference(self):
        model = CounterfactualModel(hidden=16)
        x = np.ones((1, N_FEATURES), np.float32)
        mask = np.ones((1, 6), dtype=bool)
        old = {k: v.copy() for k, v in model.params.items()}
        model.improve_actions(x, mask, np.zeros((1, 6), np.float32), entropy=0.)
        for k, expected in old.items():
            np.testing.assert_array_equal(model.params[k], expected)


if __name__ == "__main__":
    unittest.main()
