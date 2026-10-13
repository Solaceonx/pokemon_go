"""Building looks from only what has been seen so far (assemble(..., now=...)), on one of the owner's recordings."""
import gzip
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "recording"))
import assemble as asm  # noqa: E402
sys.path.insert(0, str(ROOT))
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

RAW = ROOT / "games" / "screenrecording-10-10-2026-10-50-13-1" / "raw"


def load():
    rows = [json.loads(l) for l in gzip.open(RAW / "readings.jsonl.gz", "rt", encoding="utf-8")]
    texts = [json.loads(l) for l in gzip.open(RAW / "text.jsonl.gz", "rt", encoding="utf-8")]
    return rows, texts


class LiveAssembly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, texts = load()
        cls.full = asm.assemble([dict(r) for r in rows], texts, ["--battle", "1"])
        cls.span, cls.origin = cls.full["span"], cls.full["origin"]
        cls.rows = [r for r in rows if cls.span[0] <= r["t"] <= cls.span[1]]
        cls.texts = [s for s in texts if cls.span[0] <= s["t"] <= cls.span[1]]
        # Their Discharge: cue read 89.4 s into the fight, buttons gone from 89.3 s.
        cls.cue = next(c["t"] for c in cls.full["timeline"]["charged"] if c["side"] == "theirs" and 85 < c["t"] < 95)

    def until(self, seconds, text_late=0.0, *extra):
        cut = self.origin + seconds
        rows = [dict(r) for r in self.rows if r["t"] <= cut]
        texts = [s for s in self.texts if s["t"] + text_late <= cut]
        return asm.assemble(rows, texts, ["--battle", "1", "--text-delay", str(text_late), *extra], span=(self.span[0], cut), now=cut)

    def test_whole_battle_is_the_offline_answer(self):
        done = asm.assemble([dict(r) for r in self.rows], self.texts, ["--battle", "1"],
                            span=self.span, now=self.span[1])
        self.assertEqual(done["looks"], self.full["looks"])

    def test_unfinished_charged_move_stays_open(self):
        # Five seconds into their move: offline would close it at the last reading; live it is still playing.
        done = self.until(self.cue + 5)
        self.assertFalse(any("foe_charged" in l for l in done["looks"] if l["t"] > self.cue - 1))
        self.assertFalse(any(l["t"] > self.cue for l in done["looks"]))

    def test_buttons_stop_the_fight_before_late_text(self):
        # Text a second late: 0.9 s after the cue it has not arrived, but the buttons have been gone over a second.
        with_stop = self.until(self.cue + 0.9, 1.0, "--buttons-stop", "0.25")
        without = self.until(self.cue + 0.9, 1.0)
        self.assertFalse(any(l["t"] >= self.cue + 0.5 for l in with_stop["looks"]))
        self.assertTrue(any(l["t"] >= self.cue + 0.5 for l in without["looks"]))

    def test_no_result_screen_no_final_knockout(self):
        # Mid-battle, nothing may be taken from a result screen that has not been seen.
        for seconds in (30, 60, 120):
            self.assertFalse(any("result screen" in l.get("note", "") for l in self.until(seconds)["looks"]))


class LivePublicFootage(unittest.TestCase):
    def test_move_still_playing_is_not_the_end_of_the_clip(self):
        raw = ROOT / "games" / "twitch" / "tw-2897295240-left-005" / "raw"
        rows = [json.loads(l) for l in gzip.open(raw / "readings-refined.jsonl.gz", "rt", encoding="utf-8")]
        texts = [json.loads(l) for l in gzip.open(raw / "text.jsonl.gz", "rt", encoding="utf-8")]
        argv = ["--public-footage", "--single-clip"]
        full = asm.assemble([dict(r) for r in rows], texts, argv)
        cue = full["origin"] + next(c["t"] for c in full["timeline"]["charged"] if c["side"] == "theirs")
        cut = cue + 4  # their Gigaton Hammer is playing
        done = asm.assemble([dict(r) for r in rows if r["t"] <= cut], [s for s in texts if s["t"] <= cut], argv,
                            span=(full["span"][0], cut), now=cut)
        self.assertFalse(any("final attack" in l.get("note", "") for l in done["looks"]))
        self.assertFalse(any(l.get("foe_charged") for l in done["looks"] if l["t"] > cue - full["origin"] - 1))


class LateSwitch(unittest.TestCase):
    def test_new_pokemon_counts_from_when_it_came_out(self):
        gd = GameData()

        def run(out_for):
            t = Tracker(gd, [gd.default("melmetal"), gd.default("altaria"), gd.default("jellicent")])
            for k in range(21):  # Stunfisk (Thunder Shock: 2 turns, 9 energy) for ten seconds of looks
                t.update(Observation(t=k * 0.5, my_species="melmetal", foe_species="stunfisk", my_left=3, foe_left=3))
            # Azumarill (Bubble: 3 turns, 11 energy) came out at 8 s; the first look to show it is at 10.5 s.
            t.update(Observation(t=10.5, my_species="melmetal", foe_species="azumarill", my_left=3, foe_left=3,
                                 foe_out_for=out_for))
            return t.foes["stunfisk"].mon.energy, t.foes["azumarill"].mon.energy

        self.assertEqual(run(None), (90, 0))  # all ten seconds go to Stunfisk
        self.assertEqual(run(2.5), (72, 11))  # eight seconds to Stunfisk; Azumarill's switch turn, then one Bubble


if __name__ == "__main__":
    unittest.main()
