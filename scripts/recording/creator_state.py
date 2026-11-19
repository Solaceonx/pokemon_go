"""Keep source-timed faint observations coherent with the battle clock.

This consumes typed pixel evidence only. It neither finds new faints nor reads
reference labels. Charged impacts and their measured victim zero are one look;
faint waits are intervals, so a simultaneous double KO cannot pause twice.
"""
import json
import hashlib
from creator_impact import _rows
from vod_media import sha256, write_json


def confirmed_empty_cache(samples, after):
    """Complete zero rectangles plus fade, ignoring isolated fade speckles.

    A sustained live return always refutes zero. A single one/two-pixel sample
    during fade is retained explicitly as noise evidence, never erased from the
    original pixel cache. Callers must supply independent target confirmation.
    """
    from creator_impact import same_bar
    for i, point in enumerate(samples):
        bar, t = point.get('bar'), point['t']
        if t < after or not bar or bar['outline_method'] != 'edge_contour' or bar['live_pixels']:
            continue
        zeros = [s for s in samples[i+1:] if 0 < s['t']-t <= .3 and s.get('bar')
                 and s['bar']['outline_method'] == 'edge_contour' and s['bar']['live_pixels'] == 0
                 and same_bar(bar['bounds'], s['bar']['bounds'])]
        if len(zeros) < 2 or zeros[-1]['t']-t < .1:
            continue
        tail = [s for s in samples[i+1:] if t < s['t'] <= t+2]
        if not tail or tail[-1]['t'] < t+1.5:
            continue
        live = [s for s in tail if s.get('bar') and s['bar']['live_pixels'] > 0]
        if any(s['bar']['live_pixels'] > 2 for s in live):
            continue
        if any(0 < b['t']-a['t'] <= .15 for a, b in zip(live, live[1:])):
            continue
        missing = [s for s in tail if s['t'] >= t+.5 and s.get('bar') is None]
        if len(missing) >= 3 and missing[-1]['t']-missing[0]['t'] >= .2:
            return {'first_zero': point, 'confirmed_zero': zeros[1],
                    'isolated_fade_pixel_samples': live, 'missing_tail_samples': len(missing)}
    return None


def recover_cached_faints(raw, timeline, evidence):
    """Use already pinned native measurements for two conservative fallbacks.

    A centered empty target followed by a fresh replacement header can establish
    a nonterminal KO despite an unreadable party counter. An ordinary complete
    empty bar for an independently observed last party member can establish a
    fast KO despite a gap before the drain. Neither consumes a result screen.
    """
    import creator_impact
    import creator_lifecycle
    meta = json.loads((raw.parent/'battle.json').read_text(encoding='utf-8'))
    origin = timeline['clip_origin_seconds']
    recovered, proofs = [], []
    for path in sorted(list(raw.glob('center-impact-*.json'))+list(raw.glob('fighting-faint-*.json'))):
        cache = json.loads(path.read_text(encoding='utf-8'))
        fp = cache.get('fingerprint', {})
        centered = path.name.startswith('center-impact-')
        expected_code = sha256(creator_impact.__file__ if centered else creator_lifecycle.__file__)
        if fp.get('video') != meta['video_sha256'] or fp.get('code') != expected_code:
            continue
        if centered:
            probe = next((p for p in evidence['charged_impact_probes']
                          if p.get('announced_clip_seconds') == fp.get('announcement_seconds')
                          and p.get('species') and p.get('move')), None)
            if not probe:
                continue
            side, name = probe['side'], probe['species']
            after = probe['announced_clip_seconds']+1
        else:
            candidate = fp.get('candidate', {})
            side, name = candidate.get('side'), candidate.get('species')
            if not side or not name:
                continue
            before = [value for when, value in timeline['left'][side]
                      if when <= candidate['t']-origin]
            if not before or before[-1] != 1:
                continue
            after = candidate['t']-2
        if any(d['side'] == side and d['species'] == name for d in evidence['faints']+recovered):
            continue
        measurement = confirmed_empty_cache(cache['samples'], after)
        if not measurement:
            continue
        at = measurement['first_zero']['t']
        if creator_lifecycle.active(timeline, side, at) != name:
            continue
        replacements = [f for f in timeline['field'][side] if f['name'] != name
                        and at < f.get('header_seen_clip_seconds', -1) <= at+20]
        if centered and not replacements:
            continue
        method = 'complete_center_zero_then_fresh_replacement_header' if centered else 'complete_last_member_zero_and_fade'
        death = {'side': side, 'species': name, 'clip_seconds': at,
                 'confirmed_clip_seconds': measurement['confirmed_zero']['t'],
                 'method': method, 'timing_uncertainty_seconds': .1}
        recovered.append(death)
        proofs.append({'faint': death, 'cache_file': path.name, 'cache_sha256': sha256(path),
                       'acquisition_fingerprint': fp, 'measurement': measurement,
                       'replacement_header_clip_seconds': min(f['header_seen_clip_seconds'] for f in replacements) if replacements else None})
    return recovered, proofs


