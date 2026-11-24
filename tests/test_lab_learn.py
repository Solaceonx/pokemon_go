"""Engine lab, lab-learn: learned policies, the piKL bot, the engine with a learned imagined opponent, population training."""
import json
import random
import sys
import unittest
from pathlib import Path

import numpy as np

from pogo.battle import CHARGED, FAST, SWITCH, Battle
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData
from pogo.lab.engines import ModelledEngine
from pogo.lab.policy import POLICY_HEADS, PolicyNet, PolicyPlayer
from pogo.learner import Learner, QNet
from pogo.realtime import RealTime

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "scripts" / "lab")]
GD = GameData()
Q = QNet.load(ROOT / "runs" / "general-decide" / "q.npz")


def played(a, b, seed=7, teams_seed=3):
    rng = random.Random(teams_seed)
    pool = GD.meta(50)
    battle = Battle(rng.sample(pool, 3), rng.sample(pool, 3), a, b, seed=seed, record=True)
    battle.run()
    return battle.winner, [list(e) for e in battle.log]


class Policy(unittest.TestCase):
    def test_fit_learns_a_rule_and_survives_saving(self):
        rng = np.random.default_rng(0)
        x = rng.normal(size=(3000, 6))
        target = (x[:, 0] > 0).astype(int)
        mask = np.ones((3000, 2), bool)
        net = PolicyNet.new(inputs=6, hidden=8, heads={"shield": 2})
        net.fit("shield", x, mask, target, epochs=30, batch=128, rate=1e-2, decay=0.0)
        p = net.probabilities("shield", x, mask)
        self.assertGreater((p.argmax(axis=1) == target).mean(), 0.95)
        path = ROOT / "runs" / "lab-learn" / "_test_policy.npz"
        try:
            net.save(path, note="test")
            again = PolicyNet.load(path)
            self.assertTrue(np.allclose(again.probabilities("shield", x, mask), p))
            self.assertEqual(again.meta["note"], "test")
        finally:
            path.unlink(missing_ok=True)

    def test_illegal_options_get_no_probability(self):
        net = PolicyNet.new(inputs=45, seed=1)
        p = net.probabilities("throw", np.ones(45), np.array([True, False, True]))
        self.assertEqual(p[1], 0.0)
        self.assertAlmostEqual(p.sum(), 1.0)

    def test_pikl_with_lam_zero_plays_as_the_trained_bot(self):
        anchor = PolicyNet.new(inputs=48, seed=2, bot_input=True)
        for seed in (7, 8):
            bot = played(Learner(q=Q, margin=0.02, seed=1), Learner(q=Q, margin=0.02, seed=2), seed=seed)
            pikl = played(PolicyPlayer(anchor=anchor, lam=0.0, q=Q, margin=0.02, seed=1), Learner(q=Q, margin=0.02, seed=2),
                          seed=seed)
            self.assertEqual(bot, pikl)

    def test_a_large_lam_follows_the_anchor(self):
        anchor = PolicyNet.new(inputs=48, seed=3, bot_input=True)
        for head in POLICY_HEADS:  # an anchor that always prefers the last legal option, overwhelmingly
            anchor.params[head][3][:] = np.arange(POLICY_HEADS[head]) * 50.0
        player = PolicyPlayer(anchor=anchor, lam=1.0, q=Q, margin=0.02, seed=1)
        played(player, Learner(q=Q, margin=0.02, seed=2))
        self.assertGreater(player.off_bot, 0)

    def test_a_sampled_policy_is_repeatable_and_its_clones_agree(self):
        net = PolicyNet.new(inputs=48, seed=4, bot_input=True)
        first = played(PolicyPlayer(pnet=net, q=Q, sample=True, seed=5), Learner(q=Q, margin=0.02, seed=6))
        again = played(PolicyPlayer(pnet=net, q=Q, sample=True, seed=5), Learner(q=Q, margin=0.02, seed=6))
        self.assertEqual(first, again)
        # a clone part way through finishes the battle exactly as the original does
        rng = random.Random(3)
        pool = GD.meta(50)
        me, them = PolicyPlayer(pnet=net, q=Q, sample=True, seed=5), Learner(q=Q, margin=0.02, seed=6)
        battle = Battle(rng.sample(pool, 3), rng.sample(pool, 3), me, them, seed=7)
        for _ in range(60):
            battle.step()
        twin = battle.clone(me.clone(), them.clone())
        self.assertEqual(battle.run(), twin.run())


