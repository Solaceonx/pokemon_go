"""A new game and its evaluation display cannot reuse another player's matchup cache."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import play
from pvpbot_site import play_api
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData


class GameEvaluators(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.pool = cls.gd.meta(50)
        cls.mine = ["altaria", "umbreon", "jellicent"]
        cls.theirs = ["melmetal", "stunfisk", "medicham"]

    def warm_separate_views(self, battle, display, prototype):
        engine = battle.agents[1].evaluator
        self.assertIsNot(engine, display)
        self.assertIsNot(engine, prototype)
        self.assertIsNot(display, prototype)
        engine.features(battle.views[1])
        self.assertTrue(engine._agent._outlooks)
        self.assertFalse(display._agent._outlooks)
        display.features(battle.views[0])
        self.assertTrue(display._agent._outlooks)
        self.assertFalse(prototype._agent._outlooks)
        return engine, display

    def test_local_new_game_keeps_bot_and_display_caches_private(self):
        server = object.__new__(play.Server)
        server.gd, server.pool, server.net, server.lineup_net = self.gd, self.pool, None, None
        server.evaluator, server.game = Evaluator(), None
        server.team = lambda names: [self.gd.default(name) for name in names]
        server.args = SimpleNamespace(team=self.mine, foe=self.theirs, bot="engine", slow=1.0,
                                      charged_pause=4.0, my_charged_pause=4.0, eval_bar=True)
        with patch.object(play.threading.Thread, "start"), patch.object(play.random, "getrandbits", return_value=29):
            server.new()
            old_engine, old_display = self.warm_separate_views(server.game.battle, server.game.evaluator,
                                                              server.evaluator)
            server.new()
        engine, display = server.game.battle.agents[1].evaluator, server.game.evaluator
        self.assertIsNot(engine, old_engine)
        self.assertIsNot(display, old_display)
        self.assertFalse(engine._agent._outlooks)
        self.assertFalse(display._agent._outlooks)

    def test_site_new_game_keeps_bot_and_display_caches_private(self):
        prototype = Evaluator()
        job = json.dumps(dict(mine=self.mine, theirs=self.theirs, owned=False, bot="engine", tick_ms=500))
        with patch.dict(play_api._s, dict(gd=self.gd, pool=self.pool, net=None, ev=prototype, owned={}), clear=True), \
                patch.object(play_api.random, "getrandbits", return_value=29):
            play_api.new(job)
            s = play_api._s
            old_engine, old_display = self.warm_separate_views(s["battle"], s["view_ev"], prototype)
            play_api.new(job)
            self.assertIsNot(s["bot"].evaluator, old_engine)
            self.assertIsNot(s["view_ev"], old_display)
            self.assertFalse(s["bot"].evaluator._agent._outlooks)
            self.assertFalse(s["view_ev"]._agent._outlooks)


if __name__ == "__main__":
    unittest.main()
