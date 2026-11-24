"""Tree, mixed, learned-opponent and tactic settings compose without changing defaults."""
import hashlib
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

import numpy as np

from pogo.agents import Planner
from pogo.battle import Battle, CHARGED, FAST, SWITCH
from pogo.engine import _FirstShield
from pogo.lab.people import PeopleLike
from pogo.lab.policy import PolicyNet, PolicyPlayer
from pogo.lab.tree import TreeEngine, TreeLearner, bot_values
from pogo.realtime import RealTime
from scripts import engine_versus as ev

ROOT = Path(__file__).resolve().parents[1]
A = 'website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh'
B = A + ',shield_mix=0'
C = B + ',finish_safe=1'
D = C + ',shield_two=0.05,shield_one=0'
E = D + ',swap_after_throw=1'


class BestLab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ev.setup()
        cls.gd, cls.pool = ev._state['gd'], ev._state['pool']

    def position(self, spec=E, mine='swampert', foe='azumarill', shields=(2, 2)):
        player = ev.pilot(ev.parse(spec), 51)
        teams = [[self.gd.default(s) for s in (lead, 'altaria', 'umbreon')] for lead in (mine, foe)]
        battle = Battle(*teams, player, Planner(seed=52), seed=53, shields=shields)
        battle.sides[0].mon.energy = 100
        return player, battle, battle.views[0]

    def test_combined_spec_builds_tree_with_every_key(self):
        p = ev.pilot(ev.parse(E), 1)
        self.assertIsInstance(p, TreeEngine)
        self.assertEqual((p.depth, p.root, p.fix_stay, p.fix_judged), (3, 'sh', True, True))
        self.assertEqual((p.shield_mix, p.finish_safe, p.shield_two, p.shield_one, p.swap_after_throw),
                         (0, True, .05, 0, True))
        self.assertEqual((p.samples, p.horizon, p.edge, p.margin), (32, 20, .03, .02))
        self.assertIn('shield', p.heads)
        self.assertEqual(p.turn_ms, 1e9)

    def test_tree_keeps_learned_opponents_and_live_deadlines(self):
        class Live(RealTime):
            pass

        spec = E + ',opp_q=runs/general-decide/q.npz,opp_policy=unused,opp_sample=0'
        net = PolicyNet.new(inputs=45, seed=7)
        with patch('pogo.lab.policy.cached', return_value=net):
            for cls in (RealTime, Live):
                p = ev.pilot(ev.parse(spec), 1, cls=cls)
                self.assertIsInstance(p, TreeEngine)
                self.assertIsInstance(p, cls)
                foe = p._imagined_opponent(random.Random(1))
                self.assertIsInstance(foe, PolicyPlayer)
                self.assertIs(foe.pnet, net)
                self.assertFalse(foe.sample)
                self.assertEqual(p.turn_ms == 1e9, cls is RealTime)
        p = ev.pilot(ev.parse(E + ',opponents=people,opp_q=runs/general-decide/q.npz'), 1)
        self.assertIsInstance(p._imagined_opponent(random.Random(1)), PeopleLike)

    def test_hypothetical_shield_advice_does_not_search_or_draw(self):
        p, _, v = self.position()
        p._decision_depth = 1
        dice = p.rng.getstate(), p._mix_rng.getstate()
        with patch.object(p, '_halving', side_effect=AssertionError('searched hypothetical shield')):
            p.shield(v, 100)
        self.assertEqual(p.looks, 0)
        self.assertEqual((p.rng.getstate(), p._mix_rng.getstate()), dice)

    def test_shield_search_and_state_margins_affect_root_pick_and_prior(self):
        p, b, v = self.position()
        p.samples, p.horizon = 1, 1
        for shields, expected, margin in ((2, True, .05), (1, False, 0)):
            b.sides[0].shields = shields
            with patch.object(p.q, 'values', return_value=np.array([.53, .5])), \
                    patch.object(Planner, 'shield', return_value=True), \
                    patch.object(p, '_look', return_value=.5), \
                    patch.object(p, '_halving', wraps=p._halving) as search:
                self.assertEqual(p.shield(v, 100), expected)
                self.assertEqual(bot_values(p, 'shield', v, (True, True), 1)[0], int(expected))
                self.assertAlmostEqual(search.call_args.args[4][1], (.5 + margin) / p.prior_temp)
            self.assertEqual(p.last['head'], 'shield')
            self.assertEqual(p.last_shield_probability, 1)
        self.assertEqual(p.looks, 2)
        # A clear search win still overrules the bot's state-specific advice.
        with patch.object(p, '_look', side_effect=lambda v, h, k, s: float(k)):
            self.assertTrue(p.shield(v, 100))

    def test_last_pokemon_rule_survives_combination(self):
        p, _, v = self.position()
        for mon in v.me.team[1:]:
            mon.hp = 0
        with patch.object(p, '_search_decision', side_effect=AssertionError('searched final shield')):
            self.assertTrue(p.shield(v, 100))

    def test_finish_safe_reaches_tree_throw_search(self):
        for safe in (0, 1):
            p, b, v = self.position(B + f',finish_safe={safe}', 'empoleon', 'diggersby', (0, 0))
            v.me.mon.hp, v.me.mon.energy = 62, 48
            v.foe.hp, v.foe.energy, b.sides[1].busy = 4, 100, 1
            self.assertEqual(p._pick_move(v), CHARGED[0] if safe else FAST)
            self.assertEqual(p.looks, safe)
            if safe:
                self.assertEqual(p.last['head'], 'throw')

    def test_swap_after_throw_fires_for_both_search_heads_and_reconsiders(self):
        for judged in (False, True):
            for enabled in (False, True):
                p, b, v = self.position(D + f',swap_after_throw={int(enabled)}', shields=(2, 0))
                p.samples, p.horizon, p.sac, p.fast_first = 1, 1, False, 0
                b.turn, v.foe.energy = 10, 100
                if judged:
                    p.mid_swap_search = 'ready'
                    p._judged = (v.me.active, v.foe.build.uid)
                with patch.object(p, '_look', side_effect=lambda v, h, k, s: float(k == 1)):
                    self.assertEqual(p.act(v), CHARGED[1] if enabled else SWITCH[1])
                    self.assertEqual(p.last['head'], 'mid_swap' if judged else 'swap')
                    self.assertEqual(p.swap_after_throws, int(enabled))
                    if enabled:
                        self.assertIsNone(p._judged)
                        self.assertEqual(p.act(v), SWITCH[1])
                        self.assertEqual(p.swap_after_throws, 1)

    def test_mid_swap_looks_keep_stay_and_judged_fixes(self):
        for stay in (0, 1):
            for judged in (0, 1):
                spec = f'website,engine=tree,depth=3,root=sh,fix_stay={stay},fix_judged={judged},mid_swap_search=ready'
                p, _, v = self.position(spec)
                p.samples = 1
                pair = (v.me.active, v.foe.build.uid)
                p._judged, p._foe_settled = pair, True
                seen = []

                def play(battle, view, head, option, others, rng):
                    us, them = battle.agents
                    ours = us.inner
                    seen.append((option, ours._judged, them._judged, us.act(battle.views[0])))
                    return .5

                with patch.object(p, '_play', side_effect=play), \
                        patch.object(TreeLearner, '_pick_switch', return_value=SWITCH[1]), \
                        patch.object(TreeLearner, '_pick_move', return_value=FAST):
                    p._decide('mid_swap', v, (True, True, True), lambda: 1)
                    # Direct look calls also carry the same fixes without an active tree.
                    if stay or judged:
                        p._look(v, 'mid_swap', 0, 7)
                for option, our_judgement, their_judgement, action in seen:
                    self.assertEqual(our_judgement, pair if judged else None)
                    self.assertEqual(their_judgement is not None, bool(judged))
                    if option == 0:
                        self.assertEqual(action, FAST if stay else SWITCH[1])

    def test_bait_and_mixed_throw_controls_reach_tree(self):
        for mix in (0, 1):
            p, _, v = self.position(E + f',bait_mix={mix}')
            p.force('throw', 2)
            self.assertEqual(p._pick_move(v), CHARGED[0] if mix else CHARGED[1])
            self.assertEqual(p.bait_opportunities, 1)
        p, _, v = self.position(E + ',throw_mix=.1,shield_floor=.1')
        p.samples = 1
        with patch.object(p, '_look', return_value=.5):
            p._decide('throw', v, (True, True, True), lambda: 0)
            self.assertTrue(0 < p.last_throw_probability < 1)
            p.shield(v, 100)
            self.assertTrue(0 < p.last_shield_probability < 1)

    def test_equilibrium_tree_looks_honor_fixed_shield_columns(self):
        p, _, v = self.position(E + ',equilibrium=1')
        p.samples = 1
        columns = []

        def play(battle, view, head, option, others, rng):
            foe = battle.agents[1]
            if isinstance(foe, _FirstShield):
                columns.append(foe.shielded)
            return .5

        with patch.object(p, '_play', side_effect=play):
            p._decide('throw', v, (False, True, True), lambda: 1)
        self.assertIn(True, columns)
        self.assertIn(False, columns)

    def test_choice_controls_only_touch_their_own_heads(self):
        for setting, head in (('no_tell_bait=1', 'swap'), ('switch_edge=.5', 'throw')):
            p, _, v = self.position(A + ',' + setting)
            with patch.object(p, '_look', return_value=.5), \
                    patch.object(p, '_choose_worth', side_effect=AssertionError('unrelated choice control')):
                p._decide(head, v, (True, True, True), lambda: 0)

    def test_tactics_off_keep_existing_tree_games(self):
        rows = json.loads((ROOT / 'runs/lab-best/tree-before.json').read_text())
        for row in rows:
            for off in ('', ',finish_safe=0,bait_mix=off,shield_two=off,shield_one=off,swap_after_throw=0'):
                seed, spec = row['seed'], row['spec'] + off
                rng = random.Random(seed)
                p = ev.pilot(ev.parse(spec), seed + 1)
                b = Battle(rng.sample(self.pool, 3), rng.sample(self.pool, 3), p,
                           ev.pilot(None, seed + 2), seed=seed, record=True)
                winner = b.run()
                payload = json.dumps([winner, b.turn, b.log, b.hits], ensure_ascii=True, separators=(',', ':'))
                self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(), row['sha256'])


if __name__ == '__main__':
    unittest.main()
