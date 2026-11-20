"""Keep visible source records when the assumed Great League model cannot run."""
import hashlib
import json
import shutil


def support(timeline, team, gd):
    ranked = {p['speciesId'] for p in gd.rankings(1500)}
    names = {p['speciesName']: sid for sid, p in gd.species.items()}
    observed = {p['species'] for p in team.get('pokemon', [])}
    observed.update(p['name'] for fields in timeline.get('field', {}).values() for p in fields)
    missing = sorted(name for name in observed if name in names and names[name] not in ranked)
    # Ranking absence is a model limitation, not a source identity rejection.
    return dict(status='unavailable' if missing else 'available',
        league_cp=1500, unranked_visible_species=missing,
        source_observations_usable=True, model_accuracy_verified=False)


def unavailable(game, availability):
    """Preserve old model artifacts before replacing them with explicit unknowns."""
    names = ['states.jsonl', 'states.jsonl.gz', 'events.jsonl', 'events.jsonl.gz',
             'state.json', 'track.json', 'track.log']
    prior = {name: (game/name).read_bytes() for name in names if (game/name).exists()}
    if prior:
        digest = hashlib.sha256(b''.join(name.encode()+b'\0'+raw for name, raw in sorted(prior.items()))).hexdigest()
        archive = game/'model-history'/digest
        archive.mkdir(parents=True, exist_ok=True)
        for name, raw in prior.items():
            target = archive/name
            if target.exists() and target.read_bytes() != raw:
                raise ValueError('Prior model archive differs')
            if not target.exists():
                shutil.copy2(game/name, target)
    for name in ('states.jsonl', 'events.jsonl'):
        (game/name).write_bytes(b'')
    for name, value in [('state.json', {'model_status': 'unavailable'}),
                        ('track.json', {'model_status': 'unavailable', 'looks': 0, 'rejected': 0,
                                        'unexplained': None}), ('model-support.json', availability)]:
        (game/name).write_text(json.dumps(value, indent=2)+'\n', encoding='utf8')
    return dict(verdict='fail', failed=['model: visible species or rules unsupported by the Great League model'],
        notes=['Source observations and events retained; no model states, assumed HP, energy or moves substituted.'],
        model_support=availability, blind_energy_check={'status': 'unavailable'})
