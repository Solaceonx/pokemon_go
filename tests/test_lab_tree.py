"""Engine lab: the tree engine (pogo/lab/tree.py) plays as the flat engine at its defaults, and its options work."""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
from pogo.battle import Battle  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.lab import KEYS, engine_class, setting  # noqa: E402
from pogo.lab.tree import Node, TreeEngine, prior_logits  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.realtime import RealTime  # noqa: E402

NO_LIMIT = {k: 1e9 for k in ("turn_ms", "unforeseen_ms", "after_charged_ms", "after_faint_ms", "replace_ms", "start_ms")}


class LabTree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.pool = cls.gd.meta(50)
        cls.net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
        cls.ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")

    def engine(self, cls=TreeEngine, seed=3, **kw):
        kw.setdefault("samples", 2)
        return cls(Evaluator(self.ev.model), self.pool, rollout="bot", horizon=6, edge=0.03, q=self.net, margin=0.02,
                   seed=seed, **NO_LIMIT, **kw)

    def game(self, a, b, g=0):
        rng = random.Random(100 + g)
        battle = Battle(rng.sample(self.pool, 3), rng.sample(self.pool, 3), a, b, seed=g, record=True)
        battle.run()
        return battle.winner, battle.log

    def test_defaults_play_as_the_flat_engine(self):
        for g in range(2):
            flat = self.game(self.engine(cls=RealTime), Learner(q=self.net, margin=0.02, seed=9), g)
            tree = self.engine()
            same = self.game(tree, Learner(q=self.net, margin=0.02, seed=9), g)
            self.assertEqual(flat, same)
            self.assertGreater(tree.looks, 0)
            self.assertEqual(tree.nodes_made, 0)

    def test_tree_options_play_whole_games(self):
        for kw in (dict(depth=2), dict(depth=2, root="sh", samples=3), dict(depth=1, adversary=True),
                   dict(root="sh", gumbel=1.0, samples=3), dict(depth=2, closed=False, c_puct=1.0, k0=0.0)):
            with self.subTest(**kw):
                e = self.engine(**kw)
                e.record = []
                winner, _ = self.game(e, Learner(q=self.net, margin=0.02, seed=9), 1)
                self.assertIn(winner, (-1, 0, 1))
                self.assertTrue(e.record)
                for row in e.record:
                    self.assertIn(row["choice"], row["options"])
                    self.assertTrue(all(0.0 <= w <= 1.0 for w in row["worth"].values()))
                    budget = 2 * 0 + kw.get("samples", 2) * len(row["options"])
                    self.assertLessEqual(sum(row["battles"].values()), budget)
                if kw.get("depth"):
                    self.assertGreater(e.nodes_made, 0)

    def test_stay_is_played_as_staying(self):
        from pogo.battle import SWITCH
        from pogo.lab.tree import _Stay
        for g in range(6):
            rng = random.Random(g)
            bot = Learner(q=self.net, margin=0.02, seed=g)
            battle = Battle(rng.sample(self.pool, 3), rng.sample(self.pool, 3), _Stay(bot),
                            Learner(q=self.net, margin=0.02, seed=1), seed=g)
            view = battle.views[0]
            action = battle.agents[0].act(view)
            self.assertNotIn(action, SWITCH)
            self.assertEqual(bot._judged, (view.me.active, view.foe.build.uid))
        e = self.engine(fix_stay=True, samples=2)
        e.record = []
        for g in range(2):
            self.game(e, Learner(q=self.net, margin=0.02, seed=9), g)
        self.assertTrue(any(r["head"] == "swap" for r in e.record))

    def test_halving_spends_more_on_the_last_two(self):
        e = self.engine(root="sh", samples=4)
        e.record = []
        for g in range(3):
            self.game(e, Learner(q=self.net, margin=0.02, seed=9), g)
        three = [r for r in e.record if len(r["options"]) == 3]
        if not three:
            self.skipTest("no three-option decision in these games")
        for r in three:
            counts = sorted(r["battles"].values())
            self.assertEqual(counts[0], 2)  # 12 battles: 2 rounds; 2 seeds for all three, then 3 more for two
            self.assertEqual(counts[1:], [5, 5])
            self.assertIn(r["pick"], [k for k, n in r["battles"].items() if n == 5])  # the bot's pick kept

    def test_node_selection(self):
        node = Node(3, prior_logits([0.6, 0.58, 0.4], 0, 3, 0.02, 0.1), [0.6, 0.58, 0.4])
        self.assertEqual(node.select((True, True, True), 0.5, 1.0, pick=0), 0)  # unvisited: the bot's pick
        for _ in range(6):
            node.update(0, 0.1)  # the pick keeps losing
        self.assertNotEqual(node.select((True, True, True), 0.5, 1.0, pick=0), 0)
        self.assertIn(node.select((True, False, True), 0.5, 1.0, pick=0), (0, 2))  # only legal options
        for _ in range(30):
            node.update(2, 0.9)  # the third option, once tried, wins
        self.assertEqual(node.select((True, False, True), 0.5, 1.0, pick=0), 2)

    def test_settings(self):
        self.assertIs(engine_class("tree"), TreeEngine)
        self.assertEqual(setting("tree_heads", "throw+swap"), ("throw", "swap"))
        self.assertEqual(setting("depth", "2"), 2)
        self.assertTrue(setting("adversary", "1"))
        with self.assertRaises(ValueError):
            setting("root", "deep")
        import engine_versus
        spec = engine_versus.parse("website,engine=tree,depth=2,root=sh,gumbel=1")
        self.assertEqual((spec["engine"], spec["depth"], spec["root"], spec["gumbel"]), ("tree", 2, "sh", 1.0))
        self.assertTrue({"engine", "depth", "root"} <= KEYS)
        with self.assertRaises(ValueError):
            self.engine(adversary=True, opponents="mix")

    def test_pilot(self):
        import engine_versus
        engine_versus._state.update(gd=self.gd, pool=self.pool, net=self.net, evals={}, pools={})

        class Live(RealTime):
            pass

        unhurried = engine_versus.pilot(engine_versus.parse("website,engine=tree,depth=2"), 5)
        self.assertIsInstance(unhurried, TreeEngine)
        self.assertEqual((unhurried.depth, unhurried.turn_ms), (2, 1e9))
        live = engine_versus.pilot(engine_versus.parse("website,engine=tree,fix_stay=1"), 5, cls=Live)
        self.assertIsInstance(live, TreeEngine)
        self.assertIsInstance(live, Live)
        self.assertTrue(live.fix_stay)
        self.assertLess(live.turn_ms, 1e9)  # a RealTime subclass keeps the game's pauses
        plain = engine_versus.pilot(engine_versus.parse("website"), 5, cls=Live)
        self.assertNotIsInstance(plain, TreeEngine)
        self.assertLess(plain.turn_ms, 1e9)


if __name__ == "__main__":
    unittest.main()
