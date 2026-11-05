"""Task 43's gates, unchanged games when off, and the rulebook default inside the search."""
import hashlib
import json
import random
import unittest
from pathlib import Path
from unittest.mock import patch

from pogo.agents import Masher, Planner
from pogo.battle import FAST, SWITCH, Battle
from pogo.engine import Engine, imagine
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData
from pogo.learner import Learner, QNet

ROOT = Path(__file__).resolve().parent.parent
GD = GameData()
POOL = GD.meta(50)
Q = QNet.load(ROOT / "runs/general-decide/q.npz")
MODEL = Evaluator.load(ROOT / "runs/eval/eval.npz").model


class MidSwapSearch(unittest.TestCase):
    def position(self, gate="ready", **settings):
        pilot = Engine(Evaluator(MODEL), POOL, q=Q, rollout="bot", samples=1, horizon=1,
                       heads=("mid_swap",), mid_swap_search=gate, sac=False, moves=False, seed=7, **settings)
        team = [GD.default(s) for s in ("melmetal", "jellicent", "altaria")]
        battle = Battle(team, list(reversed(team)), pilot, Masher(), seed=9, shields=(0, 0))
        view = battle.views[0]
        pilot._judged = (view.me.active, view.foe.build.uid)
        view.foe.energy = min(m.energy for m in view.foe.build.charged) - 2 * view.foe.build.fast.energy_gain
        return pilot, battle, view

    def hit(self, pilot, battle, view):
        view.foe.energy = 100
        battle._throw(1, 0)
        view.foe.energy = 0
        battle.turn += 1

    def test_ready_reuses_task20_boundary_including_already_ready(self):
        self.assertNotIn("mid_swap", Q.params)
        for extra in (-1, 0, 1, 50):
            for gate in ("ready", "both"):
                with self.subTest(extra=extra, gate=gate):
                    pilot, _, view = self.position(gate)
                    view.foe.energy += extra
                    with patch.object(pilot, "_look", return_value=0.5) as look:
                        pilot.act(view)
                    self.assertEqual(pilot.mid_swap_searches, int(extra >= 0))
                    self.assertEqual(look.call_count, 3 if extra >= 0 else 0)
                    self.assertTrue(all(c.args[1] == "mid_swap" for c in look.call_args_list))

    def test_all_gates_require_a_legal_switch_and_judged_matchup(self):
        for gate in ("ready", "hit", "both"):
            for case in ("locked", "busy", "fainted", "no_bench", "new", "disabled", "no_switches", "no_head"):
                with self.subTest(gate=gate, case=case):
                    pilot, _, view = self.position(gate)
                    pilot._swap_hit = (-1, 0)
                    if case == "locked":
                        view.me.switch_wait = 1
                    elif case == "busy":
                        view.me.busy = 1
                    elif case == "fainted":
                        view.me.mon.hp = 0
                    elif case == "no_bench":
                        for slot in view.me.bench():
                            view.me.team[slot].hp = 0
                    elif case == "new":
                        pilot._judged = None
                    elif case == "disabled":
                        pilot.mid_swap = False
                    elif case == "no_switches":
                        pilot.switches = False
                    else:
                        pilot.heads = ()
                    with patch.object(pilot, "_look", return_value=0.5):
                        pilot.act(view)
                    self.assertEqual(pilot.mid_swap_searches, 0)
                    self.assertIsNone(pilot._swap_hit)

    def test_hit_once_per_landed_move_including_shields(self):
        for shields in (0, 2):
            pilot, battle, view = self.position("hit")
            view.me.shields = shields
            with patch.object(pilot, "_look", return_value=0.5), patch.object(pilot, "shield", return_value=True):
                pilot.act(view)  # ready alone does not open hit
                self.assertEqual(pilot.mid_swap_searches, 0)
                for n in range(1, 3):
                    before = view.me.mon.hp
                    self.hit(pilot, battle, view)
                    self.assertLess(view.me.mon.hp, before)
                    pilot.act(view)
                    self.assertEqual(pilot.mid_swap_searches, n)
                    pilot.act(view)
                    self.assertEqual(pilot.mid_swap_searches, n)

    def test_hit_is_after_damage_in_a_real_step(self):
        pilot, battle, view = self.position("hit")
        view.foe.energy = 100
        before = view.me.mon.hp
        with patch.object(pilot, "_look", return_value=0.5) as look:
            battle.step()
            self.assertEqual(pilot.mid_swap_searches, 0)
            self.assertLess(view.me.mon.hp, before)
            view.foe.energy = 0
            battle.step()
            self.assertEqual(pilot.mid_swap_searches, 1)
            self.assertTrue(look.called)

    def test_hit_is_not_queued_until_switch_unlocks_or_after_replacement(self):
        pilot, battle, view = self.position("hit")
        with patch.object(pilot, "_look", return_value=0.5):
            self.hit(pilot, battle, view)
            view.me.switch_wait = 1
            pilot.act(view)
            view.me.switch_wait = 0
            pilot.act(view)
            self.assertEqual(pilot.mid_swap_searches, 0)
            self.hit(pilot, battle, view)
            view.me.mon.hp = 0
            battle._enter(0, pilot.replace(view))
            pilot._judged = (view.me.active, view.foe.build.uid)
            pilot.act(view)
            self.assertEqual(pilot.mid_swap_searches, 0)

    def test_both_is_either_gate_and_does_not_search_twice(self):
        for ready, hit in ((False, False), (True, False), (False, True), (True, True)):
            pilot, _, view = self.position("both")
            view.foe.energy = 100 if ready else 0
            pilot._swap_hit = (-1, 0) if hit else None
            with patch.object(pilot, "_look", return_value=0.5):
                pilot.act(view)
            self.assertEqual(pilot.mid_swap_searches, int(ready or hit))

    def test_rulebook_rescue_is_the_default_and_switch_clears_hold(self):
        pilot, _, view = self.position()
        pilot.sac, pilot._hold = True, 4
        with patch.object(pilot, "_pick_sacrifice", return_value=None), \
                patch.object(pilot, "_pick_rescue", return_value=2), \
                patch.object(pilot, "_look", return_value=0.5):
            self.assertEqual(pilot.act(view), SWITCH[2])  # equal scores keep the rulebook's rescue
        self.assertEqual(pilot._hold, 0)
        self.assertEqual(pilot.mid_swap_searches, 1)

    def test_switch_edge_applies_to_mid_swap(self):
        for edge, expected in ((0, SWITCH[1]), (0.05, FAST)):
            pilot, _, view = self.position(switch_edge=edge)
            with patch.object(pilot, "_look", side_effect=lambda v, h, k, s: (0.5, 0.54, 0.4)[k]):
                self.assertEqual(pilot.act(view), expected)

    def test_stay_after_replace_and_forced_choices_do_not_search(self):
        for case in ("replace", "forced", "deadline"):
            pilot, _, view = self.position(stay_after_replace=case == "replace")
            if case == "replace":
                pilot._replaced_at = view.turn
            elif case == "forced":
                pilot.force("mid_swap", 0)
            else:
                pilot._deadline = -1
            with patch.object(pilot, "_look") as look:
                self.assertEqual(pilot.act(view), FAST)
            look.assert_not_called()
            self.assertEqual(pilot.mid_swap_searches, int(case == "deadline"))

    def test_imagined_bots_keep_defaults(self):
        for gate in ("ready", "hit", "both"):
            pilot, _, view = self.position(gate)
            seen = []

            def capture(*args, **kwargs):
                battle = imagine(*args, **kwargs)
                seen.extend([battle.agents[0].inner, battle.agents[1]])
                return battle

            with patch("pogo.engine.imagine", side_effect=capture):
                pilot._look(view, "mid_swap", 0, 23)
            self.assertEqual(len(seen), 2)
            for player in seen:
                self.assertIs(type(player), Learner)
                self.assertFalse(hasattr(player, "mid_swap_search"))
                self.assertTrue(player.mid_swap)
                self.assertFalse(player._mid_swap_gate(view))

    def test_clone_consumes_its_own_hit(self):
        pilot, _, view = self.position("hit")
        pilot._swap_hit = (-1, 0)
        twin = pilot.clone()
        with patch.object(twin, "_look", return_value=0.5):
            twin.act(view)
        self.assertIsNone(twin._swap_hit)
        self.assertEqual(pilot._swap_hit, (-1, 0))

    def test_invalid_gate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "mid_swap_search"):
            self.position("typo")

    def test_off_matches_pre_edit_moves_winners_and_turns(self):
        # Captured on cbd8825 before editing, with the command's output in runs/task43-before.json.
        expected = [
            (0, 370, "d67866a6689299ad845f43e4e997eff2f042a89f95a8644aaf2608e4b13ac723"),
            (0, 440, "4ea954e82b2f8638e2ee8dbfdc7f742bff0807857fbc83e9255e5451a1f0ba35"),
            (1, 308, "0dbae70a4149206c551f935850af0591909fc96545eb517c570481ac257e5e8f"),
            (1, 256, "c767687eeb6f2e2b3a3bcb0068e4aebc82f405edb0be6c1926c975535f1193f6"),
        ]
        for settings in ({}, {"mid_swap_search": None}, {"mid_swap_search": False}):
            for seed, (winner, turns, digest) in enumerate(expected):
                rng = random.Random(seed)
                teams = rng.sample(POOL, 3), rng.sample(POOL, 3)
                me = Engine(Evaluator(MODEL), POOL, rollout="bot", samples=2, horizon=4, edge=0.03,
                            q=Q, margin=0.02, seed=rng.getrandbits(32), **settings)
                them = Planner(seed=rng.getrandbits(32))
                battle = Battle(*teams, me, them, seed=rng.getrandbits(32), record=True)
                battle.run()
                self.assertEqual((battle.winner, battle.turn), (winner, turns))
                self.assertEqual(hashlib.sha256(json.dumps([battle.log, battle.winner, battle.turn]).encode()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
