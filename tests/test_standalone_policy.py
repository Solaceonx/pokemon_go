"""The delivered policy uses the evaluated inference mode, without an engine import."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pogo.standalone_policy import load_agent
from pogo.standalone_rl import ActorCritic as SharedModel
from pogo.standalone_rl_v2 import ActorCritic


class SavedStandalonePolicy(unittest.TestCase):
    def test_selected_and_locked_modes_are_loaded_including_legacy_models(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "policy.npz"
            for mode in (False, True):
                ActorCritic(hidden=16).save(path, {"selection": "validation_only", "state": {"best_greedy": mode}})
                agent, _ = load_agent(path, seed=37)
                self.assertIs(agent.greedy, mode)
                ActorCritic(hidden=16).save(path, {"locked": True, "state": {"best_greedy": mode}})
                agent, _ = load_agent(path)
                self.assertIs(agent.greedy, mode)
            SharedModel(hidden=16).save(path, {"selection": "validation_only"})
            self.assertFalse(load_agent(path)[0].greedy)

    def test_raw_round_does_not_silently_use_a_previous_champions_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "round.npz"
            ActorCritic(hidden=16).save(path, {"stage": "ppo", "state": {"best_greedy": True}})
            with self.assertRaisesRegex(ValueError, "explicit"):
                load_agent(path)
            self.assertFalse(load_agent(path, greedy=False)[0].greedy)

    def test_fresh_process_loads_an_independent_policy_without_old_players(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "locked.npz"
            ActorCritic(hidden=16).save(path, {"locked": True, "state": {"best_greedy": True}})
            code = (
                "import sys; from pogo.standalone_policy import load_agent; "
                "agent, meta = load_agent(sys.argv[1]); assert agent.greedy; "
                "assert not any(n in sys.modules for n in "
                "('pogo.agents','pogo.learner','pogo.engine','pogo.battle'))"
            )
            result = subprocess.run([sys.executable, "-c", code, str(path)],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
