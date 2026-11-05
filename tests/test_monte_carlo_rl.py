"""Terminal-return credit and explicit experiment provenance."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pogo.rl_experiment import atomic_json, digest
from pogo.standalone_rl import N_FEATURES
from pogo.standalone_rl_v2 import ActorCritic
from scripts import monte_carlo_rl as mc


class CompleteReturnPPO(unittest.TestCase):
    def test_all_decisions_receive_the_complete_terminal_return(self):
        log = [(head, np.zeros(N_FEATURES), np.ones(width, bool), 0, 0., value)
               for head, width, value in (("act", 6, .2), ("shield", 2, -.1), ("act", 6, .4))]
        rows = mc.terminal_advantages(log, reward=1., lam=.3)
        np.testing.assert_allclose([r[6] for r in rows], [.8, 1.1, .6])
        np.testing.assert_allclose([r[7] for r in rows], [1., 1., 1.])

    def test_registration_preserves_weights_and_hashes_the_variant(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            folder = Path(tmp)
            model = ActorCritic(hidden=8)
            def original_prepare(path, args):
                config = {"sources": mc.sources()}
                atomic_json(path / "experiment.json", config)
                model.save(path / "initial.npz", {"experiment": "before-variant-registration"})
                return config
            with patch.object(mc, "_prepare", side_effect=original_prepare):
                config = mc.prepare(folder, None)
            self.assertEqual(config["gae_lambda"], 1.)
            self.assertIn("scripts/monte_carlo_rl.py", config["sources"])
            loaded, meta = ActorCritic.load(folder / "initial.npz")
            self.assertEqual(meta["experiment"], digest(folder / "experiment.json"))
            for key in model.params:
                np.testing.assert_array_equal(loaded.params[key], model.params[key])
            with patch.object(mc, "_prepare", return_value={"sources": config["sources"]}):
                with self.assertRaisesRegex(ValueError, "separate run"):
                    mc.prepare(folder, None)


if __name__ == "__main__":
    unittest.main()
