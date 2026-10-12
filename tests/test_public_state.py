import copy
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "scripts/recording"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
from public_state import PublicState, energy_candidates, evidence, unknown
from public_fast import score_candidates
from vod_track import enforce_coverage
from vod_pairs import reconcile
from vod_markers import party_patch


def frame(t, name="Lanturn", cp=1493, left=3, health=None):
    def side(owner, species, cp):
        return {"species": {"value": species, "status": "observed", "evidence": {"observed_at_seconds": t}},
                "cp": {"value": cp, "status": "observed", "evidence": {"observed_at_seconds": t}},
                "pokemon_left": evidence(left, t), "shields_left": evidence(2, t),
                "health_estimate": {"status": "estimated", "fraction_range": health or [.48, .52],
                                    "identity": f"{owner}:{species}:{cp}"}}
    return {"timestamp_seconds": t, "mine": side("mine", name, cp), "opponent": side("opponent", "Snorlax", 1488),
            "buttons": [], "phase": evidence("normal_fighting", t), "result": unknown("No result"),
            "text_observation": {"fresh_this_frame": False, "records": []}}


SLIM = {"b": {"l": [0, 0, 0], "r": [0, 0, 0]}}


class EnergyTests(unittest.TestCase):
    def test_energy_stays_in_whole_units(self):
        amounts = energy_candidates([.6, .45], [45, 60], [False, False])
        self.assertIn(27, amounts)
        self.assertTrue(all(isinstance(e, int) and 0 <= e <= 100 for e in amounts))

    def test_ready_ring_excludes_unchargeable_energy(self):
        self.assertTrue(all(e >= 45 for e in energy_candidates([.6, 1], [45, 60], [True, True])))

    def test_contradictory_discs_do_not_invent_energy(self):
        self.assertEqual(energy_candidates([.1, .8], [50, 50], [False, False]), [])

    def test_missing_cost_is_unknown(self):
        self.assertEqual(energy_candidates([.5, .6], [None, 50], [False, False]), [])

    def test_second_helping_keeps_all_compatible_integers(self):
        self.assertIn(72, energy_candidates([.6, .2], [45, 60], [True, True]))


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'pixel checks require NumPy')
class MarkerTests(unittest.TestCase):
    def test_small_dark_marker_surrounded_by_pale_panel_is_not_alive(self):
        import numpy as np
        patch = np.zeros((13, 13, 3), dtype='uint8')
        patch[:, :, 2] = 240
        patch[4:9, 4:9, 2] = 80
        self.assertFalse(party_patch(patch, np))

    def test_blue_sky_patch_is_unknown(self):
        import numpy as np
        patch = np.full((13, 13, 3), [105, 190, 245], dtype='uint8')
        self.assertIsNone(party_patch(patch, np))


