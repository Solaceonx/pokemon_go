"""Comparison players must not inherit another player's cached matchup features."""
import sys
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import engine_versus

from pogo.agents import Masher
from pogo.battle import FAST, SWITCH, Battle
from pogo.evaluation import Evaluator


class EvaluatorIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine_versus.setup()
        cls.pool = engine_versus._state["pool"]

    def test_other_players_and_prior_battles_cannot_change_features(self):
        first = Battle(self.pool[:3], self.pool[10:13], Masher(), Masher(), seed=1)
        second = Battle(self.pool[3:6], self.pool[10:13], Masher(), Masher(), seed=1)
        settings = engine_versus.parse("")
        a = engine_versus.pilot(settings, 1)
        b = engine_versus.pilot(settings, 2)
        expected = Evaluator().features(second.views[0])
        a.evaluator.features(first.views[0])
        self.assertEqual(b.evaluator.features(second.views[0]), expected)
        # A new battle on a reused worker also starts independently of both players.
        c = engine_versus.pilot(settings, 3)
        self.assertEqual(c.evaluator.features(second.views[0]), expected)


class MidSwapMeasurements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine_versus.setup()

    def test_all_six_candidates_build_in_both_scripts(self):
        import exam_variants
        specs = [f"mid_swap_search={gate}{edge}" for gate in ("ready", "hit", "both")
                 for edge in ("", ",switch_edge=0.05")]
        # Supply the exam's model state without needing its private questions or answers.
        with patch.dict(exam_variants.E.L._state, engine_versus._state), \
                patch.dict(exam_variants.E._s, ev=engine_versus.evaluator(None)), \
                patch.object(exam_variants, "_variants", specs):
            exam = exam_variants.builds(7)
        for spec in specs:
            player = engine_versus.pilot(engine_versus.parse("samples=32," + spec), 7)
            self.assertEqual(player.mid_swap_search, exam[spec].mid_swap_search)
            self.assertEqual(player.switch_edge, exam[spec].switch_edge)
            self.assertEqual((player.samples, exam[spec].samples), (32, 32))
        with self.assertRaises(SystemExit):
            engine_versus.parse("mid_swap_search=typo")
        with self.assertRaises(ValueError):
            exam_variants.parse("mid_swap_search=typo")

    def test_switch_counter_excludes_lead_and_replacements(self):
        inner = Masher()
        player = engine_versus.Counted(inner)
        pool = engine_versus._state["pool"]
        battle = Battle(pool[:3], pool[3:6], player, Masher(), seed=1)
        view = battle.views[0]
        with patch.object(inner, "act", return_value=SWITCH[1]):
            player.act(view)
            self.assertEqual(player.mid_swaps, 0)
            battle.turn = 1
            player.act(view)
            self.assertEqual(player.mid_swaps, 1)
        player.replace(view)
        with patch.object(inner, "act", return_value=FAST):
            player.act(view)
        self.assertEqual(player.counts()["mid_swaps"], 1)

    def test_counter_does_not_change_a_game(self):
        pool = engine_versus._state["pool"]
        logs = []
        for counted in (False, True):
            player = engine_versus.pilot(engine_versus.parse("samples=1,horizon=1,mid_swap_search=both"), 8)
            if counted:
                player = engine_versus.Counted(player)
            battle = Battle(pool[:3], pool[10:13], player, Masher(), seed=9, record=True)
            battle.run()
            logs.append((battle.log, battle.winner, battle.turn))
        self.assertEqual(*logs)

    def test_worker_counts_sum_by_battle_and_resume_without_repeating(self):
        spec = "samples=1,horizon=1,mid_swap_search=both"
        base = "samples=1,horizon=1"
        saved = dict(results={}, activity={}, search_ms={}, seed=7, baseline=base,
                     field="standard", evaluator_cache=engine_versus.CACHE_POLICY,
                     counting=engine_versus.COUNTING)
        # Simulate separately returned worker chunks, including both h2h sides.
        for start in (1, 0):
            result = engine_versus.job(("h2h", spec, spec, base, start, 1, 7))
            engine_versus.collect(saved, result)
        rows = saved["activity"]["h2h"][spec]
        self.assertEqual(sum(r["ours"]["battles"] for r in rows.values()), 4)
        self.assertEqual(sum(r["baseline"]["battles"] for r in rows.values()), 4)
        self.assertEqual(sum(r["baseline"]["mid_swap_searches"] for r in rows.values()), 0)
        self.assertGreater(sum(r["ours"]["mid_swap_searches"] for r in rows.values()), 0)
        combined = engine_versus.job(("h2h", spec, spec, base, 0, 2, 7))
        for n, row in combined[4].items():
            for side in ("ours", "baseline"):
                for key in ("battles", "mid_swaps", "mid_swap_searches", "searches"):
                    self.assertEqual(rows[str(n)][side][key], row[side][key])
        ev = engine_versus.evaluator(None)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / "runs" / "engine_versus"
            directory.mkdir(parents=True)
            path = directory / "resume.json"
            path.write_text(json.dumps(saved))
            args = ["engine_versus", "--tag", "resume", "--baseline", base, "--candidates", spec,
                    "--seed", "7", "--pairings", "3", "--crowd", "0", "--pvpoke", "0", "--workers", "1", "--chunk", "3"]
            with patch.object(engine_versus, "ROOT", root), patch.object(sys, "argv", args), \
                    patch.object(engine_versus, "setup"), patch.object(engine_versus, "evaluator", return_value=ev), \
                    patch.object(engine_versus, "job", wraps=engine_versus.job) as job, \
                    redirect_stdout(io.StringIO()):
                engine_versus.main()
                self.assertEqual(job.call_count, 1)
                self.assertEqual(job.call_args.args[0][4:6], (2, 1))
                job.reset_mock()
                engine_versus.main()
                job.assert_not_called()
            after = json.loads(path.read_text())
            self.assertEqual(sum(r["ours"]["battles"] for r in after["activity"]["h2h"][spec].values()), 6)
            self.assertEqual(after["activity"]["h2h"][spec]["0"], rows["0"])

    def test_release_launcher_omits_nice_only_on_windows(self):
        import release_check
        for platform, expected in (("nt", ("python", "trial")), ("posix", ("nice", "python", "trial"))):
            with patch.object(release_check.os, "name", platform), \
                    patch.object(release_check.subprocess, "run") as run, redirect_stdout(io.StringIO()):
                release_check.run("nice", "python", "trial")
                self.assertEqual(run.call_args.args[0], expected)

    def test_one_battle_smoke_has_no_estimated_margin(self):
        self.assertEqual(engine_versus.summary([0.5]), "50.0% (one result; margin unavailable)")


if __name__ == "__main__":
    unittest.main()
