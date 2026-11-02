"""Energy corrections, form identity, and the hand-off from tracking to planning."""
import copy
import random
import unittest
from unittest.mock import Mock

from pogo.agents import Planner
from pogo.battle import Battle
from pogo.belief import sample_energy
from pogo.engine import imagine
from pogo.gamedata import GameData
from pogo.tracker import Foe, Observation, Tracker, state
from scripts.advise import rebuild
from scripts.check_tracker import CAMERAS, ViaTracker, cases, evaluate, interval

GD = GameData()


class EnergyCorrections(unittest.TestCase):
    def test_late_switch_undoes_credit_before_the_energy_cap(self):
        for switch_at, expected in ((8, 72), (11, 99), (12, 100), (13, 100)):
            with self.subTest(switch_at=switch_at):
                tracker = Tracker(GD, [GD.default("melmetal")])
                for k in range(31):
                    tracker.update(Observation(k * .5, foe_species="stunfisk"))
                tracker.update(Observation(15.5, foe_species="azumarill", foe_out_for=15.5 - switch_at))
                old = tracker.foes["stunfisk"]
                self.assertEqual((old.lo, old.hi, old.mon.energy), (expected,) * 3)
                self.assertEqual(old.clock, switch_at * 2)
                self.assertEqual(tracker.foe.clock, round((15.5 - switch_at) * 2))

    def test_spending_discards_overflow_and_undo_preserves_cost_uncertainty(self):
        foe = Foe(GD.default("stunfisk"))
        foe.gain(126)
        foe.spend([40, 55])
        self.assertEqual((foe.lo, foe.hi), (45, 60))
        foe.gain(45)
        self.assertEqual((foe.lo, foe.hi), (90, 100))
        foe.undo_gain(18)
        self.assertEqual((foe.lo, foe.hi), (72, 87))
        foe.undo_gain(27)
        self.assertEqual((foe.lo, foe.hi), (45, 60))


class FormIdentity(unittest.TestCase):
    def test_disguise_damage_does_not_overwrite_the_observed_health(self):
        for ours in (True, False):
            with self.subTest(ours=ours):
                t = Tracker(GD, [GD.default("mimikyu" if ours else "marowak")])
                t.update(Observation(0, foe_species="marowak" if ours else "mimikyu"))
                target = t.me.mon if ours else t.foe.mon
                target.hp = 30
                if ours:
                    t.update(Observation(10, my_species="mimikyu_busted", my_hp=29 / target.build.hp,
                                         foe_charged=True, foe_move="BONE_CLUB"))
                else:
                    t.update(Observation(10, foe_species="mimikyu_busted", foe_hp=29 / target.build.hp,
                                         my_charged=0))
                self.assertEqual(target.hp, 29)
                self.assertEqual(target.def_stage, -1)

    def test_forms_retain_identity_energy_and_switch_clocks(self):
        for home, form in (("cramorant", "cramorant_gorging"), ("mimikyu", "mimikyu_busted"),
                           ("morpeko_full_belly", "morpeko_hangry")):
            with self.subTest(form=form):
                t = Tracker(GD, [GD.default(home), GD.default("melmetal")])
                t.update(Observation(0, foe_species=home))
                foe = t.foe
                foe.gain(72)
                t.me.mon.energy = 63
                t.foe_switch_at, t.my_switch_at = 40, 30
                t.update(Observation(0, my_species=form, foe_species=form))
                self.assertIs(t.foe, foe)
                self.assertEqual(len(t.order), 1)
                self.assertEqual(len(t.me.team), 2)
                self.assertEqual((t.me.active, state(t)["opponent"]["active"]), (0, 0))
                self.assertEqual((t.foe.mon.energy, t.me.mon.energy), (72, 63))
                self.assertEqual((t.foe_switch_at, t.my_switch_at), (40, 30))
                self.assertEqual(t.foe.mon.build.species_id, form)
                self.assertEqual(t.me.mon.build.species_id, form)
                if home == "mimikyu":
                    self.assertEqual(t.foe.mon.def_stage, -1)
                    t.update(Observation(0, my_species=form, foe_species=form))
                    self.assertEqual(t.foe.mon.def_stage, -1)

    def test_first_sighting_can_be_a_form_absent_from_the_rankings(self):
        for species in ("cramorant_gorging", "mimikyu_busted"):
            t = Tracker(GD, [GD.default("melmetal")])
            t.update(Observation(0, foe_species=species))
            self.assertEqual(t.foe.mon.build.species_id, species)
            self.assertEqual(state(t)["opponent"]["active"], 0)

    def test_form_change_and_return_do_not_create_extra_opponents(self):
        t = Tracker(GD, [GD.default("melmetal")])
        t.update(Observation(0, foe_species="morpeko_full_belly"))
        original = t.foe
        t.foe.gain(50)
        t.update(Observation(0, foe_species="morpeko_hangry"))
        t.update(Observation(0, foe_species="azumarill"))
        self.assertEqual(original.mon.build.species_id, "morpeko_full_belly")
        t.update(Observation(0, foe_species="morpeko_full_belly"))
        self.assertIs(t.foe, original)
        self.assertEqual((len(t.order), t.foe.mon.energy), (2, 50))


