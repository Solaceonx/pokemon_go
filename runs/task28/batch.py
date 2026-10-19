"""Resume task 28's independent-player comparison, confirmation, and timing.

Every child command is recorded verbatim in commands.txt. No source or model is
changed here. Large resumable checkpoints remain local; score vectors and their
summaries are saved as small JSON files alongside this script.
"""
from pathlib import Path
import hashlib
import json
import math
import shlex
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs/task28'
PYTHON = '/Users/marco/Developer/pokemon_go/.venv/bin/python'
SPECS = ['opponents=mix', 'opponents=mix,profile=1', 'unseen=teams',
         'opponents=mix,profile=1,unseen=teams',
         'opponents=mix,profile=1,unseen=teams,style_file=runs/task28/opponent_styles-human.json',
         'opponents=mix,profile=1,unseen=teams,team_file=data/teams_v2.json']


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def score(values):
    return dict(mean=statistics.mean(values),
                margin95=1.96 * math.sqrt(statistics.variance(values) / len(values)), n=len(values))


def values(data, kind, spec):
    rows = data['results'][kind][spec]
    assert sorted(map(int, rows)) == list(range(len(rows)))
    return [rows[str(n)] for n in range(len(rows))]


def summary(tag, specs, counts, baseline=''):
    source = ROOT / 'runs/engine_versus' / (tag + '.json')
    data = json.loads(source.read_text())
    assert data['baseline'] == baseline
    result = dict(tag=tag, seed=data['seed'], baseline=baseline, candidates={}, scores={}, quarter_points={})
    for kind, by_spec in data['results'].items():
        result['scores'][kind] = {}
        result['quarter_points'][kind] = {}
        for spec in by_spec:
            v = values(data, kind, spec)
            assert len(v) == counts[kind]
            result['scores'][kind][spec] = score(v)
            result['quarter_points'][kind][spec] = ''.join(str(round(4*x)) for x in v)
    for spec in specs:
        h2h = score(values(data, 'h2h', spec))
        changes = {}
        for kind in ('crowd', 'pvpoke'):
            if counts.get(kind):
                a, b = values(data, kind, spec), values(data, kind, baseline)
                changes[kind] = score([x-y for x,y in zip(a,b)])
        result['candidates'][spec] = dict(h2h=h2h, changes=changes,
            eligible=h2h['mean']+h2h['margin95'] >= 0.5,
            selection_score=min((s['mean']-s['margin95'] for s in changes.values()), default=0))
    if SPECS[3] in specs:
        result['extensions_vs_original_combination'] = {}
        for spec in specs[4:]:
            result['extensions_vs_original_combination'][spec] = {
                kind: score([x-y for x,y in zip(values(data,kind,spec),values(data,kind,SPECS[3]))])
                for kind in ('crowd','pvpoke')}
    write(tag + '-summary.json', result)
    return result


def check_inputs(frozen):
    for path, expected in frozen.items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == expected, path


def run(args, log, frozen):
    check_inputs(frozen)
    command = ['nice', '-n', '10', PYTHON, *args]
    with (OUT / 'commands.txt').open('a') as notes:
        notes.write('\n' + shlex.join(command) + ' > runs/task28/' + log + ' 2>&1\n')
    print('Starting ' + log + ': ' + shlex.join(command), flush=True)
    with (OUT/log).open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    check_inputs(frozen)
    print('Completed ' + log, flush=True)


def main():
    paths = list(json.loads((OUT/'extension-inputs.json').read_text())['hashes'])
    paths += ['scripts/realtime_trial.py', 'runs/task28/batch.py']
    hashes = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    manifest = OUT/'isolated-inputs.json'
    if manifest.exists():
        assert json.loads(manifest.read_text())['hashes'] == hashes, 'Inputs changed; do not resume these tags.'
    else:
        write(manifest.name, dict(workers=3, seed=2701, candidates=SPECS, hashes=hashes,
            rule='No head-to-head loss beyond its 95% margin; maximize the smaller lower 95% bound for paired crowd/PvPoke improvement.',
            correction='Each player receives an independent evaluator matchup cache. Only network weights are shared.'))
    common = ['--workers','3','--pairings','2000','--crowd','2000','--pvpoke','1000']
    run(['scripts/engine_versus.py','--tag','opponents-isolated',*common,'--seed','2701',
         '--candidates',*SPECS], 'isolated.out', hashes)
    grid = summary('opponents-isolated', SPECS, dict(h2h=2000,crowd=2000,pvpoke=1000))
    eligible = [s for s in SPECS if grid['candidates'][s]['eligible']]
    chosen = max(eligible or SPECS, key=lambda s:grid['candidates'][s]['selection_score'])
    selection = dict(spec=chosen, source_tag=grid['tag'], source_seed=grid['seed'],
                     stats=grid['candidates'][chosen], rule=json.loads(manifest.read_text())['rule'])
    selection_path = OUT/'selection.json'
    if selection_path.exists():
        assert json.loads(selection_path.read_text()) == selection
    else:
        write(selection_path.name, selection)
    print('Frozen candidate: ' + chosen, flush=True)
    run(['scripts/engine_versus.py','--tag','opponents-confirm',*common,'--seed','280281',
         '--candidates',chosen], 'confirmation.out', hashes)
    confirmed = summary('opponents-confirm', [chosen], dict(h2h=2000,crowd=2000,pvpoke=1000))
    candidate = confirmed['candidates'][chosen]
    passes = candidate['eligible'] and all(v['mean']>v['margin95'] for v in candidate['changes'].values())
    write('verdict.json',dict(spec=chosen,passes_strength_criteria=passes,statistics=candidate))
    run(['scripts/realtime_trial.py','--timing','300','--workers','3','--seed','280282',
         '--settings',chosen,'--save','runs/task28/timing.json'], 'timing.out', hashes)
    run(['scripts/engine_versus.py','--tag','opponents-bot-confirm','--baseline','bot','--workers','3',
         '--pairings','1000','--crowd','0','--pvpoke','0','--seed','280283','--candidates','',chosen],
        'bot-confirmation.out', hashes)
    bot = summary('opponents-bot-confirm', ['',chosen], dict(h2h=1000,crowd=0,pvpoke=0), baseline='bot')
    data = json.loads((ROOT/'runs/engine_versus/opponents-bot-confirm.json').read_text())
    bot['paired_change_vs_old_engine'] = score([x-y for x,y in zip(values(data,'h2h',chosen),values(data,'h2h',''))])
    write('opponents-bot-confirm-summary.json', bot)
    print('All measurements complete; strength criteria: ' + str(passes), flush=True)


if __name__ == '__main__':
    main()
