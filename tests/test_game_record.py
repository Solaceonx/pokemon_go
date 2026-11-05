"""The game record (scripts/recording/game_record.py): one readable file built from a tracked game's outputs."""
import gzip
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "recording"))
import game_record as gr  # noqa: E402

REAL = ROOT / "games" / "lyxia-2026-10-10"


def mon(species, name, hp, hp_max, energy, fast, charged, theirs=False, energy_range=None, ceiling=None):
    """One Pokémon as the tracker's state() writes it. fast: (id, name, turns, gain); charged: (id, name, cost, used)."""
    p = {"species": species, "name": name, "types": [], "known_from": "seen" if theirs else "team_sheet", "cp": 1500,
         "cp_read_from_screen": False, "stats_assumed": theirs, "level": 20, "ivs": [0, 0, 0], "hp": hp,
         "hp_max": hp_max, "hp_share": round(hp / hp_max, 3), "energy": energy, "fainted": hp <= 0,
         "attack_stage": 0, "defense_stage": 0,
         "fast_move": {"id": fast[0], "name": fast[1], "type": "x", "turns": fast[2], "energy_gain": fast[3],
                       "known_from": "inferred" if theirs else "team_sheet"},
         "charged_moves": [{"id": c[0], "name": c[1], "type": "x", "energy": c[2],
                            "known_from": "seen" if c[3] else ("guessed" if theirs else "team_sheet"), "times_used": c[3]}
                           for c in charged]}
    if theirs:
        p.update(energy_range=energy_range or [energy, energy], energy_by_clock=energy if ceiling is None else ceiling,
                 fast_move_odds={fast[0]: 1.0}, charged_move_odds={c[0]: 1.0 if c[3] else 0.6 for c in charged})
    return p


BUBBLE, CLAW = ("BUBBLE", "Bubble", 3, 11), ("SHADOW_CLAW", "Shadow Claw", 2, 6)
SHOCK, MUD = ("THUNDER_SHOCK", "Thunder Shock", 2, 9), ("MUD_SHOT", "Mud Shot", 2, 9)


def look(t, turns, mine, my_active, theirs, their_active, their_left=3):
    return {"t": t, "fighting_turns": turns, "warnings": 0, "matchup": None,
            "me": {"active": my_active, "shields": 2, "left": 3, "switch_ready_in": 0.0, "pokemon": mine},
            "opponent": {"active": their_active, "shields": 2, "left": their_left, "unseen": their_left - len(theirs),
                         "switch_ready_in": 0.0, "fast_move_turns_left": 0, "pokemon": theirs}}


