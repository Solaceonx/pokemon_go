"""The new decision's window, legal actions, saved-model compatibility and play-outs."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pogo.agents import Masher, Planner
from pogo.battle import CHARGED, SWITCH, Battle, damage
from pogo.gamedata import GameData
from pogo.learner import Learner, N_FEATURES, Policy, QNet
from scripts.decide import options_for, play_out, sample_examples


GD = GameData()


class MidSwap(unittest.TestCase):
    def position(self, **settings):
        pilot = Learner(log=[], sac=False, seed=7, **settings)
        team = [GD.default(s) for s in ("melmetal", "jellicent", "altaria")]
        battle = Battle(team, list(reversed(team)), pilot, Masher(), seed=9, shields=(0, 0))
        view = battle.views[0]
        pilot._judged = (view.me.active, view.foe.build.uid)
        view.foe.energy = min(m.energy for m in view.foe.build.charged) - 2 * view.foe.build.fast.energy_gain
        return pilot, battle, view

    def test_window_includes_two_fast_moves_and_already_ready(self):
        for extra in (-1, 0, 1, 50):
            with self.subTest(extra=extra):
                pilot, _, view = self.position()
                view.foe.energy += extra
                pilot.act(view)
                rows = [r for r in pilot.log if r[0] == "mid_swap"]
                self.assertEqual(len(rows), int(extra >= 0))
                if rows:
                    self.assertEqual(rows[0][2:], ((True, True, True), 0))
                    self.assertEqual(len(rows[0][1]), N_FEATURES)

    def test_unavailable_switches_and_new_matchups_skip_the_head(self):
        for case in ("locked", "busy", "no_bench", "new_matchup", "disabled", "no_switches"):
            with self.subTest(case=case):
                pilot, _, view = self.position()
                if case == "locked":
                    view.me.switch_wait = 1
                elif case == "busy":
                    view.me.busy = 1
                elif case == "no_bench":
                    for slot in view.me.bench():
                        view.me.team[slot].hp = 0
                elif case == "new_matchup":
                    pilot._judged = None
                elif case == "disabled":
                    pilot.mid_swap = False
                else:
                    pilot.switches = False
                pilot.act(view)
                self.assertNotIn("mid_swap", [r[0] for r in pilot.log])

    def test_mask_excludes_fainted_bench_and_respects_margin(self):
        pilot, _, view = self.position(q=QNet(), margin=0.05)
        view.me.team[1].hp = 0
        with patch.object(pilot.q, "values", return_value=np.array([0.5, 0.99, 0.54])):
            self.assertIsNone(pilot._pick_switch(view))
        with patch.object(pilot.q, "values", return_value=np.array([0.5, 0.99, 0.56])):
            self.assertEqual(pilot._pick_switch(view), SWITCH[2])
        self.assertEqual(pilot.log[-1][2], (True, False, True))
        self.assertEqual(options_for("mid_swap", pilot.log[-1][2]), [0, 2])

    def test_planner_rescue_is_the_advice(self):
        pilot, _, view = self.position()
        pilot.sac = True
        with patch.object(pilot, "_pick_sacrifice", return_value=None), \
                patch.object(pilot, "_pick_rescue", return_value=2):
            self.assertEqual(pilot._pick_switch(view), SWITCH[2])
        self.assertEqual(pilot.log[-1][3], 2)

    def test_forced_swap_catches_the_move_and_clears_hold(self):
        for active in range(3):
            for option in (1, 2):
                with self.subTest(active=active, option=option):
                    pilot, battle, view = self.position()
                    view.me.active = active
                    pilot._judged = (active, view.foe.build.uid)
                    view.foe.energy = 100
                    pilot._hold = 4
                    pilot.force("mid_swap", option)
                    target = [j for j in range(3) if j != active][option - 1]
                    incoming = view.me.team[target]
                    # Masher throws the most damaging affordable move into the original active.
                    action = battle.agents[1].act(battle.views[1])
                    self.assertIn(action, CHARGED)
                    hit = damage(view.foe, view.foe.build.charged[action - CHARGED[0]], incoming)
                    before = incoming.hp
                    battle.step()
                    self.assertEqual(view.me.active, target)
                    self.assertEqual(incoming.hp, before - hit)
                    self.assertEqual(pilot._hold, 0)
                    self.assertNotIn("mid_swap", pilot.forced)

    def test_play_out_forces_each_option_without_mutating_snapshot(self):
        pilot, battle, view = self.position()
        snapshot = battle.clone(None, None), pilot.clone(), battle.agents[1].clone()
        for option in options_for("mid_swap", (True, True, True)):
            result = play_out(snapshot, "mid_swap", option)
            self.assertIn(result, (0.0, 0.5, 1.0))
            self.assertEqual(result, play_out(snapshot, "mid_swap", option))
        self.assertEqual(snapshot[0].turn, 0)
        self.assertEqual(view.me.active, 0)
        self.assertEqual(pilot.forced, {})

    def test_old_model_roundtrip_and_battle_logs_unchanged(self):
        q = QNet()
        q.params.pop("mid_swap")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "q.npz"
            q.save(path)
            loaded = QNet.load(path)
        self.assertNotIn("mid_swap", loaded.params)
        pool = GD.meta(12)
        for seed in range(6):
            teams = pool[seed:seed + 3], pool[-3:]
            a = Battle(*teams, Learner(q=loaded, seed=seed), Planner(seed=seed), seed=seed, record=True)
            b = Battle(*teams, Learner(q=loaded, mid_swap=False, seed=seed), Planner(seed=seed), seed=seed, record=True)
            self.assertEqual(a.run(), b.run())
            self.assertEqual(a.log, b.log)

    def test_old_policy_can_log_the_new_decision(self):
        pilot, _, view = self.position(policy=Policy())
        self.assertIsNone(pilot._pick_switch(view))


class ExampleBudget(unittest.TestCase):
    def test_exact_repeatable_sample_keeps_features_and_targets_together(self):
        data = {"shield": (np.arange(20).reshape(10, 2), np.arange(10)[:, None]),
                "mid_swap": (np.arange(20, 40).reshape(10, 2), np.arange(10, 20)[:, None])}
        a, b = sample_examples(data, 13, 6), sample_examples(data, 13, 6)
        self.assertEqual(sum(len(x) for x, _ in a.values()), 13)
        for head, (x, y) in a.items():
            np.testing.assert_array_equal(x[:, 0], y[:, 0] * 2)
            np.testing.assert_array_equal(x, b[head][0])
        self.assertEqual(sum(len(x) for x, _ in data.values()), 20)
        with self.assertRaisesRegex(ValueError, "fewer than"):
            sample_examples(data, 21, 6)


if __name__ == "__main__":
    unittest.main()
