"""The engine lab's league (scripts/lab/league.py): its rules, bookkeeping and probes, and a tiny run end to end."""
import io
import json
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts" / "lab"), str(ROOT / "scripts")]
import engine_versus  # noqa: E402
import league  # noqa: E402

from pogo.agents import Masher  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.realtime import RealTime  # noqa: E402


class Rules(unittest.TestCase):
    def test_verdict_follows_the_adoption_rule(self):
        level = (0.0, 0.02)
        self.assertEqual(league.verdict((0.55, 0.02), level, level), "pass: confirm on a fresh seed")
        self.assertEqual(league.verdict((0.55, 0.02), level, level, confirm=True), "PASS")
        self.assertEqual(league.verdict((0.55, 0.02), (-0.05, 0.02), level),
                         "fail: wins head to head but loses points to crowd")
        self.assertTrue(league.verdict((0.45, 0.02), level, (-0.1, 0.03)).startswith("fail: worse head to head"))
        self.assertIn("PvPoke", league.verdict((0.45, 0.02), level, (-0.1, 0.03)))
        self.assertTrue(league.verdict((0.51, 0.02), level, level).startswith("no gain shown"))
        self.assertEqual(league.verdict((0.6, float("nan")), level, level), "too few battles")
        self.assertTrue(league.verdict((0.55, 0.02), None, level).startswith("incomplete"))
        self.assertEqual(league.verdict(None, level, level), "no head to head")
        # a loss exactly at its margin is not a loss beyond it
        self.assertEqual(league.verdict((0.55, 0.02), (-0.02, 0.02), level), "pass: confirm on a fresh seed")

    def test_cycles_find_rock_paper_scissors_once(self):
        beats = {("a", "b"): 0.6, ("b", "c"): 0.6, ("c", "a"): 0.6}

        def score(x, y):
            if (x, y) in beats:
                return beats[(x, y)], 0.05
            return 1 - beats[(y, x)], 0.05

        found = league.cycles(["a", "b", "c"], score)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["beyond_margin"])
        self.assertEqual(set(found[0]["cycle"]), {"a", "b", "c"})
        beats[("c", "a")] = 0.4  # now a beats c: transitive
        self.assertEqual(league.cycles(["a", "b", "c"], score), [])
        beats[("c", "a")] = 0.52  # a cycle, but not beyond the margins
        self.assertFalse(league.cycles(["a", "b", "c"], score)[0]["beyond_margin"])

    def test_runs_and_endgame_selection(self):
        self.assertEqual(league.runs_of([0, 1, 2, 5, 6, 9], 2), [[0, 1], [2], [5, 6], [9]])
        self.assertEqual(league.endgame_selection(318, None), list(range(318)))
        some = league.endgame_selection(318, 30)
        self.assertEqual(len(some), 30)
        self.assertEqual(some, sorted(set(some)))
        self.assertTrue(0 <= some[0] and some[-1] < 318 and some[-1] > 280)  # spread, not the first 30

    def test_modal_and_pick(self):
        self.assertEqual(league.modal([1, 1, 2, 1]), (3, 4, 2))
        self.assertEqual(league.modal([True] * 5), (5, 5, 1))
        snaps = [league.Snap(kind, None, 0, None) for kind in ["throw"] * 6 + ["shield", "replace"]]
        got = league.pick(snaps, 3, random.Random(1))
        self.assertEqual(sorted(s.kind for s in got), ["replace", "shield", "throw"])

    def test_reseed_replaces_every_generator(self):
        class Player:
            def __init__(self):
                self.rng, self._mix_rng = random.Random(1), random.Random(2)
                self.gen, self.other = np.random.default_rng(3), 7

        a = Player()
        originals = (a.rng, a._mix_rng, a.gen)
        league.reseed(a, 5)
        self.assertTrue(all(x is not y for x, y in zip(originals, (a.rng, a._mix_rng, a.gen))))
        self.assertEqual(originals[0].random(), random.Random(1).random())  # the original is left alone
        b = Player()
        league.reseed(b, 5)
        self.assertEqual((a.rng.random(), a._mix_rng.random(), a.gen.random()),
                         (b.rng.random(), b._mix_rng.random(), b.gen.random()))
        c = Player()
        league.reseed(c, 6)
        self.assertNotEqual(c.rng.random(), Player().rng.random())
        self.assertNotEqual(a._mix_rng.getstate(), a.rng.getstate())