def overlap(intervals, start, end):
    return sum(max(0, min(end, b)-max(start, a)) for a, b in intervals)


def union(intervals):
    result = []
    for a, b in sorted(intervals):
        if b <= a:
            continue
        if result and a <= result[-1][1]:
            result[-1][1] = max(result[-1][1], b)
        else:
            result.append([a, b])
    return result


def reconcile_looks(looks, timeline, evidence):
    """Return corrected observations and an explicit record of every change."""
    looks = [dict(r) for r in looks]
    origin = timeline['clip_origin_seconds']
    original_waits = timeline.get('waits', [])
    audit = {'merged_impacts': [], 'quarantined_waits_removed': [],
             'source_waits': [], 'terminal_zero_from_three_measured_victims': [],
             'unattributed_zero_candidates': [d for d in evidence['faints'] if not d.get('species')],
             'unattributed_observations_removed': []}
    evidence = {**evidence, 'faints': [d for d in evidence['faints'] if d.get('species')]}
    for r in list(looks):
        unknown = False
        for prefix in ['my', 'foe']:
            if r.get(prefix+'_fainted') and not r.get(prefix+'_species'):
                unknown = True
                for key in [prefix+'_fainted', prefix+'_species', prefix+'_hp']:
                    r.pop(key, None)
        if unknown:
            audit['unattributed_observations_removed'].append(r['t'])
            if set(r) <= {'t', 'note'}:
                looks.remove(r)
    # Non-faint looks came from assembly. Preserve an additional charged pause
    # if a prior adapter measured a longer gap than the usual ten seconds.
    extras, previous = {}, 0
    for r in sorted((r for r in looks if not r.get('my_fainted') and not r.get('foe_fainted')),
                    key=lambda r: r['t']):
        residual = r.get('paused', 0)-overlap(original_waits, previous, r['t'])
        if residual > .05 and (r.get('my_charged') is not None or r.get('foe_charged')):
            extras[id(r)] = residual
        previous = r['t']
    # A faint sampled shortly before its incoming charge's resolution must not
    # advance nine seconds of fast fighting and debit the charge one look later.
    for death in list(looks):
        for prefix, incoming in [('my', 'foe_charged'), ('foe', 'my_charged')]:
            if not death.get(prefix+'_fainted'):
                continue
            candidates = [r for r in looks if r is not death and r.get(incoming) is not None
                          and r.get(incoming) is not False and 0 <= r['t']-death['t'] <= 3]
            if not candidates:
                continue
            charge = min(candidates, key=lambda r: r['t'])
            audit['merged_impacts'].append({'victim_side': prefix,
                'species': death.get(prefix+'_species'), 'charged_look_before': charge['t'],
                'measured_zero_seconds': death['t']})
            charge['t'] = death['t']
            charge.update({k: v for k, v in death.items() if k.startswith(prefix+'_')})
            death.pop(prefix+'_fainted', None)
            if not death.get('my_fainted') and not death.get('foe_fainted'):
                looks.remove(death)
    retained = []
    for a, b in original_waits:
        contradicted = [q for q in evidence.get('quarantined_counters', [])
                        if abs(a-(q['clip_seconds']-origin)) <= 1]
        if contradicted:
            audit['quarantined_waits_removed'].append({'interval': [a, b],
                                                      'counter_sides': [q['side'] for q in contradicted]})
        else:
            retained.append([a, b])
    for d in evidence['faints']:
        start = d['clip_seconds']-origin
        next_headers = [f['header_seen_clip_seconds']-origin for f in timeline['field'][d['side']]
                        if f['name'] != d['species'] and f.get('header_seen_clip_seconds', -1) > d['clip_seconds']]
        end = min(next_headers) if next_headers else timeline['end']
        audit['source_waits'].append({'side': d['side'], 'species': d['species'],
                                      'interval': [max(0, start), end]})
    waits = union(retained+[d['interval'] for d in audit['source_waits']])
    # Three distinct observed victims establish an empty party without using a
    # result screen or trusting an earlier broken party counter.
    for side, prefix in [('mine', 'my'), ('theirs', 'foe')]:
        roster = {f['name'] for f in timeline['field'][side]}
        dead = {}
        for d in evidence['faints']:
            if d['side'] == side and d['species'] in roster:
                dead[d['species']] = min(dead.get(d['species'], float('inf')), d['clip_seconds']-origin)
        if len(roster) != 3 or set(dead) != roster:
            continue
        at = max(dead.values())
        for r in looks:
            if r['t'] >= at-1e-5:
                r[prefix+'_left'] = 0
        audit['terminal_zero_from_three_measured_victims'].append({'side': side, 't': at,
                                                                  'species': sorted(dead)})
    looks.sort(key=lambda r: r['t'])
    previous = looks[0]['t'] if looks else 0
    for r in looks:
        paused = overlap(waits, previous, r['t'])+extras.get(id(r), 0)
        r.pop('paused', None)
        if paused > .001:
            r['paused'] = round(paused, 6)
        previous = r['t']
    audit['merged_wait_intervals'] = waits
    return looks, audit


