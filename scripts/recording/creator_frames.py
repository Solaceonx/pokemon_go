"""Adapt native measurements for the evidence viewer, preserving source time."""
import copy
import bisect
from creator_health import rows
from creator_observations import interpret_measurements, health_owners


def native_fighting_scene(assigned, control_sample, at, headers=None):
    """Two physical side bars, corroborated by fresh controls or both headers.

    Charged close-ups show one camera bar. Normal battle-camera geometry does
    not depend on the text reader successfully naming the scene or buttons.
    """
    sidebars=all(assigned[s] and not assigned[s].get('camera_owner_basis') for s in ['mine','theirs'])
    buttons=bool(control_sample and 0<=at-control_sample['t']<=.25
        and len(control_sample['controls']['discs'])==2
        and all(d['status']=='observed' for d in control_sample['controls']['discs']))
    panels=bool(headers and all(headers[s].get('panels') for s in ['mine','theirs']))
    return bool(sidebars and (buttons or panels))


def measured_frames(raw, timeline, lifecycle=None):
    native, _ = interpret_measurements(rows(raw/'native-health-12hz.jsonl.gz'))
    rich, slim = rows(raw/'screen-refined.jsonl.gz'), rows(raw/'readings-refined.jsonl.gz')
    from creator_controls import ControlEvidence
    interpreter = ControlEvidence()
    from creator_identity import confirmed_identities, enrich_frame, entry_announcements
    identity_path = raw/'native-identities-3hz.jsonl.gz'
    identity_samples=rows(identity_path) if identity_path.exists() else []
    identities = confirmed_identities(identity_samples,entry_announcements(raw)) if identity_samples else []
    identity_times = [r['t'] for r in identities]
    controls = rows(raw/'native-controls-6hz.jsonl.gz') if (raw/'native-controls-6hz.jsonl.gz').exists() else []
    labels_path = raw/'native-direct-labels-1hz.jsonl.gz'
    if labels_path.exists():
        labels = {round(r['t'],6): r['labels'] for r in rows(labels_path)}
        for c in controls:
            supplemental = labels.get(round(c['t'],6), [])
            if supplemental:
                combined = c['labels'] + [{**v,'observed_at_seconds':c['t']} for v in supplemental]
                unique = []
                for button in ['charge_0','charge_1']:
                    found = [v for v in combined if v['id'] == button]
                    if len({v['name'] for v in found}) == 1:
                        unique.append(max(found,key=lambda v:v['confidence']))
                c['labels'] = unique
    context_by_index = {r['frame_index']: r for r in rich}
    control_index = -1
    control_buttons, constraint = [], None
    if len(rich) != len(slim):
        raise ValueError('Rich/slim source lengths differ')
    index = -1
    pending = sorted((lifecycle or {}).get('faints', []),
                     key=lambda d: d.get('confirmed_clip_seconds', d['clip_seconds']))
    death_index = 0
    for sample in native:
        while index+1 < len(slim) and slim[index+1]['t'] <= sample['t']+1e-6:
            index += 1
        if index < 0:
            continue
        frame, reading = copy.deepcopy(rich[index]), copy.deepcopy(slim[index])
        identity_index = bisect.bisect_right(identity_times, sample['t']+1e-6)-1
        if identity_index >= 0 and sample['t']-identity_times[identity_index] <= .75:
            enrich_frame(frame, identities[identity_index]['values'])
            for side,visible_side in [('mine','mine'),('theirs','opponent')]:
                candidate=identity_samples[identity_index].get(side)
                if candidate:
                    frame[visible_side]['identity_candidate']={**candidate,'observed_at_seconds':identity_times[identity_index]}
        original_time = reading['t']
        fresh = abs(original_time-sample['t']) < 1e-5
        frame.update(timestamp_seconds=sample['t'], frame_index=sample['frame_index'],
                     source_context_seconds=original_time,
                     native_source={'pts': sample['source_pts'], 'time_base': sample['source_time_base']})
        reading.update(t=sample['t'], buttons_observed_at_seconds=original_time)
        frame['source_faints'] = []
        while death_index < len(pending):
            d = pending[death_index]
            if d.get('confirmed_clip_seconds', d['clip_seconds']) > sample['t']:
                break
            frame['source_faints'].append({**d, 'side': 'opponent' if d['side'] == 'theirs' else 'mine'})
            death_index += 1
        if not fresh:
            frame['text_observation']['fresh_this_frame'] = False
            for button in frame['buttons']:
                if button.get('identity_status') == 'observed':
                    button['identity_status'] = 'stale'
        assigned = health_owners(sample, timeline)
        for side, visible_side, short in [('mine', 'mine', 'm'), ('theirs', 'opponent', 'o')]:
            visible, bar = frame[visible_side], assigned[side]
            for field, native_field in [('pokemon_left', 'party'), ('shields_left', 'shields')]:
                counted = sample['headers'][side][native_field]
                visible[field] = {**counted, 'evidence': {'method': 'native_header_glyphs',
                    'observed_at_seconds': sample['t'], 'frame_index': sample['frame_index']}}
            visible['health_bar'] = {'value': bar, 'status': 'observed' if bar else 'unknown',
                'evidence': {'method': 'native_live_pixels', 'observed_at_seconds': sample['t']}}
            visible['health_estimate'] = {'status': 'unknown', 'reason': 'No attributable physical bar in this frame'}
            reading[short]['live_hp_fraction'] = bar['fraction'] if bar else None
            if bar:
                species, cp = visible['species'].get('value'), visible['cp'].get('value')
                visible['health_estimate'] = {'status': 'estimated',
                    'fraction_range': bar['fraction_interval'], 'maximum_hp': None,
                    'integer_hp_range': None,
                    'identity': f'{visible_side}:{species}:{cp}' if species and cp is not None else None,
                    'method': 'native_live_pixels', 'camera_owner_basis': bar.get('camera_owner_basis'),
                    'camera_species': bar.get('camera_species'),
                    'camera_identity_cutoff_seconds': bar.get('camera_identity_cutoff_seconds'),
                    'observed_at_seconds': sample['t'], 'accuracy_verified': False}
        while control_index+1 < len(controls) and controls[control_index+1]['t'] <= sample['t']+1e-6:
            control_index += 1
            c = controls[control_index]
            context = copy.deepcopy(context_by_index.get(c['context_frame_index'], {}))
            current_identity = bisect.bisect_right(identity_times, c['t']+1e-6)-1
            if current_identity >= 0 and c['t']-identity_times[current_identity] <= .75:
                enrich_frame(context, identities[current_identity]['values'])
            source = context.get('mine', {})
            name, cp = source.get('species', {}), source.get('cp', {})
            seen = name.get('evidence', {}).get('observed_at_seconds')
            identity = (f"{name['value']}:{cp['value']}" if name.get('value') and cp.get('value') is not None
                        and seen is not None and 0 <= c['t']-seen <= .75 else None)
            control_buttons, constraint = interpreter.update(c, identity)
        if control_index >= 0:
            frame['buttons'] = copy.deepcopy(control_buttons)
            for button in frame['buttons']:
                if controls[control_index]['t'] < sample['t']-1e-5 and button['identity_status'] == 'observed':
                    button['identity_status'] = 'retained'
            frame['charge_controls_constraint'] = constraint
            current_control=controls[control_index]
            if (0<=sample['t']-current_control['t']<=.25 and current_control['controls']['status']=='observed'):
                frame['charge_label_candidates']=[dict(name=label['name'],observed_at_seconds=current_control['t'])
                    for label in current_control['labels']]
        frame['normal_fighting_evidence']={'supported':native_fighting_scene(
            assigned,controls[control_index] if control_index>=0 else None,sample['t'],sample['headers']),
            'method':'two_physical_side_bars_with_paired_controls_or_header_geometry',
            'observed_at_seconds':sample['t']}
        yield frame, reading