class Bookkeeping(unittest.TestCase):
    def saved(self):
        return {"results": {
            "h2h": {"b": {"a": {"0": 0.75, "1": 0.5}}, "c": {"a": {"0": 0.5, "1": 0.5}, "b": {"0": 0.0, "1": 0.5}}},
            "crowd": {"a": {"0": 1.0, "1": 0.0, "2": 1.0}, "b": {"0": 1.0, "1": 1.0, "2": 1.0},
                      "c": {"0": 0.0, "1": 0.0, "2": 1.0}},
            "pvpoke": {"a": {"0": 1.0, "1": 1.0}, "b": {"0": 1.0, "1": 1.0}, "c": {"0": 1.0, "1": 0.0}},
            "reader": {"a": {"0": [0.5, 0.25], "1": [0.5, 0.5]}, "b": {"0": [0.5, 0.5], "1": [0.75, 0.75]}},
            "predict": {"a": {"0": [["throw", 4, 4, 1], ["shield", 3, 4, 2]], "1": [["throw", 2, 4, 2]]}},
            "timing": {"a": {"0": {"points": 1.0, "live": True, "rows": [[50.0, 0, 0], [900.0, 1, 0]]},
                             "1": {"points": 0.0, "live": True, "rows": [[70.0, 0, 0]]}}},
            "endgame": {"a": {"0": ["real:x", 0.0, "act"], "1": ["sim:1", 0.1, "shield"]},
                        "b": {"0": ["real:x", 0.05, "act"], "1": ["sim:1", 0.0, "shield"]}}},
            "preset": "screen", "seed": 1, "field": "mixed", "tag": "t", "sizes": dict(league.PRESETS["smoke"])}

    def test_pair_scores_either_way_round(self):
        saved = self.saved()
        self.assertEqual(league.pair_scores(saved, "b", "a"), {0: 0.75, 1: 0.5})
        self.assertEqual(league.pair_scores(saved, "a", "b"), {0: 0.25, 1: 0.5})
        self.assertEqual(league.pair_scores(saved, "a", "z"), {})

    def test_plan_skips_what_is_done_and_keeps_the_way_round(self):
        saved = self.saved()
        sizes = dict(league.PRESETS["smoke"], pairings=3, rr_pairings=2, crowd=3, pvpoke=2, reader=0, predict=0,
                     timing=0)
        seeds = {"battles": 1, "timing": 2, "predict": 3, "endgame": 4}
        plan = league.plan_jobs(saved, ["a", "b", "c"], sizes, {"h2h", "round", "crowd", "pvpoke"}, seeds, "", 0)
        h2h = {(t[1], tuple(t[2])) for t in plan if t[0] == "h2h"}
        # b against a needs pairing 2 only; c against a, pairing 2; c against b is done at 2 pairings
        self.assertEqual(h2h, {(("b", "a"), (2,)), (("c", "a"), (2,))})
        self.assertFalse([t for t in plan if t[0] in ("crowd", "pvpoke")])
        # specs given in another order: the pair already run as b against a is extended that way round
        plan = league.plan_jobs(saved, ["b", "a"], dict(sizes, pairings=4), {"h2h"}, seeds, "", 0)
        self.assertEqual([(t[1], t[2]) for t in plan], [(("b", "a"), [2, 3])])

    def test_collect_merges_by_battle_number(self):
        saved = {}
        league.collect(saved, ("h2h", ("b", "a"), {0: 1.0, 1: 0.5}, 2.0, 2))
        league.collect(saved, ("h2h", ("b", "a"), {1: 0.5, 2: 0.0}, 2.0, 2))
        league.collect(saved, ("crowd", "a", {0: 1.0}, 1.0, 1))
        self.assertEqual(saved["results"]["h2h"]["b"]["a"], {"0": 1.0, "1": 0.5, "2": 0.0})
        self.assertEqual(saved["cost"]["h2h"]["b | a"], [4.0, 4])
        self.assertEqual(league.unit_costs(saved)["crowd"]["a"], 1.0)

    def test_summary_and_table(self):
        saved = self.saved()
        s = league.summarize(saved, ["a", "b", "c"])
        b = s["specs"]["b"]
        self.assertAlmostEqual(b["h2h"]["score"], 0.625)
        self.assertAlmostEqual(b["crowd"]["diff"], 1 / 3)
        self.assertAlmostEqual(b["reader"]["gain"], 0.0)
        self.assertAlmostEqual(s["specs"]["a"]["reader"]["gain"], 0.125)
        self.assertAlmostEqual(b["reader"]["diff"], -0.125)
        self.assertAlmostEqual(s["matrix"]["a"]["b"]["score"], 0.375)
        self.assertAlmostEqual(s["specs"]["c"]["round_robin"]["score"], (0.5 + 0.25) / 2)
        p = s["specs"]["a"]["predict"]
        self.assertAlmostEqual(p["throw"]["modal"], (1.0 + 0.5) / 2)
        self.assertAlmostEqual(p["all"]["varies"], 2 / 3)
        t = s["specs"]["a"]["timing"]
        self.assertEqual(t["decisions"], 3)
        self.assertAlmostEqual(t["cut"], 1 / 3)
        self.assertFalse(t["release_ok"])  # 900 ms at the 99th percentile, a third cut short
        e = s["specs"]["b"]["endgame"]
        self.assertAlmostEqual(e["points"], 2.5)
        self.assertAlmostEqual(e["diff"], -2.5)
        self.assertEqual(s["specs"]["a"]["verdict"], "reference")
        text = league.table(s, ["a", "b", "c"], saved)
        self.assertIn("| 1 | `b` |", text)
        self.assertIn("Round robin", text)
        self.assertEqual(text.count("\n| 2 |"), 2)  # c in the main table and the matrix; no predict, timing rows