class EnergySampling(unittest.TestCase):
    def tracker(self):
        t = Tracker(GD, [GD.default(s) for s in ("melmetal", "altaria", "jellicent")])
        t.update(Observation(0, foe_species="azumarill"))
        t.foe.gain(55)
        t.update(Observation(0, foe_species="stunfisk"))
        t.foe.gain(45)
        return t

    def test_relative_weights_json_keys_and_seed_are_respected(self):
        a, b = random.Random(5), random.Random(5)
        draws = [sample_energy({"0": 1, "90": 3, "100": 0}, a) for _ in range(4000)]
        self.assertEqual(draws, [sample_energy({0: .25, 90: .75, 100: 0}, b) for _ in range(4000)])
        self.assertEqual(set(draws), {0, 90})
        self.assertAlmostEqual(draws.count(90) / len(draws), .75, delta=.03)
        for odds in ({}, {1: 0}, {1: -1}, {101: 1}, {2.5: 1}, {1: float("nan")}):
            with self.assertRaises(ValueError):
                sample_energy(odds, a)

    def test_imagination_samples_bench_and_active_without_mutating_tracker(self):
        t = self.tracker()
        before = state(t)
        seen = [set(), set()]
        for seed in range(50):
            b = imagine(t.view(), random.Random(seed), GD.meta(50), None, None)
            for i in range(2):
                seen[i].add(b.sides[1].team[i].energy)
        for values, odds in zip(seen, t.view().foe_shown_energy_odds):
            self.assertEqual(values, set(odds))
        self.assertEqual(state(t), before)

    def test_saved_advice_uses_probabilities_outside_the_nominal_range(self):
        original = state(self.tracker())
        for p in original["opponent"]["pokemon"]:
            p["energy_range"], p["energy_odds"] = [40, 40], {"81": .99}
        before = copy.deepcopy(original)
        b = rebuild(GD, original, GD.meta(50), random.Random(4), None, None)
        self.assertEqual([m.energy for m in b.sides[1].team[:2]], [81, 81])
        self.assertEqual(original, before)
        for p in original["opponent"]["pokemon"]:
            del p["energy_odds"]
        b = rebuild(GD, original, GD.meta(50), random.Random(4), None, None)
        self.assertEqual([m.energy for m in b.sides[1].team[:2]], [40, 40])

    def test_exact_view_keeps_energy_and_rng_sequence(self):
        teams = [GD.default(s) for s in ("azumarill", "melmetal", "altaria")]
        b = Battle(teams, teams, None, None, seed=4)
        b.sides[1].shown = [0, 1, 2]
        for i, mon in enumerate(b.sides[1].team):
            mon.energy = 20 + i
        a, expected = random.Random(7), random.Random(7)
        imagined = imagine(b.views[0], a, GD.meta(50), None, None)
        expected.getrandbits(32)  # the battle seed is the only draw when no Pokémon are unseen
        self.assertEqual([m.energy for m in imagined.sides[1].team], [20, 21, 22])
        self.assertEqual(a.getstate(), expected.getstate())


class PairedMeasurement(unittest.TestCase):
    def test_camera_order_does_not_change_battles_or_results(self):
        pool = GD.meta(12)
        schedule = cases(lambda rng: rng.sample(pool, 3), 2, 7)
        cameras = {k: CAMERAS[k] for k in ("perfect", "rough")}
        a = evaluate(GD, schedule, lambda seed: Planner(seed=seed), cameras)
        b = evaluate(GD, schedule, lambda seed: Planner(seed=seed), dict(reversed(list(cameras.items()))))
        self.assertEqual(a, b)
        self.assertEqual(a["exact state"]["change_from_exact"], {"mean": 0.0, "margin95": 0.0})
        self.assertEqual(interval([.5, .5])["mean"], .5)

    def test_unread_move_does_not_leak_from_simulator_callback(self):
        inner = Mock()
        wrapped = ViaTracker(inner)
        wrapped.tracker = Tracker(GD, [GD.default("melmetal")])
        wrapped.tracker.update(Observation(0, foe_species="azumarill"))
        wrapped.names = False
        wrapped.saw_throw(None, GD.moves["ICE_BEAM"], 100, True)
        inner.saw_throw.assert_not_called()


if __name__ == "__main__":
    unittest.main()
