"""Task 44: keep the old draws, opt into wider training, and compare the website engine fairly."""
import json
import random
import unittest
from unittest.mock import patch

import pogo.agents as agents
import pogo.learner as learner
from pogo.agents import Planner
from pogo.battle import DRAW, Battle
from pogo.gamedata import GameData
from pogo.learner import Learner, N_FEATURES, N_FORMS, QNet
from pogo.realtime import WEBSITE, RealTime
from scripts import any_team_test, decide, engine_versus, wide_teams


class AnyTeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()

    def setUp(self):
        self.tables = agents._matchup_table, learner._matchup_table

    def tearDown(self):
        agents._matchup_table, learner._matchup_table = self.tables

    def config(self, **kw):
        return dict(team=None, teams=None, opponents=[], exploit=None, mid_swap=True, **kw)

    def ids(self, pool):
        return [b.species_id for b in pool]

    def test_default_training_draws_exactly_the_old_teams(self):
        expected_pool = self.gd.meta(50)
        for config in (self.config(), self.config(pool=50, forms=False)):
            _, pool, team, draw, crowd = decide.world(config)
            self.assertIsNone(team)
            self.assertEqual(self.ids(pool), self.ids(expected_pool))
            old, new = random.Random(44), random.Random(44)
            for _ in range(20):
                crowd(new)
                agents.varied(old, expected_pool)
                self.assertEqual(self.ids(draw(new)), self.ids(old.sample(expected_pool, 3)))
                self.assertEqual(self.ids(draw(new)), self.ids(old.sample(expected_pool, 3)))
                self.assertEqual(new.getrandbits(32), old.getrandbits(32))

    def test_wide_training_pool_and_forms_are_explicit(self):
        expected = [b.species_id for b in wide_teams.species_pool(self.gd, 300) if b.forms is None]
        for n in (50, 300):
            plain = self.ids(decide.training_pool(self.gd, n))
            forms = self.ids(decide.training_pool(self.gd, n, forms=True))
            self.assertEqual(forms, plain + wide_teams.FORMS)
            self.assertFalse(set(plain) & set(wide_teams.FORMS))
            self.assertEqual(len(forms), len(set(forms)))
        self.assertEqual(self.ids(decide.training_pool(self.gd, 300)), expected)
        for team in wide_teams.REFERENCE:
            self.assertTrue(set(team) <= set(expected))

    def test_wide_world_reads_table_for_both_players(self):
        table = {"quagsire": {"altaria": 0.25}}
        read = wide_teams.Path.read_text
        def read_table(path, *args, **kwargs):
            return json.dumps(table) if path == wide_teams.OUT / "matchups.json" else read(path, *args, **kwargs)
        with patch.object(wide_teams.Path, "read_text", autospec=True, side_effect=read_table):
            decide.world(self.config(pool=300))
        self.assertEqual(agents._matchup_table(), table)
        self.assertEqual(learner._matchup_table(), table)

    def test_default_world_does_not_load_wide_table(self):
        with patch.object(wide_teams, "set_matchup_table") as load:
            decide.world(self.config())
        load.assert_not_called()

    def test_wide_mixed_world_keeps_training_pool_and_mixed_opponents(self):
        with patch.object(wide_teams, "set_matchup_table"):
            _, pool, _, draw, _ = decide.world(self.config(pool=300, field="mixed"))
        from pogo.teamshape import mixed_field
        expected = mixed_field(self.gd)[1]
        a, b = random.Random(44), random.Random(44)
        self.assertEqual(self.ids(pool), self.ids(decide.training_pool(self.gd, 300)))
        for _ in range(10):
            self.assertEqual(self.ids(draw(a)), self.ids(expected(b)))

    def test_worker_passes_form_inputs_and_wider_start_model(self):
        q = QNet.load(decide.ROOT / "runs/general-decide/q.npz").widened(N_FEATURES + N_FORMS)
        with patch.object(wide_teams, "set_matchup_table"), patch.object(decide, "collect") as collect:
            decide.collect_job((self.config(pool=300, forms=True, playouts=2), q.params, 0.02, 1, 44))
        call = collect.call_args
        self.assertTrue(call.args[2].forms)
        self.assertTrue(call.kwargs["forms"])
        self.assertEqual(call.kwargs["playouts"], 2)
        self.assertTrue(set(wide_teams.FORMS) <= set(self.ids(call.args[1])))

    def test_default_any_team_arguments_and_pilot(self):
        args = any_team_test.arguments([])
        self.assertEqual((args.pilot, args.teams, args.battles, args.engine_pool), ("rulebook", 20, 200, 50))
        self.assertIs(type(any_team_test.make_pilot(args.pilot, 44)), Planner)

    def test_default_any_team_battles_keep_old_dice_and_pilots(self):
        any_team_test._init(None)
        team = self.ids(self.gd.meta(50)[:3])
        for pilot in ("trained", "rulebook"):
            result = any_team_test._battles((("top", 0), team, pilot, 44, 0, 3))
            expected = []
            for k in range(3):
                rng = random.Random(44 * 1_000_003 + k)
                foe = any_team_test._w["draw"](rng)
                dice = rng.getrandbits(32)
                me = (Learner(q=any_team_test._w["ours"], margin=0.02, seed=dice % 99991)
                      if pilot == "trained" else Planner(seed=dice % 99991))
                won = Battle([self.gd.default(s) for s in team], foe, me,
                             Learner(q=any_team_test._w["net"], margin=0.02, seed=dice % 99989), seed=dice).run()
                expected.append(1.0 if won == 0 else 0.5 if won == DRAW else 0.0)
            self.assertEqual(result[3], expected)
            self.assertEqual(result[4], [])

    def test_engine_uses_chosen_pool_and_private_evaluator(self):
        for n in (50, 300):
            any_team_test._init(None, engine_pool=n, pilot="engine")
            a, b = (any_team_test.make_pilot("engine", k) for k in (1, 2))
            self.assertIsInstance(a, RealTime)
            self.assertEqual(a.samples, WEBSITE["samples"])
            self.assertEqual(a.rollout, WEBSITE["rollout"])
            expected = self.gd.meta(50) if n == 50 else any_team_test.builds(self.gd)
            self.assertEqual(self.ids(a.pool), self.ids(expected))
            self.assertIsNot(a.evaluator, b.evaluator)
            self.assertEqual(a.unforeseen_ms, 300)

    def test_serial_jobs_restore_shipped_table(self):
        original = wide_teams._shipped_tables
        try:
            wide_teams._shipped_tables = self.tables
            with patch.object(wide_teams.Path, "read_text", return_value='{"wide": {}}'):
                wide_teams.set_matchup_table("unused")
            list(wide_teams.run_jobs(abs, [-2], 1, wide_teams.set_matchup_table))
            self.assertIs(agents._matchup_table, self.tables[0])
            self.assertIs(learner._matchup_table, self.tables[1])
        finally:
            wide_teams._shipped_tables = original

    def test_engine_versus_website_candidate_reads_forms_in_search(self):
        engine_versus.setup("mixed", team_pool=50)
        q = QNet.load(decide.ROOT / "runs/general-decide/q.npz").widened(N_FEATURES + N_FORMS)
        with patch.object(engine_versus.QNet, "load", return_value=q) as load:
            pilot = engine_versus.pilot(engine_versus.parse("website,q=unused-forms.npz"), 44)
        load.assert_called_once_with(str(engine_versus.ROOT / "unused-forms.npz"))
        self.assertTrue(pilot.forms)
        self.assertEqual(pilot.samples, 32)
        self.assertEqual(self.ids(pilot.pool), self.ids(self.gd.meta(50)))
        pilot.samples, pilot.horizon = 1, 1
        team = [self.gd.default(s) for s in ("mimikyu", "morpeko_full_belly", "cramorant")]
        Battle(team, self.gd.meta(50)[:3], pilot, Planner(), seed=44).run()
        self.assertGreater(pilot.looks, 0)

    def test_engine_versus_defaults_and_top50_draw(self):
        self.assertEqual(engine_versus.parse(""), engine_versus.CONFIRMED)
        engine_versus.setup("mixed")
        self.assertIs(engine_versus._state["draw"], engine_versus._state["our_draw"])
        engine_versus.setup("mixed", team_pool=50)
        top = set(self.ids(self.gd.meta(50)))
        rng = random.Random(44)
        for _ in range(20):
            self.assertTrue(set(self.ids(engine_versus._state["our_draw"](rng))) <= top)


if __name__ == "__main__":
    unittest.main()