class LedgerTests(unittest.TestCase):
    def test_no_default_stats_or_unseen_team(self):
        state = PublicState({}).update(frame(0), SLIM)
        ours = state["sides"]["mine"]
        self.assertEqual(len(ours["pokemon"]), 1)
        mon = ours["pokemon"][ours["active"]]
        for key in ("maximum_hp", "fast_move", "energy", "form"):
            self.assertIsNone(mon[key]["value"])
        self.assertIsNone(state["battle_clock"]["value"])

    def test_hidden_headers_keep_historical_identity_with_age(self):
        reader = PublicState({})
        reader.update(frame(0), SLIM)
        hidden = frame(2)
        for side in ("mine", "opponent"):
            hidden[side]["species"] = unknown("Header hidden")
            hidden[side]["cp"] = unknown("Header hidden")
        state = reader.update(hidden, SLIM)
        mon = state["sides"]["mine"]["pokemon"]["Lanturn:1493"]
        self.assertEqual(mon["species"]["status"], "retained")
        self.assertEqual(mon["species"]["age_seconds"], 2)

    def test_bench_health_is_retained_under_its_identity(self):
        reader = PublicState({})
        reader.update(frame(0, health=[.3, .35]), SLIM)
        state = reader.update(frame(1, "Araquanid", 1492, health=[.8, .85]), SLIM)
        ours = state["sides"]["mine"]
        self.assertEqual(ours["pokemon"]["Lanturn:1493"]["health"]["value"], [.3, .35])
        self.assertEqual(ours["active"], "Araquanid:1492")

    def test_unsettled_counter_does_not_confirm_faint(self):
        reader = PublicState({})
        for t in [0, .067, .134]: reader.update(frame(t), SLIM)
        state = reader.update(frame(.2, left=2), SLIM)
        self.assertEqual(state["sides"]["mine"]["left"]["value"], 3)
        self.assertIsNone(state["sides"]["mine"]["pokemon"]["Lanturn:1493"]["fainted"]["value"])

    def test_sustained_counter_confirms_faint_without_fake_zero_hp(self):
        reader = PublicState({})
        for t in [0, .067, .134]: reader.update(frame(t), SLIM)
        for t in [.2, .267, .334]: state = reader.update(frame(t, left=2), SLIM)
        mon = state["sides"]["mine"]["pokemon"]["Lanturn:1493"]
        self.assertTrue(mon["fainted"]["value"])
        self.assertEqual(mon["health"]["value"], [.48, .52])

    def test_exact_announced_opponent_move_is_remembered(self):
        f = frame(0)
        f["text_observation"] = {"fresh_this_frame": True, "records": [{"text": "Snorlax used Body Slam!"}]}
        state = PublicState({"Body Slam": 35}).update(f, SLIM)
        moves = state["sides"]["opponent"]["pokemon"]["Snorlax:1488"]["charged_moves"]
        self.assertEqual(next(iter(moves.values()))["value"], "Body Slam")

    def test_counter_confirmation_after_new_header_marks_outgoing_mon(self):
        reader = PublicState({})
        for t in [0, .067, .134]: reader.update(frame(t), SLIM)
        for t in [.2, .267, .334]: state = reader.update(frame(t, "Araquanid", 1492, left=2), SLIM)
        mons = state["sides"]["mine"]["pokemon"]
        self.assertTrue(mons["Lanturn:1493"]["fainted"]["value"])
        self.assertIsNone(mons["Araquanid:1492"]["fainted"]["value"])

    def test_partial_beginning_never_passes_complete_verdict(self):
        v = enforce_coverage({"verdict": "pass", "failed": [], "notes": []}, {"incomplete_start": True})
        self.assertEqual(v["verdict"], "fail")
        self.assertFalse(v["full_game_state_verified"])


class FastInferenceTests(unittest.TestCase):
    def test_saved_compressed_observations_are_read_as_utf8(self):
        spec = importlib.util.spec_from_file_location("track_script", ROOT / "scripts/track.py")
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            line = json.dumps({"t": 0, "note": "Pokémon"}, ensure_ascii=False) + "\n"
            with gzip.open(folder / "observations.jsonl.gz", "wt", encoding="utf-8") as stream:
                stream.write(line)
            self.assertEqual(list(script.observation_lines(folder)), [line])

    def test_equal_energy_rates_stay_ambiguous(self):
        fit = score_candidates([(3, 18)] * 4, [("BITE", 3, 1), ("DRAGON_BREATH", 3, 1)])
        self.assertIsNone(fit["selected"])

    def test_repeated_energy_rises_select_rate_without_team_sheet(self):
        fit = score_candidates([(3, 18), (4, 24), (5, 30)], [("WATER_GUN", 3, 1), ("SPARK", 8, 2)])
        self.assertEqual(fit["selected"], "WATER_GUN")
        self.assertFalse(fit["accuracy_verified"])

    def test_one_rise_is_insufficient_evidence(self):
        fit = score_candidates([(3, 18)], [("WATER_GUN", 3, 1)])
        self.assertIsNone(fit["selected"])

    def test_model_fast_does_not_mark_moves_or_stats_known(self):
        spec = importlib.util.spec_from_file_location("track_script", ROOT / "scripts/track.py")
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        from pogo.gamedata import GameData
        builds, known = script.load_team(GameData(), {"pokemon": [{"species": "Lanturn", "model_fast": "WATER_GUN"}]})
        self.assertEqual(builds[0].fast.id, "WATER_GUN")
        self.assertEqual(known, [False])