class Engines(unittest.TestCase):
    def test_opp_q_equal_to_q_plays_as_the_engine(self):
        model = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz").model
        pool = GD.meta(50)
        kw = dict(rollout="bot", samples=2, horizon=6, edge=0.03, q=Q, margin=0.02, seed=9, turn_ms=1e9,
                  unforeseen_ms=1e9, after_charged_ms=1e9, after_faint_ms=1e9, replace_ms=1e9, start_ms=1e9)
        plain = played(RealTime(Evaluator(model), pool, **kw), Learner(q=Q, margin=0.02, seed=2), seed=11)
        modelled = played(ModelledEngine(Evaluator(model), pool, opp_q=Q, **kw), Learner(q=Q, margin=0.02, seed=2), seed=11)
        self.assertEqual(plain, modelled)

    def test_the_imagined_opponent_is_the_model(self):
        model = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz").model
        net = PolicyNet.new(inputs=48, seed=4, bot_input=True)
        engine = ModelledEngine(Evaluator(model), GD.meta(50), rollout="bot", q=Q, opp_policy=net)
        them = engine._imagined_opponent(random.Random(1))
        self.assertIsInstance(them, PolicyPlayer)
        self.assertTrue(them.sample)
        self.assertIs(them.pnet, net)


class Versus(unittest.TestCase):
    def test_default_specs_unchanged_and_lab_keys_parsed(self):
        import engine_versus as V
        self.assertIsNone(V.parse("bot"))
        self.assertEqual(V.parse("bot,q=runs/general-decide/q.npz,margin=0.05"),
                         {"_bot": True, "q": "runs/general-decide/q.npz", "margin": 0.05})
        spec = V.parse("website,opp_policy=runs/x.npz,opp_sample=0,opp_q=runs/general-decide/q.npz")
        self.assertEqual((spec["opp_policy"], spec["opp_sample"], spec["opp_q"]), ("runs/x.npz", False, "runs/general-decide/q.npz"))
        V.setup("standard")
        self.assertIs(type(V.pilot(None, 1)), Learner)
        self.assertIs(type(V.pilot(V.parse("bot,q=runs/general-decide/q.npz"), 1)), PolicyPlayer)
        engine = V.pilot(V.parse("website,opp_q=runs/general-decide/q.npz"), 1)
        self.assertIsInstance(engine, ModelledEngine)
        self.assertIs(type(V.pilot(V.parse("website"), 1)), RealTime)


class OwnerGames(unittest.TestCase):
    def test_labels(self):
        import fit_policy as F
        acts = {10: CHARGED[1], 12: SWITCH[2], 30: CHARGED[0], 33: SWITCH[1]}
        row = {"turn": 10, "active": 0, "head": "throw"}
        self.assertEqual(F.label(row, acts, 6), 2)
        self.assertEqual(F.label({**row, "turn": 11}, acts, 6), 0)
        self.assertIsNone(F.label({**row, "turn": 12}, acts, 6))
        swap = {"turn": 8, "active": 0, "head": "swap"}
        self.assertEqual(F.label(swap, acts, 6), 0)  # a charged move before any switch: stayed
        self.assertEqual(F.label({**swap, "turn": 11}, acts, 6), 2)  # switched to slot 2: the second of the others
        self.assertEqual(F.label({**swap, "turn": 31}, acts, 6), 1)
        self.assertEqual(F.label({**swap, "turn": 20}, acts, 6), 0)
        self.assertEqual(F.label({"turn": 5, "active": 1, "head": "replace", "answer_slot": 2}, acts, 6), 1)
        self.assertEqual(F.label({"turn": 5, "active": 1, "head": "shield", "answer": 1}, acts, 6), 1)

    def test_watching_does_not_change_the_game(self):
        import fit_policy as F
        from pogo.review import Logged, Replay
        game = json.loads((ROOT / "runs" / "people" / "owner_games.jsonl").read_text(encoding="utf-8").splitlines()[0])
        teams = [[GD.build(sid, mv, level=lv, ivs=tuple(iv)) for sid, mv, lv, iv in t] for t in game["teams"]]
        watched = F.Watched(Replay(game["my_choices"]), Learner(q=Q, margin=0.02, log=[], mid_swap=False, seed=0))
        battle = Battle(teams[0], teams[1], watched, Logged(game["log"]), seed=game["seed"], record=True)
        battle.run()
        self.assertEqual([list(e) for e in battle.log], [list(e) for e in game["log"]])
        heads = {r["head"] for r in watched.rows}
        self.assertTrue({"throw", "shield"} <= heads)
        self.assertTrue(all(("answer" in r) == (r["head"] == "shield") for r in watched.rows))


class Population(unittest.TestCase):
    def test_weights_and_every_kind_of_opponent(self):
        import train_population as T
        self.assertEqual(T.weights_from("rulebook=1,people=0.5")["people"], 0.5)
        with self.assertRaises(SystemExit):
            T.weights_from("nobody=1")
        pool = GD.meta(50)
        for kind in ("rulebook", "past", "people", "engine"):
            config = {"weights": T.weights_from(f"{kind}=1"), "population": [T.SHIPPED], "imitation": T.OWNER_POLICY,
                      "engine_samples": 2}
            opponent = T.population_crowd(config, pool)(random.Random(1))
            self.assertTrue(hasattr(opponent, "act") and hasattr(opponent, "clone"))
        people = T.population_crowd({**config, "weights": T.weights_from("people=1")}, pool)(random.Random(2))
        self.assertIsNotNone(people.people)


if __name__ == "__main__":
    unittest.main()
