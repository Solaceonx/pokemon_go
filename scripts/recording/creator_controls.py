"""Causal interpretation of saved disc measurements and visible move labels."""
from collections import deque
from creator_energy import intersect_buttons


class ControlEvidence:
    def __init__(self):
        self.labels = {}
        self.runs = {}
        self.discs = deque(maxlen=2)
        self.last_identity = None

    def update(self, sample, identity):
        t = sample['t']
        if identity != self.last_identity:
            self.discs.clear()
        self.last_identity = identity
        for label in sample['labels']:
            if identity is None:
                continue
            key = (identity, label['id'])
            previous = self.runs.get(key)
            same = previous and previous['name'] == label['name'] and 0 < t-previous['last'] <= 3
            run = {'name': label['name'], 'first': previous['first'] if same else t,
                   'last': t, 'count': previous['count']+1 if same else 1}
            self.runs[key] = run
            if run['count'] >= 2:
                self.labels[key] = {**label, 'confirmed_at_seconds': t,
                                    'first_visible_seconds': run['first']}
        discs = sample['controls']['discs']
        eligible = len(discs) == 2 and all(d['status'] == 'observed' for d in discs)
        if not eligible or (self.discs and t-self.discs[-1]['t'] > .25):
            self.discs.clear()
        if eligible:
            self.discs.append({'t': t, 'discs': discs})
        # One-turn moves land every half second; requiring a third sample at
        # 6 Hz misses short plateaus between the liquid-fill animations.
        settled = len(self.discs) == 2 and all(
            max(r['discs'][i]['measurement']['fill'] for r in self.discs)-
            min(r['discs'][i]['measurement']['fill'] for r in self.discs) <= .035
            for i in range(2))
        buttons, constraints = [], []
        for d in discs:
            known = self.labels.get((identity, d['id']))
            buttons.append({'id': d['id'], 'kind': 'charge', 'visible': True,
                'move': known['name'] if known else None,
                'identity_status': 'observed' if known and known['confirmed_at_seconds'] == t else 'retained' if known else 'unknown',
                'identity_observed_at_seconds': known['confirmed_at_seconds'] if known else None,
                'visually_enabled': d['ready'], 'tap_normalized': [d['center'][0]/508, d['center'][1]/1080],
                'disc_measurement': d['measurement'], 'settled': settled,
                'evidence': {'method': 'paired_physical_circles', 'observed_at_seconds': t}})
            constraints.append({'observed': settled and d['status'] == 'observed' and known is not None,
                'cost': known['cost'] if known else None, 'fill': d['measurement']['fill'], 'ready': d['ready']})
        constraint = intersect_buttons(constraints, uncertainty=.08)
        constraint.update(observed_at_seconds=t, identity=identity,
                          method='settled_discs_and_causally_confirmed_move_labels', accuracy_verified=False)
        return buttons, constraint