def reconcile_creator_state(game, raw=None):
    evidence_path = game/'creator-lifecycle.json'
    if not evidence_path.exists():
        return None
    path = game/'observations.jsonl'
    source_looks = _rows(path)
    def digest_rows(values):
        return hashlib.sha256(''.join(json.dumps(v, sort_keys=True, ensure_ascii=False,
                                  separators=(',', ':'))+'\n' for v in values).encode('utf-8')).hexdigest()
    before = digest_rows(source_looks)
    timeline = json.loads((game/'timeline.json').read_text(encoding='utf-8'))
    original_evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    evidence = {**original_evidence, 'faints': list(original_evidence['faints'])}
    recovered, recovery_proofs = recover_cached_faints(raw, timeline, evidence) if raw is not None else ([], [])
    for d in recovered:
        prefix = 'my' if d['side'] == 'mine' else 'foe'
        name = d['species']
        if prefix == 'my':
            name = next((f['resolved_species'] for f in evidence['forms'] if f['header_species'] == name), name)
        source_looks.append({'t': round(d['clip_seconds']-timeline['clip_origin_seconds'], 6),
                            prefix+'_species': name, prefix+'_hp': 0, prefix+'_fainted': True,
                            'note': 'complete cached native zero with independent target confirmation'})
    evidence['faints'] += recovered
    terminal_path = game/'terminal-impact.json'
    terminal = json.loads(terminal_path.read_text(encoding='utf-8')) if terminal_path.exists() else {}
    if terminal.get('accepted'):
        at = terminal['measurement']['first_zero']['t']
        if not any(d['side'] == terminal['side'] and d['species'] == terminal['species']
                   and abs(d['clip_seconds']-at) < 3 for d in evidence['faints']):
            evidence['faints'].append({'side': terminal['side'], 'species': terminal['species'], 'clip_seconds': at})
    looks, audit = reconcile_looks(source_looks, timeline, evidence)
    if audit['unattributed_zero_candidates'] or recovered:
        original_evidence = {**original_evidence,
            'faints': [d for d in original_evidence['faints'] if d.get('species')]+recovered,
            'unattributed_zero_candidates': original_evidence.get('unattributed_zero_candidates', [])+
                                            audit['unattributed_zero_candidates']}
        write_json(evidence_path, original_evidence)
    audit['cached_zero_recovery'] = recovery_proofs
    path.write_bytes(''.join(json.dumps(r)+'\n' for r in looks).encode('utf-8'))
    audit.update(schema='creator-state-reconciliation-v1', code_sha256=sha256(__file__),
                 observations_before_canonical_sha256=before, observations_after_canonical_sha256=digest_rows(looks),
                 lifecycle_canonical_sha256=hashlib.sha256(json.dumps(original_evidence, sort_keys=True,
                     ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest(),
                 terminal_impact_accepted=terminal.get('accepted', False),
                 digest_method='SHA256 of compact sorted-key UTF-8 JSON; observations have one LF after each row',
                 result_based_faints=0)
    write_json(game/'creator-state-reconciliation.json', audit)
    return audit
