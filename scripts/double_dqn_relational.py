"""Run the unchanged Double DQN trainer with the shared matchup encoder instead of the flat MLP.

This entrypoint is research-only: evaluation uses validation compositions. A measured winning candidate
would need its own method-preserving final evaluator/canary; this entrypoint cannot open final teams.
Backend selection is local to this process and restored on return, including errors.
"""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.dqn_relational import Network, ARCHITECTURE
from scripts import double_dqn as trainer


@contextmanager
def relational_backend():
    previous = trainer.Network, trainer.ALGORITHM
    trainer.Network = Network
    trainer.ALGORITHM = ('Double DQN with ' + ARCHITECTURE + '; replay/returns/margin settings in training_settings.json')
    try:
        yield
    finally:
        trainer.Network, trainer.ALGORITHM = previous


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--split', choices=['validation'], default='validation')
    parser.add_argument('--run', required=not any(x in sys.argv for x in ('-h', '--help')))
    args, _ = parser.parse_known_args()
    if (ROOT / 'runs/double-dqn/final_test_lock.json').exists():
        raise ValueError('Production evidence is locked; no more research on these final teams')
    if args.run is not None:
        if Path(args.run).name != args.run or args.run in ('.', '..'):
            raise ValueError('Use a simple fresh run directory name')
        run = ROOT / 'runs/double-dqn' / args.run
        receipt = run / 'network_backend.json'
        identity = {'architecture': ARCHITECTURE, 'final_teams_enabled': False,
            'source_sha256': {str(p.relative_to(ROOT)): trainer.sha(p) for p in
                (Path(__file__), ROOT / 'pogo/dqn_relational.py', ROOT / 'pogo/dqn.py',
                 ROOT / 'scripts/double_dqn.py')}}
        if receipt.exists():
            import json
            if json.loads(receipt.read_text()) != identity:
                raise ValueError('Backend source changed; preserve the old run and use a fresh name')
        elif (run / 'bootstrap.npz').exists() or (run / 'resume.json').exists():
            raise ValueError('Existing checkpoints have no matching backend receipt; use a fresh name')
        run.mkdir(parents=True, exist_ok=True)
        trainer.write_json(receipt, identity)
    with relational_backend():
        trainer.main()


if __name__ == '__main__':
    main()