def battle():
    """A short made-up battle: their Double Iron Bash, our Hydro Pump, our switch, their faint."""
    def ours(azu_hp, azu_e, used=0):
        return [mon("azumarill", "Azumarill", azu_hp, 100, azu_e, BUBBLE, [("HYDRO_PUMP", "Hydro Pump", 40, used)]),
                mon("sableye", "Sableye", 120, 120, 0, CLAW, [("FOUL_PLAY", "Foul Play", 45, 0)])]

    def melmetal(hp, e, used=0):
        return mon("melmetal", "Melmetal", hp, 150, e, SHOCK, [("DOUBLE_IRON_BASH", "Double Iron Bash", 35, used)],
                   theirs=True)

    quagsire = mon("quagsire", "Quagsire", 140, 140, 0, MUD, [("AQUA_TAIL", "Aqua Tail", 35, 0)], theirs=True)
    states = [
        look(0.0, 0, ours(100, 0), 0, [melmetal(150, 0)], 0),
        look(5.0, 10, ours(95, 33), 0, [melmetal(150, 45)], 0),
        look(15.5, 11, ours(55, 33), 0, [melmetal(150, 0, 1)], 0),   # after their Double Iron Bash (cue 5.6)
        look(30.0, 20, ours(55, 5, 1), 0, [melmetal(90, 18, 1)], 0),  # after our Hydro Pump (cue 20.2)
        look(31.0, 21, ours(55, 5, 1), 1, [melmetal(90, 18, 1)], 0),  # we switch to Sableye
        look(40.0, 39, ours(55, 5, 1), 1, [melmetal(0, 50, 1), quagsire], 1, their_left=2),  # Melmetal fainted
        look(50.0, 59, ours(55, 5, 1), 1, [melmetal(0, 50, 1), quagsire], 1, their_left=2),
    ]
    events = [
        {"t": 0.0, "event": "start", "my_team": ["azumarill", "sableye"]},
        {"t": 0.0, "event": "foe_seen", "species": "melmetal"},
        {"t": 5.0, "event": "unexplained", "what": "my health drop", "drop": 5, "expected_per_hit": 4},
        {"t": 5.0, "event": "foe_fast_learned", "species": "melmetal", "move": "THUNDER_SHOCK",
         "misfit": {"THUNDER_SHOCK": 0.1}, "ruled_out": []},
        {"t": 15.5, "event": "foe_charged", "move": "DOUBLE_IRON_BASH", "shielded": False, "energy": [0, 0],
         "energy_before": [30, 30], "energy_before_by_clock": 50},
        {"t": 30.0, "event": "my_charged", "move": "HYDRO_PUMP", "shielded": False},
        {"t": 31.0, "event": "my_switch", "to": "sableye"},
        {"t": 40.0, "event": "foe_faint", "next": "quagsire"},
        {"t": 40.0, "event": "foe_seen", "species": "quagsire"},
        {"t": 50.0, "event": "end", "result": "win"},
    ]
    timeline = {"end": 50.0, "result": "win",
                "charged": [{"t": 5.6, "side": "theirs", "move": "Double Iron Bash", "blocked": False},
                            {"t": 20.2, "side": "mine", "move": "Hydro Pump", "blocked": False}],
                "steps": {"mine": [[1.0, 4], [3.0, 4], [6.0, 30]], "theirs": [[2.0, 3]]}}
    return states, events, timeline


def save(folder: Path, states, events, timeline, compress=False, **extra):
    folder.mkdir(parents=True, exist_ok=True)
    for name, rows in (("states.jsonl", states), ("events.jsonl", events)):
        body = "".join(json.dumps(r) + "\n" for r in rows)
        if compress:
            with gzip.open(folder / (name + ".gz"), "wt", encoding="utf-8") as out:
                out.write(body)
        else:
            (folder / name).write_text(body, encoding="utf-8")
    files = {"state.json": states[-1], "timeline.json": timeline, "track.json": {"unexplained": 1},
             "verdict.json": {"verdict": "pass", "failed": [], "notes": [], "result": "win"}, **extra}
    for name, value in files.items():
        (folder / name).write_text(json.dumps(value), encoding="utf-8")


