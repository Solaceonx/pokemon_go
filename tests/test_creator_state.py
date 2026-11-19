import sys
from pathlib import Path
import unittest
import tempfile
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_state import reconcile_looks, reconcile_creator_state, confirmed_empty_cache, recover_cached_faints
from vod_media import sha256
import creator_impact
import creator_lifecycle
from pogo.gamedata import GameData
from pogo.tracker import Tracker, Observation


class SourceClock(unittest.TestCase):
    def zero_samples(self):
        return [{'t': 1+i/15, 'bar': {'bounds': [182, 500, 334, 514], 'live_pixels': 0,
                'outline_method': 'edge_contour'} if i < 10 else None} for i in range(50)]

    def test_isolated_fade_pixel_is_retained_but_real_live_return_refutes_zero(self):
        samples = self.zero_samples()
        samples[12]['bar'] = {'bounds': [182, 500, 334, 514], 'live_pixels': 1, 'outline_method': 'edge_contour'}
        proof = confirmed_empty_cache(samples, 1)
        self.assertEqual(proof['first_zero']['t'], 1)
        self.assertEqual(len(proof['isolated_fade_pixel_samples']), 1)
        samples[13]['bar'] = dict(samples[12]['bar'])
        self.assertIsNone(confirmed_empty_cache(samples, 1))

    def test_centered_zero_needs_fresh_replacement_and_pinned_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = root/'tracking-raw'; raw.mkdir()
            (root/'battle.json').write_text(json.dumps({'video_sha256': 'source'}))
            (raw/'center-impact-000.json').write_text(json.dumps({'fingerprint': {
                'video': 'source', 'code': sha256(creator_impact.__file__), 'announcement_seconds': 0},
                'samples': self.zero_samples()}))
            timeline = {'clip_origin_seconds': 0, 'field': {'theirs': [
                {'t': 0, 'name': 'Cramorant', 'header_seen_clip_seconds': 0}]}}
            evidence = {'faints': [], 'charged_impact_probes': [{'side': 'theirs', 'species': 'Cramorant',
                        'move': 'Icy Wind', 'announced_clip_seconds': 0}]}
            self.assertFalse(recover_cached_faints(raw, timeline, evidence)[0])
            timeline['field']['theirs'].append({'t': 10, 'name': 'Piloswine', 'header_seen_clip_seconds': 10})
            recovered, _ = recover_cached_faints(raw, timeline, evidence)
            self.assertEqual(recovered[0]['clip_seconds'], 1)
            (root/'battle.json').write_text(json.dumps({'video_sha256': 'different-source'}))
            self.assertFalse(recover_cached_faints(raw, timeline, evidence)[0])

    def test_fast_zero_needs_known_identity_and_independent_last_member_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = root/'tracking-raw'; raw.mkdir()
            (root/'battle.json').write_text(json.dumps({'video_sha256': 'source'}))
            (raw/'fighting-faint-000.json').write_text(json.dumps({'fingerprint': {
                'video': 'source', 'code': sha256(creator_lifecycle.__file__),
                'candidate': {'side': 'mine', 'species': 'Fearow', 't': 1}}, 'samples': self.zero_samples()}))
            timeline = {'clip_origin_seconds': 0, 'field': {'mine': [
                {'t': 0, 'name': 'Fearow', 'header_seen_clip_seconds': 0}]}, 'left': {'mine': [[0, 2]]}}
            evidence = {'faints': [], 'charged_impact_probes': []}
            self.assertFalse(recover_cached_faints(raw, timeline, evidence)[0])
            timeline['left']['mine'] = [[0, 1]]
            recovered, _ = recover_cached_faints(raw, timeline, evidence)
            self.assertEqual(recovered[0]['species'], 'Fearow')
            timeline['field']['mine'] = []
            self.assertFalse(recover_cached_faints(raw, timeline, evidence)[0])

    def test_unidentified_zero_never_kills_the_model_assumed_active(self):
        looks = [{'t': 0, 'my_species': 'Kingdra'},
                 {'t': 9, 'foe_species': None, 'foe_hp': 0, 'foe_fainted': True},
                 {'t': 12, 'foe_species': 'Araquanid'}]
        evidence = {'faints': [{'side': 'theirs', 'species': None, 'clip_seconds': 9}],
                    'quarantined_counters': []}
        fixed, audit = reconcile_looks(looks, self.timeline(), evidence)
        self.assertEqual([r['t'] for r in fixed], [0, 12])
        self.assertFalse(audit['source_waits'])
        self.assertEqual(len(audit['unattributed_zero_candidates']), 1)

    def test_receipt_digests_survive_windows_and_unix_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            receipts = []
            for newline in ['\n', '\r\n']:
                (game/'timeline.json').write_bytes(json.dumps(self.timeline(), indent=2).replace('\n', newline).encode())
                (game/'creator-lifecycle.json').write_bytes(json.dumps({'faints': [], 'quarantined_counters': []}, indent=2).replace('\n', newline).encode())
                (game/'observations.jsonl').write_bytes((json.dumps({'t': 0})+newline+json.dumps({'t': 2})+newline).encode())
                receipts.append(reconcile_creator_state(game))
            for key in ['observations_before_canonical_sha256', 'observations_after_canonical_sha256', 'lifecycle_canonical_sha256']:
                self.assertEqual(receipts[0][key], receipts[1][key])

    def timeline(self):
        return {'clip_origin_seconds': 0, 'end': 20, 'waits': [],
                'field': {'mine': [{'t': 0, 'name': 'Kingdra', 'header_seen_clip_seconds': 0},
                                   {'t': 12, 'name': 'Turtonator', 'header_seen_clip_seconds': 12}],
                          'theirs': [{'t': 0, 'name': 'Araquanid', 'header_seen_clip_seconds': 0}]}}

    def test_incoming_charge_and_zero_are_one_look_without_fast_credit(self):
        looks = [{'t': 0, 'my_species': 'kingdra', 'foe_species': 'araquanid'},
                 {'t': 9, 'my_species': 'kingdra', 'my_hp': 0, 'my_fainted': True},
                 {'t': 10, 'my_species': 'kingdra', 'foe_charged': True, 'foe_move': 'MIRROR_COAT'}]
        evidence = {'faints': [{'side': 'mine', 'species': 'Kingdra', 'clip_seconds': 9}],
                    'quarantined_counters': []}
        fixed, audit = reconcile_looks(looks, self.timeline(), evidence)
        self.assertEqual(len(fixed), 2)
        self.assertEqual(fixed[1]['t'], 9)
        self.assertTrue(fixed[1]['my_fainted'])
        self.assertTrue(fixed[1]['foe_charged'])
        gd = GameData()
        t = Tracker(gd, [gd.default('kingdra'), gd.default('turtonator')])
        for look in fixed:
            t.update(Observation(**look))
        self.assertEqual(t.turn, 0)  # no nine seconds of invented fast moves
        self.assertEqual(t.me.team[0].hp, 0)
        self.assertEqual(len(audit['merged_impacts']), 1)

    def test_false_counter_wait_is_removed_and_real_wait_redistributed(self):
        timeline = self.timeline()
        timeline['waits'] = [[3, 8]]
        looks = [{'t': 0}, {'t': 6, 'paused': 3}, {'t': 10, 'paused': 2}, {'t': 12}]
        evidence = {'faints': [{'side': 'mine', 'species': 'Kingdra', 'clip_seconds': 9}],
                    'quarantined_counters': [{'side': 'mine', 'clip_seconds': 3}]}
        fixed, audit = reconcile_looks(looks, timeline, evidence)
        self.assertNotIn('paused', fixed[1])
        self.assertEqual(fixed[2]['paused'], 1)
        self.assertEqual(fixed[3]['paused'], 2)
        self.assertEqual(audit['quarantined_waits_removed'][0]['interval'], [3, 8])

    def test_double_ko_wait_is_a_union_not_two_pauses(self):
        timeline = self.timeline()
        timeline['field']['theirs'].append({'t': 12, 'name': 'Ninetales', 'header_seen_clip_seconds': 12})
        evidence = {'faints': [{'side': s, 'species': n, 'clip_seconds': 9} for s, n in
                              [('mine', 'Kingdra'), ('theirs', 'Araquanid')]], 'quarantined_counters': []}
        fixed, _ = reconcile_looks([{'t': 9}, {'t': 12}], timeline, evidence)
        self.assertEqual(fixed[1]['paused'], 3)

    def test_empty_party_needs_three_distinct_measured_victims(self):
        timeline = self.timeline()
        timeline['field']['mine'].append({'t': 15, 'name': 'Victreebel', 'header_seen_clip_seconds': 15})
        deaths = [{'side': 'mine', 'species': n, 'clip_seconds': t} for t, n in
                  [(9, 'Kingdra'), (14, 'Turtonator'), (18, 'Victreebel')]]
        looks = [{'t': 0, 'my_left': 3}, {'t': 18, 'my_left': 1}, {'t': 20, 'my_left': 1}]
        incomplete, _ = reconcile_looks(looks, timeline, {'faints': deaths[:2], 'quarantined_counters': []})
        self.assertEqual(incomplete[-1]['my_left'], 1)
        fixed, audit = reconcile_looks(looks, timeline, {'faints': deaths, 'quarantined_counters': []})
        self.assertEqual(fixed[0]['my_left'], 3)
        self.assertEqual(fixed[-1]['my_left'], 0)
        self.assertEqual(len(audit['terminal_zero_from_three_measured_victims']), 1)


if __name__ == '__main__':
    unittest.main()
