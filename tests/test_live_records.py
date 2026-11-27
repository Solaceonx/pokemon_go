"""The live battle records in games/live/ (task 45): every GO Battle League record parses, has a result from the fixed
set, both teams, our exact stats, the bot's commit (new battles) and its raw log beside it; index.json lists exactly
the folders; the battle tables are made from notes.json."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAMES = ROOT / "games" / "live"
sys.path.insert(0, str(ROOT / "scripts" / "live"))
import live_record  # noqa: E402

# league battles from here on are played by a bot that writes its commit into the log's start row
COMMIT_FROM = "20261109-000000"


def records():
    for path in sorted(GAMES.glob("*/game.json")):
        yield path.parent.name, json.loads(path.read_text(encoding="utf-8"))


def league():
    return [(stamp, rec) for stamp, rec in records() if rec["source"]["mode"] == "league"]


class LiveRecords(unittest.TestCase):
    def test_there_are_league_records(self):
        self.assertGreater(len(league()), 30)

    def test_each_league_record(self):
        for stamp, rec in league():
            with self.subTest(stamp=stamp):
                self.assertEqual(rec["schema"], "game-record-v1")
                self.assertEqual(rec["variant"], "live-log")
                self.assertEqual(rec["variant_version"], live_record.VARIANT_VERSION)
                result = rec["result"]
                self.assertIn(result["value"], live_record.RESULTS)
                if result["value"] == "fragment":
                    self.assertTrue((GAMES / result["fragment_of"] / "game.json").exists())
                else:
                    self.assertTrue(rec["teams"]["mine"])
                    self.assertTrue(rec["teams"]["theirs"])
                self.assertTrue((GAMES / stamp / "log.jsonl").exists())
                self.assertEqual(rec["source"]["log"], f"games/live/{stamp}/log.jsonl")
                self.assertEqual(rec["built_from"], [rec["source"]["log"]])
                self.assertTrue(rec["source"]["started_utc"])
                for p in rec["teams"]["mine"]:
                    self.assertIn("level", p)
                    self.assertIn("ivs", p)
                if stamp >= COMMIT_FROM:
                    bot = rec["source"]["bot"]
                    # the commit, or why it could not be read (git timed out at a battle's start, 2026-11-09)
                    self.assertTrue(bot["commit"] or bot.get("version_error"), "the bot's commit is in the log's start row")
                    if bot["commit"]:
                        self.assertIsNotNone(bot["dirty"])

    def test_our_exact_stats(self):
        """Level and IVs for each of ours, from games/live/our_teams.json (the owner gives them once)."""
        missing = sorted({f"{stamp}: {p['species']}" for stamp, rec in league() for p in rec["teams"]["mine"]
                          if p.get("level") is None or p.get("ivs") is None})
        if missing:
            self.skipTest(f"levels and IVs not given yet for {len(missing)} of ours in league records "
                          "(games/live/our_teams.json; task 45 waits on the owner)")

    def test_no_trainer_names(self):
        local = ROOT / "data" / "accounts" / "trainers.local.json"
        names = list(json.loads(local.read_text(encoding="utf-8"))) if local.exists() else []
        for path in GAMES.glob("*.json"):
            text = path.read_text(encoding="utf-8")
            for name in names:
                self.assertNotIn(name, text, f"a trainer name in {path.name}")

    def test_index_lists_exactly_the_folders(self):
        index = json.loads((GAMES / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(e["stamp"] for e in index), sorted(stamp for stamp, _ in records()))
        notes = json.loads((GAMES / "notes.json").read_text(encoding="utf-8"))
        for e in index:
            self.assertEqual(e["went_wrong"], (notes.get(e["stamp"]) or {}).get("went_wrong"))
            if e["mode"] == "league":
                self.assertIn("odds", e)

    def test_battle_tables_made_from_notes(self):
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "live" / "battle_tables.py"), "--check"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout)


if __name__ == "__main__":
    unittest.main()