class MadeUpBattle(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.states, self.events, self.timeline = battle()
        save(self.dir / "game", self.states, self.events, self.timeline)
        self.rec = gr.build(self.dir / "game")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def kinds(self, rec=None):
        return [a["kind"] for a in (rec or self.rec)["actions"]]

    def of(self, kind, side=None, rec=None):
        return [a for a in (rec or self.rec)["actions"] if a["kind"] == kind and (side is None or a.get("side") == side)]

    def test_actions_in_order(self):
        self.assertEqual(self.kinds(), ["start", "fighting", "charged", "fighting", "charged", "fighting", "switch",
                                        "fighting", "faint", "fighting", "end"])
        start = self.rec["actions"][0]
        self.assertEqual((start["mine"], start["theirs"]), ("Azumarill", "Melmetal"))

    def test_their_charged_move(self):
        move = self.of("charged", "theirs")[0]
        self.assertEqual(move["t"], 5.6)  # when it started on screen, not the look after it
        self.assertEqual(move["resolved_t"], 15.5)
        self.assertTrue(move["cue"])
        self.assertEqual((move["move"], move["move_known_from"], move["cost"]), ("Double Iron Bash", "seen", 35))
        self.assertEqual((move["energy_before"], move["energy_ceiling"]), ([30, 30], 50))
        self.assertEqual(move["energy_short_by"], 5)
        self.assertEqual((move["target"], move["target_hp_before"], move["target_hp_after"]), ("Azumarill", 95, 55))
        self.assertFalse(move["shielded"])

    def test_our_charged_move(self):
        move = self.of("charged", "mine")[0]
        self.assertEqual((move["t"], move["move"], move["cost"]), (20.2, "Hydro Pump", 40))
        self.assertEqual(move["energy_before"], 45)  # 5 left after paying 40
        self.assertNotIn("energy_short_by", move)
        self.assertEqual((move["target"], move["target_hp_before"], move["target_hp_after"]), ("Melmetal", 150, 90))

    def test_fighting_before_the_first_charged_move(self):
        fight = self.rec["actions"][1]
        self.assertEqual((fight["t"], fight["until"], fight["turns"]), (0.0, 5.6, 11))
        self.assertEqual(fight["mine"]["fast_moves_if_no_pause"], 3)  # Bubble, 3 turns
        self.assertEqual(fight["theirs"]["fast_moves_if_no_pause"], 5)  # Thunder Shock, 2 turns
        self.assertEqual(fight["theirs"]["hits_seen"], 2)  # steps on our bar at 1.0 and 3.0; 6.0 is after the cue
        self.assertEqual(fight["mine"]["hits_seen"], 1)
        self.assertEqual(fight["unexplained_health_changes"], 1)
        self.assertEqual(fight["state"]["theirs"]["energy"], [45, 45])  # the look before the cue

    def test_switch_faint_end(self):
        switch, faint, end = self.of("switch")[0], self.of("faint")[0], self.of("end")[0]
        self.assertEqual((switch["side"], switch["from"], switch["to"]), ("mine", "Azumarill", "Sableye"))
        self.assertEqual((faint["side"], faint["pokemon"], faint["next"]), ("theirs", "Melmetal", "Quagsire"))
        self.assertEqual((end["result"], end["result_from"], end["left"]), ("win", "result screen", {"mine": 3, "theirs": 2}))
        self.assertEqual(self.rec["summary"]["charged"], {"mine": 1, "theirs": 1})
        self.assertEqual(self.rec["summary"]["faints"], {"mine": 0, "theirs": 1})

    def test_deductions_and_teams(self):
        (found,) = self.rec["deductions"]
        self.assertEqual((found["pokemon"], found["what"], found["value"]), ("Melmetal", "fast move", "Thunder Shock"))
        names = [p["name"] for p in self.rec["teams"]["theirs"]]
        self.assertEqual(names, ["Melmetal", "Quagsire"])
        self.assertEqual(self.rec["teams"]["theirs"][1]["other_charged_moves"], {"Aqua Tail": 0.6})
        self.assertEqual(self.rec["source"], {"kind": "own_recording"})

    def test_text(self):
        story = gr.text(self.rec)
        self.assertIn("WIN (result screen)", story)
        self.assertIn("0:05.6  They throw Double Iron Bash (Melmetal, 30 of 35 energy, clock allows 50) -> Azumarill 95% -> 55%",
                      story)
        self.assertIn("[short by 5 energy by our count]", story)
        self.assertIn("We switch Azumarill -> Sableye", story)
        self.assertIn("Their Melmetal faints; Quagsire comes in", story)
        self.assertIn("worked out: their Melmetal has Thunder Shock", story)

    def test_compressed_files_give_the_same_record(self):
        save(self.dir / "gz", self.states, self.events, self.timeline, compress=True)
        rec = gr.build(self.dir / "gz")
        self.assertEqual(rec["actions"], self.rec["actions"])

    def test_charged_move_without_a_cue(self):
        timeline = dict(self.timeline, charged=self.timeline["charged"][:1])
        save(self.dir / "nocue", self.states, self.events, timeline)
        move = self.of("charged", "mine", gr.build(self.dir / "nocue"))[0]
        self.assertEqual((move["t"], move["cue"], move["move_known_from"]), (30.0, False, "inferred"))

    def test_bar_not_read_after_a_charged_move(self):
        # The look after our Hydro Pump did not read their bar. Since 2026-11-04 the tracker takes the damage off by
        # the rules; games tracked before that left the health as it was, which the record shows as unknown.
        states = [json.loads(json.dumps(s)) for s in self.states]
        states[2]["matchup"] = {"ours": {"charged": [{"id": "HYDRO_PUMP", "damage": 60}]}, "theirs": {"charged": []}}
        looks = [{"t": s["t"], "my_hp": 0.5, "foe_hp": 0.6} for s in states]
        del looks[3]["foe_hp"]
        old = json.loads(json.dumps(states))
        old[3]["opponent"]["pokemon"][0]["hp"] = 150  # the old tracker: health after = health before
        for name, version in (("new", states), ("old", old)):
            save(self.dir / name, version, self.events, self.timeline)
            (self.dir / name / "observations.jsonl").write_text("".join(json.dumps(o) + "\n" for o in looks),
                                                                encoding="utf-8")
        rec = gr.build(self.dir / "new")
        ours, theirs = self.of("charged", "mine", rec)[0], self.of("charged", "theirs", rec)[0]
        self.assertEqual((ours["target_bar_read"], ours["expected_damage"]), (False, 60))
        self.assertTrue(theirs["target_bar_read"])
        self.assertIn("-> Melmetal 100% -> 60% (bar not read; by the rules)", gr.text(rec))
        self.assertIn("-> Melmetal 100% -> ? (bar not read; the move does ~40%)", gr.text(gr.build(self.dir / "old")))

    def test_public_footage(self):
        source = {"source_url": "https://www.twitch.tv/videos/1", "view_id": "left", "match_id": "m1",
                  "source_start_seconds": 10.0, "source_end_seconds": 60.0, "incomplete_start": True, "incomplete_end": False}
        save(self.dir / "pub", self.states, self.events, dict(self.timeline, result=None, public_footage=True),
             **{"source.json": source})
        rec = gr.build(self.dir / "pub")
        self.assertEqual((rec["source"]["kind"], rec["source"]["view"]), ("public_footage", "left"))
        self.assertTrue(rec["actions"][0]["incomplete_start"])
        self.assertEqual((rec["result"]["value"], rec["result"]["from"]), ("win", "who had Pokémon left"))
        self.assertIn("Mine = the player whose screen this is.", gr.text(rec))

    def test_write_and_find(self):
        rec = gr.write(self.dir / "game")
        self.assertEqual(json.loads((self.dir / "game" / "game.json").read_text(encoding="utf-8"))["actions"],
                         rec["actions"])
        self.assertTrue((self.dir / "game" / "game.txt").read_text(encoding="utf-8").startswith("game . own recording"))
        self.assertIn(self.dir / "game", gr.tracked(self.dir))

    def test_not_a_tracked_game(self):
        (self.dir / "empty").mkdir()
        with self.assertRaises(ValueError):
            gr.build(self.dir / "empty")


@unittest.skipUnless((REAL / "states.jsonl").exists(), "needs the owner's first tracked recording")
class FirstRecording(unittest.TestCase):
    """The owner's first recording: 10 charged moves, 2 switches and 4 faints, a win (status.md)."""

    @classmethod
    def setUpClass(cls):
        cls.rec = gr.build(REAL)
        cls.timeline = json.loads((REAL / "timeline.json").read_text(encoding="utf-8"))

    def test_every_charged_move_at_its_cue(self):
        charged = [a for a in self.rec["actions"] if a["kind"] == "charged"]
        self.assertEqual(len(charged), 10)
        self.assertTrue(all(a["cue"] for a in charged))
        self.assertEqual([(a["t"], a["side"], a["move"]) for a in charged],
                         [(c["t"], c["side"], c["move"]) for c in self.timeline["charged"]])
        self.assertTrue(all(0 < a["resolved_t"] - a["t"] < gr.CUE_WINDOW for a in charged))

    def test_changes_of_pokemon_and_result(self):
        kinds = [a["kind"] for a in self.rec["actions"]]
        self.assertEqual((kinds.count("switch"), kinds.count("faint")), (2, 4))
        self.assertEqual((self.rec["result"]["value"], self.rec["result"]["from"]), ("win", "result screen"))
        self.assertEqual(self.rec["checks"]["verdict"], "pass")

    def test_times_run_forward(self):
        times = [a["t"] for a in self.rec["actions"]]
        self.assertEqual(times, sorted(times))

    def test_text_reads(self):
        story = gr.text(self.rec)
        self.assertIn("Start: Melmetal vs Cramorant", story)
        self.assertIn("They switch Cramorant -> Oinkologne", story)


if __name__ == "__main__":
    unittest.main()
