import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import dqn_budget_final as budget


class BudgetFinalTests(unittest.TestCase):
    def test_registered_plan_remains_fixed_and_process_check_observes_current_process(self):
        _, plan = budget.load_plan()
        self.assertEqual(plan['runtime_forecast']['final_battles'], 6000)
        self.assertTrue(budget.worker_alive(os.getpid()))
        with tempfile.TemporaryDirectory() as directory, patch.object(budget, 'ROOT', Path(directory)):
            root = Path(directory) / 'runs/double-dqn/budget-finalization-v1'
            root.mkdir(parents=True)
            (root / 'plan.json').write_text(json.dumps(dict(plan, absolute_deadline_unix=0)))
            with self.assertRaisesRegex(ValueError, 'registered before teacher'):
                budget.load_plan()

    def test_budget_excludes_slow_high_score_without_weakening_final_target(self):
        _, plan = budget.load_plan()
        direct = {'source_run': 'direct', 'status': 'complete', 'score': .6,
                  'forecast_seconds': budget.forecast(plan, {'mode': 'direct'})}
        slow = {'source_run': 'search', 'status': 'complete', 'score': .9,
                'forecast_seconds': budget.forecast(plan, {'mode': 'planning'})}
        now = plan['research_cutoff_unix']
        self.assertEqual(budget.choose(plan, [slow, direct], now), direct)
        tied = dict(direct, source_run='tied')
        self.assertEqual(budget.choose(plan, [tied, direct], now), tied)
        with self.assertRaisesRegex(ValueError, 'do not extend'):
            budget.choose(plan, [direct], plan['absolute_deadline_unix'] - 1)

    def test_live_worker_blocks_selection_and_locked_decision_cannot_follow_canary_outcomes(self):
        _, plan = budget.load_plan()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'runs/double-dqn/budget-finalization-v1'
            teacher = root / 'runs/double-dqn/teacher32-v1'
            target.mkdir(parents=True)
            teacher.mkdir(parents=True)
            plan_path = target / 'plan.json'
            plan_path.write_text(json.dumps(plan))
            (teacher / 'launch.json').write_text(json.dumps({'worker_pid': 42,
                'worker_started_utc': '2026-11-03T05:12:08.3065768Z'}))
            scores = {'relational-v1': .6, 'search-v3': .9, 'symmetry-v5': .55}
            for name in scores:
                source = root / 'runs/double-dqn' / name
                source.mkdir()
                (source / 'result.json').write_text(json.dumps({'name': name}))
                (source / ('trial_plan.json' if name == 'relational-v1' else 'plan.json')).write_text('{}')
                (source / 'model.npz').write_bytes(name.encode())

            def selected(name, canary, *, require_competitive):
                self.assertFalse(canary)
                self.assertFalse(require_competitive)
                mode = 'planning' if name == 'search-v3' else 'direct'
                return (root / 'runs/double-dqn' / name / 'model.npz', [], {'mode': mode},
                    {'score': scores[name], 'margin95': .05, 'lower95': scores[name] - .05,
                     'upper95': scores[name] + .05, 'seed': 38812})

            with patch.object(budget, 'ROOT', root), patch.object(budget, 'load_plan', return_value=(plan_path, plan)), \
                 patch.object(budget.final, 'selection', side_effect=selected), \
                 patch.object(budget.time, 'time', return_value=plan['research_cutoff_unix']):
                with patch.object(budget, 'worker_alive', return_value=True):
                    with self.assertRaisesRegex(RuntimeError, 'duplicate numerical worker'):
                        budget.resolve_selection()
                self.assertFalse((target / 'selection.json').exists())
                with patch.object(budget, 'worker_alive', return_value=False):
                    name, receipt = budget.resolve_selection()
                    self.assertEqual(name, 'relational-v1')
                    self.assertFalse((root / 'runs/double-dqn/final_test_lock.json').exists())
                    with patch.object(budget.time, 'time', return_value=plan['research_cutoff_unix'] + 3600):
                        self.assertEqual(budget.resolve_selection(), (name, receipt))
                    (root / 'runs/double-dqn/relational-v1/result.json').write_text('{"changed":true}')
                    with self.assertRaisesRegex(ValueError, 'Final selection is locked'):
                        budget.resolve_selection()


if __name__ == '__main__':
    unittest.main()
