"""The optional inputs describing their Pokémon seen off the field (pogo.learner.known_foes, decide.py --wide)."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import _matchup_table, varied  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import N_FEATURES, N_KNOWN, Learner, QNet, known_foes  # noqa: E402

GD = GameData()


class KnownFoesTest(unittest.TestCase):
    def setUp(self):
        self.mine = [GD.default(s) for s in ("melmetal", "altaria", "jellicent")]
        self.theirs = [GD.default(s) for s in ("tinkaton", "corviknight", "ninetales_shadow")]

    def test_nothing_known_at_the_start(self):
        battle = Battle(self.mine, self.theirs, Learner(), Learner(), seed=1)
        self.assertEqual(known_foes(battle.views[0]), [0.0] * N_KNOWN)

    def test_a_foe_that_switched_out_is_described(self):
        battle = Battle(self.mine, self.theirs, Learner(), Learner(), seed=1)
        battle.sides[1].switch_wait = 0
        battle._enter(1, 1)  # Corviknight comes in; Tinkaton is now seen and off the field
        x = known_foes(battle.views[0])
        self.assertEqual(len(x), N_KNOWN)
        self.assertEqual(x[:3], [1.0, 1.0, 0.0])
        table = _matchup_table()
        self.assertEqual(x[3], table.get("melmetal", {}).get("tinkaton", 0.0))  # ours in play first
        self.assertEqual(x[4], table.get("altaria", {}).get("tinkaton", 0.0))
        self.assertEqual(x[6:], [0.0] * 6)

    def test_old_models_see_the_old_inputs(self):
        net = QNet.load(str(Path(__file__).resolve().parent.parent / "runs" / "general-decide" / "q.npz"))
        self.assertFalse(net.wide)
        self.assertFalse(Learner(q=net).wide)

    def test_a_wide_model_logs_and_reads_the_extra_inputs(self):
        net = QNet(seed=3, inputs=N_FEATURES + N_KNOWN)
        self.assertTrue(net.wide)
        log = []
        pool = GD.meta(50)
        rng = random.Random(5)
        bot = Learner(q=net, margin=0.02, log=log, seed=7)
        self.assertTrue(bot.wide)
        Battle(rng.sample(pool, 3), rng.sample(pool, 3), bot, varied(rng, pool), seed=9).run()
        self.assertTrue(log)
        self.assertTrue(all(len(x) == N_FEATURES + N_KNOWN for _, x, _, _ in log))

    def test_logging_for_a_wide_run_before_any_model(self):
        log = []
        Battle(self.mine, self.theirs, Learner(log=log, wide=True, seed=2), Learner(seed=4), seed=6).run()
        self.assertTrue(log)
        self.assertTrue(all(len(x) == N_FEATURES + N_KNOWN for _, x, _, _ in log))


if __name__ == "__main__":
    unittest.main()
