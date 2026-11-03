import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from pogo.agents import Planner
from pogo.battle import Battle
from pogo.dqn import Replay
from pogo.dqn_relational import Network
from pogo.gamedata import GameData
from pogo.teamlist import drawer
from scripts import dqn_continue as trial, dqn_final as final, double_dqn as trainer


class StandInFrozen:
    def __init__(self):
        gd = GameData()
        self.pool = gd.meta(15)
        self.mixed_draw = self.standard_draw = drawer(gd, self.pool)
        self.samples, self.games = [], 0

    def engine(self, seed, samples):
        self.samples.append(samples)
        return Planner(seed=seed)

    def game(self, a, b, p, q, seed, side=0):
        args = (a, b, p, q) if side == 0 else (b, a, q, p)
        game = Battle(*args, seed=seed)
        winner = game.run()
        self.games += 1
        return (0. if winner == -1 else 1. if winner == side else -1.), game


class ContinuationTests(unittest.TestCase):
    def test_exclusions_cover_permutations_and_old_game_seeds_and_restore_on_failure(self):
        blocked, accepted = ['a','b','c'], ['d','e','f']
        self.assertEqual(trial.team_key(blocked), trial.team_key(list(reversed(blocked))))
        original_random, original_draw = final.random, final.draw_split
        rng = random.Random(123)
        forbidden, expected = rng.getrandbits(32), rng.getrandbits(32)
        with patch.object(final, 'draw_split', side_effect=[blocked, accepted]):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                with trial.fresh_evaluation({trial.team_key(blocked)}, {forbidden}):
                    fresh = final.random.Random(123)
                    self.assertEqual(fresh.getrandbits(32), expected)
                    self.assertEqual(final.draw_split(None, fresh, 'test'), accepted)
                    raise RuntimeError('interrupted')
        self.assertIs(final.random, original_random)
        self.assertIs(final.draw_split, original_draw)

    def test_only_complete_pairings_survive_and_changed_resume_identity_is_rejected(self):
        net = Network(seed=123, hidden=8)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            whole, resumed = root/'whole', root/'resumed'
            whole.mkdir(); resumed.mkdir()
            whole_f, resumed_f = StandInFrozen(), StandInFrozen()
            with trial.fresh_evaluation(set(), {13}):
                complete = final.measure(whole, whole_f, net, [], trial.RECIPE,
                                         'mixed', 901, 2, 'validation', lambda: False)
                calls = 0
                def stop_after_one_pair():
                    nonlocal calls
                    calls += 1
                    return calls > 2
                with self.assertRaises(TimeoutError):
                    final.measure(resumed, resumed_f, net, [], trial.RECIPE,
                                  'mixed', 901, 2, 'validation', stop_after_one_pair)
                self.assertEqual(len(trainer.read_rows(resumed/'rows_mixed_901.jsonl')), 1)
                restored = final.measure(resumed, resumed_f, net, [], trial.RECIPE,
                                        'mixed', 901, 2, 'validation', lambda: False)
                self.assertEqual(complete['pair_scores'], restored['pair_scores'])
                self.assertEqual(whole_f.games, resumed_f.games)
                self.assertEqual(resumed_f.samples, [32]*4)
                path = resumed/'rows_mixed_901.jsonl'
                rows = trainer.read_rows(path)
                rows[0]['game_seeds'][0] += 1
                path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
                with self.assertRaises(ValueError):
                    final.measure(resumed, resumed_f, net, [], trial.RECIPE,
                                  'mixed', 901, 2, 'validation', lambda: False)
                self.assertEqual(resumed_f.games, 4)

    def test_full_state_continues_learning_without_resetting_or_modifying_source(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            source, run = root/'runs/double-dqn/source', root/'new'
            source.mkdir(parents=True); run.mkdir()
            net = Network(seed=7, hidden=8)
            target = copy.deepcopy(net)
            for p in target.p: p += .01
            for m in net.m: m.fill(.001)
            for v in net.v: v.fill(.001)
            net.steps = 7
            rng = np.random.default_rng(19)
            meta = dict(games=9, batches=3, seed=77, numpy_rng=rng.bit_generator.state,
                        train_seconds=0., best_validation=.6, snapshot=0)
            net.save(source/'endpoint.npz', meta, target)
            replay = Replay(capacity=16)
            replay.size = 4
            replay.mask[:4,0] = True
            replay.next_mask[:4,0] = True
            replay.mc[:4] = 1.
            replay.priority[:4] = 1.
            replay.save(source/'replay_0.npz')
            replay.save(source/'demonstrations.npz')
            trainer.write_json(source/'resume.json', {'slot':0})
            identity = {name:trainer.sha(source/name) for name in
                        ('endpoint.npz','replay_0.npz','demonstrations.npz','resume.json')}
            plan = dict(source_run='source', source_sha256=identity)
            with patch.object(trial, 'ROOT', root):
                trial.seed_run(run, plan)
                restored, info, restored_target = Network.load(run/'latest_0.npz')
                self.assertEqual(restored.steps, 7)
                self.assertEqual(info['numpy_rng'], meta['numpy_rng'])
                for a,b in zip(restored.m+restored.v, net.m+net.v): np.testing.assert_array_equal(a,b)
                for a,b in zip(restored_target.p, target.p): np.testing.assert_array_equal(a,b)
                trainer.write_json(run/'selection.json', dict(checkpoint='initial.npz', validation={'score':.6}))
                args = SimpleNamespace(seed=77,hours=.001,batch=4,engine_share=1,train_samples=32,
                    nstep=3,epsilon=.03,epsilon_min=.005,epsilon_decay=20000,mc_share=.25,
                    demo_margin=1,rate=.0001,updates=1,target_every=500,save_every=25,
                    eval_every=10**9,validation_pairs=64,validation_samples=32)
                f = StandInFrozen()
                with patch.object(trainer,'frozen',return_value=f), trial.relational_backend(), \
                     patch.object(trainer.time,'monotonic',side_effect=[0.,0.,0.,9999.,9999.]):
                    trainer.train(args,run)
                slot = json.loads((run/'resume.json').read_text())['slot']
                learned, info, retained_target = Network.load(run/f'latest_{slot}.npz')
                self.assertEqual((info['games'],info['batches'],learned.steps),(10,4,9))
                self.assertFalse(all(np.array_equal(a,b) for a,b in zip(net.p,learned.p)))
                for a,b in zip(retained_target.p,target.p): np.testing.assert_array_equal(a,b)
                self.assertNotEqual(info['numpy_rng'],meta['numpy_rng'])
                for name,digest in identity.items(): self.assertEqual(trainer.sha(source/name),digest)
                net.p[-1][0] += 1
                net.save(source/'endpoint.npz')
                with self.assertRaisesRegex(ValueError,'input changed'):
                    trial.seed_run(run,plan)

    def test_recovery_never_restarts_stage_or_overall_allocation(self):
        stage={'deadline_unix':200.}
        plan={'research_cutoff_unix':4000.,'absolute_deadline_unix':5000.}
        self.assertEqual(trial.remaining_stage(stage,plan,120.),80.)
        self.assertEqual(trial.remaining_stage(stage,plan,201.),0.)
        plan['research_cutoff_unix']=3750.
        self.assertEqual(trial.remaining_stage(stage,plan,120.),30.)
        plan['absolute_deadline_unix']=140.
        self.assertEqual(trial.remaining_stage(stage,plan,120.),20.)

    def test_real_second_process_cannot_acquire_worker_lease(self):
        code = ('import sys\nfrom pathlib import Path\nfrom scripts.dqn_continue import worker_lease\n'
                'try:\n with worker_lease(Path(sys.argv[1])): print("acquired")\n'
                'except OSError: sys.exit(17)\n')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'worker.lock'
            with trial.worker_lease(path):
                denied = subprocess.run([sys.executable,'-c',code,str(path)], capture_output=True)
                self.assertEqual(denied.returncode,17,denied.stderr)
                self.assertNotIn(b'acquired',denied.stdout)
            allowed = subprocess.run([sys.executable,'-c',code,str(path)], capture_output=True)
            self.assertEqual(allowed.returncode,0,allowed.stderr)
            self.assertIn(b'acquired',allowed.stdout)


if __name__ == '__main__':
    unittest.main()
