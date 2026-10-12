"""State persistence through charging, resolution, readback and missing time."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_public_state import frame, SLIM
from public_state import PublicState, evidence, unknown
from vod_track import switch_time_left


def hidden(t, phase):
    f = frame(t)
    f["phase"] = evidence(phase, t) if phase else unknown("Animation has no readable cue")
    for side in ("mine", "opponent"):
        for key in ("species", "cp", "pokemon_left", "shields_left"):
            f[side][key] = unknown("Not visible in animation")
        f[side]["health_estimate"] = {"status": "unknown"}
    return f


def discs(f, left=.6, right=.2, ready=True):
    f["buttons"] = [{"id": f"charge_{i}", "move": name, "identity_status": "observed"}
                    for i, name in enumerate(("Surf", "Thunderbolt"))]
    return {"b": {"l": [left, 1, int(ready)], "r": [right, 1, int(ready)]}}


class ContinuityTests(unittest.TestCase):
    def settled(self):
        reader = PublicState({"Surf": 45, "Thunderbolt": 60, "Body Slam": 35})
        for t in (0, .067, .134):
            f = frame(t)
            state = reader.update(f, discs(f))
        return reader, state

    def mon(self, state, side="mine", name=None):
        team = state["sides"][side]
        return team["pokemon"][name or team["active"]]

    def test_my_minigame_retains_unaffected_state(self):
        reader, before = self.settled()
        for t in (.2, .8, 1.4, 2):
            state = reader.update(hidden(t, "my_charged_minigame"), SLIM)
        self.assertEqual(self.mon(state)["health"]["value"], self.mon(before)["health"]["value"])
        self.assertEqual(self.mon(state)["health"]["status"], "retained")
        self.assertEqual(self.mon(state)["species"]["status"], "retained")
        self.assertEqual(state["sides"]["mine"]["left"]["status"], "retained")
        self.assertEqual(state["sides"]["mine"]["shields"]["status"], "retained")
        self.assertEqual(self.mon(state)["energy"]["status"], "pending")
        self.assertEqual(self.mon(state, "opponent")["health"]["status"], "pending")
        self.assertEqual(state["sides"]["opponent"]["shields"]["status"], "pending")
        self.assertEqual(state["pending_attack"]["id"], 1)

    def test_opponent_charge_marks_our_health_and_shields_only(self):
        reader, before = self.settled()
        for t in (.2, .8, 1.4):
            state = reader.update(hidden(t, "shield_prompt"), SLIM)
        self.assertEqual(self.mon(state)["health"]["status"], "pending")
        self.assertEqual(self.mon(state)["energy"]["value"], self.mon(before)["energy"]["value"])
        self.assertEqual(self.mon(state)["energy"]["status"], "retained")
        self.assertEqual(state["sides"]["opponent"]["shields"]["status"], "retained")

    def test_bench_readings_survive_the_next_pokemons_charge(self):
        reader, _ = self.settled()
        reader.update(frame(.3, "Araquanid", 1492), SLIM)
        for t in (.4, 1, 1.6):
            state = reader.update(hidden(t, "my_charged_minigame"), SLIM)
        mon = self.mon(state, name="Lanturn:1493")
        self.assertEqual(mon["health"]["status"], "retained")
        self.assertEqual(mon["energy"]["status"], "retained")

    def test_animation_pixels_do_not_overwrite_pending_health_or_energy(self):
        reader, before = self.settled()
        misleading = frame(.2, health=[.98, 1])
        misleading["phase"] = evidence("my_charged_minigame", .2)
        state = reader.update(misleading, discs(misleading, .1, .1, False))
        self.assertEqual(self.mon(state)["health"]["value"], self.mon(before)["health"]["value"])
        self.assertEqual(self.mon(state)["energy"]["value"], self.mon(before)["energy"]["value"])

    def test_announcement_confirms_cost_without_inventing_damage_or_balance(self):
        reader, before = self.settled()
        reader.update(hidden(.2, "my_charged_minigame"), SLIM)
        f = hidden(.8, "charged_resolution")
        f["text_observation"] = {"fresh_this_frame": True, "records": [{"text": "Lanturn used Thunderbolt!"}]}
        state = reader.update(f, SLIM)
        self.assertEqual(state["pending_attack"]["energy_cost"], 60)
        self.assertEqual(len(state["pending_attack"]["confirmed_changes"]), 1)
        self.assertEqual(self.mon(state)["energy"]["value"], self.mon(before)["energy"]["value"])
        self.assertEqual(self.mon(state, "opponent")["health"]["value"], self.mon(before, "opponent")["health"]["value"])
        for key in ("energy", "health"):
            self.assertEqual(self.mon(state)[key]["status"], "pending")
        f = hidden(.867, "charged_resolution")
        f["text_observation"] = {"fresh_this_frame": True, "records": [{"text": "Lanturn used Thunderbolt!"}]}
        state = reader.update(f, SLIM)
        self.assertEqual(state["pending_attack"]["id"], 1)

    def test_sustained_fighting_reads_back_only_the_visible_fields(self):
        reader, before = self.settled()
        for t in (.2, .8, 1.4):
            reader.update(hidden(t, "my_charged_minigame"), SLIM)
        for t in (2, 2.067, 2.134, 2.201):
            state = reader.update(frame(t, health=[.28, .32]), SLIM)
        self.assertEqual(self.mon(state)["health"]["value"], [.28, .32])
        self.assertEqual(self.mon(state)["health"]["status"], "estimated")
        self.assertEqual(self.mon(state)["energy"]["status"], "pending")
        f = frame(2.268, health=[.28, .32])
        state = reader.update(f, discs(f, .2667, .2, False))
        self.assertIsNone(state["pending_attack"])
        self.assertEqual(self.mon(state)["energy"]["status"], "estimated")
        self.assertNotEqual(self.mon(state)["energy"]["value"], self.mon(before)["energy"]["value"])

    def test_missing_time_does_not_claim_unchanged_health(self):
        reader, _ = self.settled()
        state = reader.update(hidden(5, "my_charged_minigame"), SLIM)
        self.assertEqual(self.mon(state)["health"]["status"], "pending")
        self.assertIn("gap", self.mon(state)["health"]["pending_event"]["reason"])

    def test_result_persists_without_fabricating_a_knockout(self):
        reader, _ = self.settled()
        f = frame(.2)
        f["result"] = evidence("win", .2)
        reader.update(f, SLIM)
        state = reader.update(hidden(1, None), SLIM)
        self.assertEqual(state["result"]["value"], "win")
        self.assertEqual(state["result"]["status"], "retained")
        self.assertIsNone(self.mon(state, "opponent")["fainted"]["value"])

    def test_fresh_readback_recovers_continuity_after_a_time_gap(self):
        reader, _ = self.settled()
        reader.update(hidden(5, None), SLIM)
        for t in (5.067, 5.134, 5.201):
            f = frame(t)
            reader.update(f, discs(f))
        for t in (5.267, 5.867, 6.467):
            state = reader.update(hidden(t, "my_charged_minigame"), SLIM)
        self.assertEqual(self.mon(state)["health"]["status"], "retained")
        self.assertEqual(self.mon(state)["energy"]["status"], "pending")

    def test_unknown_initial_values_stay_unknown(self):
        reader = PublicState({"Surf": 45}, incomplete_start=True)
        state = reader.update(hidden(0, "my_charged_minigame"), SLIM)
        self.assertEqual(state["sides"]["mine"]["pokemon"], {})
        self.assertIsNone(state["sides"]["mine"]["left"]["value"])
        self.assertIsNone(state["pending_attack"]["attacker"])

    def test_fainted_pokemon_keeps_historical_bars_not_current_health(self):
        reader, before = self.settled()
        for t in (.2, .267, .334):
            state = reader.update(frame(t, left=2), SLIM)
        mon = self.mon(state)
        self.assertTrue(mon["fainted"]["value"])
        self.assertEqual(mon["health"]["value"], self.mon(before)["health"]["value"])
        self.assertEqual(mon["health"]["status"], "historical")

    def test_switch_timer_runs_through_a_ten_second_charge_animation(self):
        self.assertEqual(switch_time_left(25, 50, 40), 15)
        self.assertEqual(switch_time_left(5, 50, 40), 0)
        self.assertIsNone(switch_time_left(None, 50, 40))

    def test_literal_move_name_wins_over_plus_variant(self):
        reader = PublicState({"Surf": 45, "Surf+": 45})
        f = frame(0)
        f["text_observation"] = {"fresh_this_frame": True, "records": [{"text": "Lanturn used Surf!"}]}
        state = reader.update(f, SLIM)
        self.assertEqual(state["pending_attack"]["move"], "Surf")

    def test_animation_does_not_promote_already_stale_energy(self):
        reader, _ = self.settled()
        reader.update(hidden(.8, None), SLIM)
        reader.update(hidden(1.4, "shield_prompt"), SLIM)
        state = reader.update(hidden(2, "shield_prompt"), SLIM)
        self.assertEqual(self.mon(state)["energy"]["status"], "stale")

    def test_switch_does_not_promote_an_unconfirmed_bench_balance(self):
        reader, _ = self.settled()
        reader.update(hidden(.8, None), SLIM)
        state = reader.update(frame(1.4, "Araquanid", 1492), SLIM)
        self.assertEqual(self.mon(state, name="Lanturn:1493")["energy"]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