class AssemblyTests(unittest.TestCase):
    def test_public_clip_keeps_unicode_announcements_after_last_health_bar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rr = []
            for i in range(421):
                t = i / 15
                def side(name):
                    return {"sp": name if i % 10 == 0 else None, "cp": 1499, "sh": 2, "left": 3,
                            "seg": [["cyan", 138]] if t < 18 else None, "w": 138 if t < 18 else None}
                rr.append({"t": t, "m": side("Melmetal"), "o": side("Azumarill"), "phase": None,
                           "result": None, "b": {"l": [0, 0, 0], "r": [0, 0, 0]}})
            texts = [{"t": 20, "text": [["middle", "Get Ready!"]]},
                     {"t": 27, "text": [["middle", "tal used Double lron Bash！"], ["lower", "NOT VERY EFFECTIVE"]]}]
            for filename, values in (("readings.jsonl.gz", rr), ("text.jsonl.gz", texts)):
                with gzip.open(root / filename, "wt", encoding="utf-8") as f:
                    for row in values: f.write(json.dumps(row, ensure_ascii=False) + "\n")
            done = subprocess.run([sys.executable, str(HERE / "assemble.py"), str(root / "readings.jsonl.gz"),
                                  str(root / "text.jsonl.gz"), str(root / "game"), "--public-footage", "--single-clip"],
                                  cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(done.returncode, 0, done.stderr)
            timeline = json.loads((root / "game/timeline.json").read_text())
            self.assertEqual(timeline["charged"][0]["move"], "Double Iron Bash")
            team = json.loads((root / "game/team.json").read_text())
            self.assertNotIn("fast", team["pokemon"][0])
            looks = [json.loads(line) for line in (root / "game/observations.jsonl").read_text().splitlines()]
            self.assertEqual(looks[-1]["my_charged"], "Double Iron Bash")
            self.assertNotIn("foe_hp", looks[-1])
            self.assertNotIn("foe_left", looks[-1])

    def test_paired_move_needs_same_source_match_and_opposite_side(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            own, peer = root / 'tw-own', root / 'tw-peer'
            for folder, view in [(own, 'left'), (peer, 'right')]:
                (folder / 'tracker').mkdir(parents=True)
                (folder / 'battle.json').write_text(json.dumps({'view_id': view, 'match_id': 'm1',
                    'source_sha256': 'same-source', 'source_start_seconds': 100}))
            timeline = {'clip_origin_seconds': 1, 'charged': [{'t': 5, 'side': 'theirs', 'move': None}]}
            other = {'clip_origin_seconds': 1, 'charged': [{'t': 5.3, 'side': 'mine', 'move': 'Surf'}]}
            game = own / 'tracker'
            (game / 'timeline.json').write_text(json.dumps(timeline))
            (game / 'observations.jsonl').write_text(json.dumps({'t': 15, 'foe_charged': True})+'\n')
            (peer / 'tracker/assembly-original-timeline.json').write_text(json.dumps(other))
            changes = reconcile(own, game)
            self.assertEqual(len(changes), 1)
            self.assertEqual(json.loads((game/'observations.jsonl').read_text())['foe_move'], 'Surf')
            self.assertFalse(changes[0]['accuracy_verified'])
            # A similar clip from another source must not become evidence.
            p = json.loads((peer/'battle.json').read_text()); p['source_sha256'] = 'different'
            (peer/'battle.json').write_text(json.dumps(p))
            (game/'timeline.json').write_text(json.dumps(timeline))
            self.assertEqual(reconcile(own, game), [])


if __name__ == "__main__": unittest.main()
