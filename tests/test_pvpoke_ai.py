"""Integration checks for the single-matchup PvPoke port."""
import subprocess
import sys
import unittest
from pathlib import Path

from pogo.battle import Battle, Mon
from pogo.gamedata import GameData
from pogo.pvpoke_ai import PvpokeAI


class PvpokeAITests(unittest.TestCase):
    def test_reference_battles(self):
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, str(root / "scripts/check_pvpoke_ai.py")],
            cwd=root, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("108 of 108 battles identical to PvPoke; same winner in 108", result.stdout)

    def test_planning_and_shielding_do_not_mutate_battle(self):
        gd = GameData()
        builds = [
            gd.build("malamar", ["PSYWAVE", "SUPER_POWER", "FOUL_PLAY"]),
            gd.build("furret", ["SUCKER_PUNCH", "SWIFT", "TRAILBLAZE"]),
        ]
        agents = [PvpokeAI(), PvpokeAI()]
        mons = [Mon(build, energy=80) for build in builds]
        mons[0].atk_stage, mons[1].def_stage = -1, -2
        battle = Battle([mons[0]], [mons[1]], *agents, shields=(1, 1))

        def state():
            return [(m.hp, m.energy, m.atk_stage, m.def_stage) for m in mons], [s.shields for s in battle.sides]

        before = state()
        for i, agent in enumerate(agents):
            view = battle.views[i]
            self.assertIn(agent.act(view), view.legal())
            for move in view.foe.build.charged:
                self.assertIsInstance(agent.shield(view, view.foe.energy, move), bool)
            self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
