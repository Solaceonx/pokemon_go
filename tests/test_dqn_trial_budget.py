import unittest
from unittest import mock

from scripts import dqn_relational_trial as trial


class TrialBudgetTests(unittest.TestCase):
    def test_recovery_preserves_original_training_and_absolute_deadlines(self):
        state = {'rl_deadline_unix': 200., 'deadline_unix': 250.}
        self.assertEqual(trial.remaining_rl(state, 120.), 80.)
        self.assertEqual(trial.remaining_rl(state, 201.), 0.)
        state['deadline_unix'] = 170.
        self.assertEqual(trial.remaining_rl(state, 120.), 50.)

    def test_backend_invocation_restores_command_line_on_error(self):
        previous = trial.sys.argv
        observed = []
        def fail():
            observed.append(trial.sys.argv[:])
            raise RuntimeError('interrupted')
        with mock.patch.object(trial, 'backend_main', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                trial.invoke(['train', '--run', 'relational-v1'])
        self.assertIs(trial.sys.argv, previous)
        self.assertEqual(observed[0][1:], ['train', '--run', 'relational-v1'])


if __name__ == '__main__':
    unittest.main()