class Probes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        league.setup("standard")
        cls.pool = engine_versus._state["pool"]

    def battle(self, agent, seed=4):
        rng = random.Random(seed)
        return Battle(rng.sample(self.pool, 3), rng.sample(self.pool, 3), agent, Masher(), seed=seed, record=True)

    def test_recording_does_not_change_the_game(self):
        for spec in ("bot", "samples=1,horizon=4"):
            plain = self.battle(engine_versus.pilot(engine_versus.parse(spec), 9))
            plain.run()
            recorder = league.Recorder(engine_versus.pilot(engine_versus.parse(spec), 9))
            watched = self.battle(recorder)
            watched.run()
            self.assertEqual(plain.log, watched.log, spec)
            self.assertTrue(recorder.snaps, spec)

    def test_a_snap_asked_with_the_same_dice_answers_the_same(self):
        recorder = league.Recorder(engine_versus.pilot(engine_versus.parse("samples=2,horizon=4"), 3))
        self.battle(recorder).run()
        throws = [s for s in recorder.snaps if s.kind == "throw"][:3]
        self.assertTrue(throws)
        for snap in throws:
            self.assertEqual(snap.ask(11), snap.ask(11))

    def test_live_pilot_has_deadlines(self):
        settings = engine_versus.parse("website")
        live = engine_versus.pilot(settings, 1, cls=league.Live)
        unhurried = engine_versus.pilot(settings, 1)
        self.assertIsInstance(live, RealTime)
        self.assertEqual(live.turn_ms, 500)
        self.assertGreater(unhurried.turn_ms, 1e8)


class EndToEnd(unittest.TestCase):
    def test_tiny_league_runs_and_resumes(self):
        args = ["--reference", "bot", "bot,ko_wait=1", "--tag", "tiny", "--workers", "1", "--field", "standard",
                "--pairings", "2", "--rr-pairings", "2", "--crowd", "2", "--pvpoke", "2", "--reader", "1",
                "--predict", "1", "--positions", "2", "--asks", "2", "--timing", "1", "--endgame", "3",
                "--measures", "h2h,round,crowd,pvpoke,reader,predict,timing,endgame"]
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                summary = league.main(args + ["--out", tmp])
            spec = summary["specs"]["bot,ko_wait=1"]
            for key in ("h2h", "crowd", "pvpoke", "reader", "predict", "timing", "endgame", "verdict"):
                self.assertIn(key, spec)
            saved = json.loads((Path(tmp) / "tiny" / "league.json").read_text(encoding="utf-8"))
            self.assertEqual(len(saved["results"]["crowd"]["bot"]), 2)
            self.assertTrue((Path(tmp) / "tiny" / "table.md").read_bytes().count(b"\r") == 0)
            out = io.StringIO()
            with redirect_stdout(out):
                league.main(args + ["--out", tmp])
            self.assertIn(" 0 jobs ", out.getvalue())
            with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
                league.main(args + ["--out", tmp, "--seed", "99"])  # another seed under the same tag


if __name__ == "__main__":
    unittest.main()
