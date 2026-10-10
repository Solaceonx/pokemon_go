"""Independent one-turn normal-form enumeration and recursive engine checks."""
import itertools
import unittest
from dataclasses import replace

import numpy as np

from pogo.agents import Masher
from pogo.battle import Battle, Mon, MAX_TURNS
from pogo.endgame import Solver, SolveLimit, matrix_game, EndgamePlayer, state_key
from pogo.learner import Learner
from pogo.gamedata import GameData

GD = GameData()


def position(shields=0, size=(1, 1), turns=1):
    a = GD.build('azumarill', ['BUBBLE', 'ICE_BEAM', 'PLAY_ROUGH'])
    b = GD.build('medicham', ['COUNTER', 'ICE_PUNCH', 'PSYCHIC'])
    # Remove chance buffs for the independent deterministic reference.
    b = replace(b, charged=tuple(replace(m, buff_chance=0) for m in b.charged))
    battle = Battle([Mon(a, hp=12, energy=60) for _ in range(size[0])],
                    [Mon(b, hp=15, energy=60) for _ in range(size[1])],
                    Masher(), Masher(), seed=0, shields=(shields, shields))
    battle.turn = MAX_TURNS - turns
    for s in battle.sides:
        s.shown = list(range(len(s.team)))
    return battle


class Fixed(Masher):
    def __init__(self, action, shield):
        self.action, self.use_shield = action, shield

    def act(self, view):
        return self.action

    def shield(self, view, energy):
        return self.use_shield


def brute_one_turn(b):
    """Explicit pure (action, shield) pairs; one-mon, deterministic, final turn."""
    plans = [list(itertools.product(v.legal(), (False, True) if s.shields else (False,)))
             for v, s in zip(b.views, b.sides)]
    matrix = []
    for p in plans[0]:
        row = []
        for q in plans[1]:
            twin = b.clone(Fixed(*p), Fixed(*q))
            twin.step()
            assert twin.winner is not None
            row.append(.5 if twin.winner == -1 else float(twin.winner == 0))
        matrix.append(row)
    return matrix_game(matrix)[0]


def brute_no_shields(b):
    """Independent un-memoized joint-action enumeration, deterministic moves only."""
    if b.winner is not None:
        return .5 if b.winner == -1 else float(b.winner == 0)
    matrix = []
    for a in b.views[0].legal():
        row = []
        for c in b.views[1].legal():
            twin = b.clone(Fixed(a, False), Fixed(c, False))
            twin.step()
            row.append(brute_no_shields(twin))
        matrix.append(row)
    return matrix_game(matrix)[0]


class EndgameTests(unittest.TestCase):
    def test_matrix(self):
        v, p, q = matrix_game([[1, 0], [0, 1]])
        self.assertAlmostEqual(v, .5)
        np.testing.assert_allclose(p, [.5, .5])
        np.testing.assert_allclose(q, [.5, .5])
        v, p, q = matrix_game([[0, -1, 1], [1, 0, -1], [-1, 1, 0]])
        self.assertAlmostEqual(v, 0)
        np.testing.assert_allclose(p, [1/3]*3)
        # Rectangular, degenerate equilibrium.
        v, p, q = matrix_game([[1, 0, .5], [0, 1, .5]])
        self.assertAlmostEqual(v, .5)

    def test_brute(self):
        for shields in range(3):
            for energy in (0, 40, 60, 100):
                b = position(shields)
                b.sides[0].mon.energy = energy
                self.assertAlmostEqual(Solver(seconds=10).solve(b).value, brute_one_turn(b))

    def test_tree_without_transpositions(self):
        for size in ((1, 1), (2, 1), (2, 2)):
            b = position(0, size, 2)
            a = Solver(seconds=20).solve(b).value
            self.assertAlmostEqual(a, Solver(seconds=20, memo=False).solve(b).value)
            self.assertAlmostEqual(a, brute_no_shields(b))

    def test_chance_cmp(self):
        b = position(0)
        b.sides[1] = b.sides[0].copy()
        from pogo.battle import View
        b.views = [View(b, i) for i in (0, 1)]
        self.assertAlmostEqual(Solver(seconds=10).solve(b).value, .5)

    def test_probabilistic_buff(self):
        b = position(0, turns=480)
        build = b.sides[0].mon.build
        move = replace(build.charged[0], power=0, energy=60,
                       buff_chance=.5, self_buffs=(4, 0))
        b.sides[0].mon.build = replace(build, charged=(move,), _cache={},
                                     fast=replace(build.fast, turns=1, energy_gain=0))
        other = b.sides[1].mon.build
        b.sides[1].mon.build = replace(other, _cache={},
                                     fast=replace(other.fast, turns=1, energy_gain=0))
        b.sides[0].mon.hp = 12
        b.sides[1].mon.energy = 0
        b.sides[1].mon.hp = 16

        def brute(state):
            if state.winner is not None:
                return .5 if state.winner == -1 else float(state.winner == 0)
            matrix = []
            for a in state.views[0].legal():
                row = []
                for c in state.views[1].legal():
                    outcomes = []
                    # Only side 0 has a random move and CMP cannot tie here.
                    for roll in (.25, .75):
                        twin = state.clone(Fixed(a, False), Fixed(c, False))
                        original_rng = twin.rng
                        class Dice:
                            def random(self):
                                return roll
                        twin.rng = Dice()
                        twin.step()
                        twin.rng = original_rng
                        outcomes.append(brute(twin))
                    row.append(sum(outcomes)/2)
                matrix.append(row)
            return matrix_game(matrix)[0]

        value = Solver(seconds=10).solve(b).value
        self.assertAlmostEqual(value, brute(b))
        self.assertAlmostEqual(value, .25)

    def test_limits_and_visibility(self):
        b = position(0, (2, 2))
        b.sides[1].shown = [0]
        self.assertFalse(Solver.qualifies(b))
        with self.assertRaises(ValueError):
            Solver().solve(b)
        b.sides[1].shown = [0, 1]
        with self.assertRaises(SolveLimit):
            Solver(max_nodes=0).solve(b)

    def test_no_mutation_and_fallback(self):
        b = position(1)
        before, dice = state_key(b), b.rng.getstate()
        Solver(seconds=10).solve(b)
        self.assertEqual(before, state_key(b))
        self.assertEqual(dice, b.rng.getstate())
        player = EndgamePlayer(max_nodes=0, seed=19)
        self.assertEqual(player.act(b.views[0]), Learner(seed=19).act(b.views[0]))
        self.assertEqual(player.limited, 1)
        # Busy input is a real search state, with no act decision for that side.
        b.sides[0].busy = 1
        result = Solver(seconds=10).solve(b)
        self.assertTrue(all((0, 'act') not in p for p in result.plans[0]))

    def test_player(self):
        b = position(1)
        player = EndgamePlayer(seconds=10, seed=1)
        b.agents[0] = player
        b.step()
        self.assertEqual(player.solved, 1)
