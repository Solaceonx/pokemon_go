"""Small training-only diagnostic of sensitivity to equivalent bench-slot labels; no strength claim."""
import os
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
from pathlib import Path
import hashlib
import json
import random
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.arena import low_priority
from pogo.dqn import Agent, Network
from pogo.counterfactual import StepRecorder
from pogo.dqn_symmetry import permute, action_order, SymmetricPolicy
from scripts.double_dqn import frozen, draw_split, sha, write_json


def main():
    low_priority()
    path = ROOT / 'runs/double-dqn/refine-v3/policy.npz'
    net, _, _ = Network.load(path)
    f, rng, calls = frozen(), random.Random(38401), []
    for _ in range(8):
        teams = [draw_split(f.mixed_draw, rng, 'train') for _ in range(2)]
        players = [StepRecorder(Agent(net, seed=rng.getrandbits(32))) for _ in range(2)]
        battle = f.modules['battle'].Battle(*teams, *players, seed=rng.getrandbits(32))
        battle.run()
        calls.extend(call for player in players for call in player.calls if call['mask'].sum() > 1)
    calls = rng.sample(calls, min(256, len(calls)))
    x, mask = np.stack([c['x'] for c in calls]), np.stack([c['mask'] for c in calls])
    vote = np.where(mask, net.predict(x), -np.inf).argmax(axis=1)
    variants = {}
    for ours, foes in ((True, False), (False, True), (True, True)):
        px, pm, _ = permute(x, mask, vote, ours, foes)
        changed = action_order(ours)[np.where(pm, net.predict(px), -np.inf).argmax(axis=1)]
        variants[f'ours={ours},foes={foes}'] = {
            'different': int(np.count_nonzero(changed != vote)), 'count': len(vote),
            'by_kind': {kind: {'count': sum(c['kind'] == kind for c in calls),
                'different': int(sum(c['kind'] == kind and a != b for c, a, b in zip(calls, changed, vote)))}
                for kind in ('act', 'shield', 'replace')}}
    invariant = np.where(mask, SymmetricPolicy(net).predict(x), -np.inf).argmax(axis=1)
    report = {'diagnostic_only': True, 'strength_evidence': False, 'split': 'train', 'seed': 38401,
        'games': 8, 'states': len(calls), 'policy_sha256': sha(path),
        'input_sha256': hashlib.sha256(x.tobytes() + mask.tobytes()).hexdigest(),
        'variants': variants, 'averaged_policy_changed': int(np.count_nonzero(invariant != vote))}
    out = ROOT / 'runs/double-dqn/symmetry-v5'
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / 'training_audit.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
