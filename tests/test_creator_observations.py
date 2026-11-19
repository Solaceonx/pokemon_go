import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_observations import classify_headers, stable_counter_runs, health_owners, reconcile_source_shields, shield_readbacks
from creator_energy import intersect_buttons, legal_transition


class SourceCounters(unittest.TestCase):
    def panel(self, offset=0, mine=True):
        colors = ['red', 'red', 'dark', 'purple', 'dark']
        positions = [35, 62, 89, 127, 151]
        if not mine:
            colors, positions = list(reversed(colors)), [350, 374, 412, 439, 466]
        glyphs = []
        for x, color in zip(positions, colors):
            glyphs.append({'bounds': [x+offset, 130, x+offset+10, 140], 'area': 100,
                'red_pixels': 60 if color == 'red' else 0,
                'purple_pixels': 60 if color == 'purple' else 9 if color == 'dark' else 0,
                'dark_pixels': 65 if color == 'dark' else 10})
        return {'background_value_median': 225, 'glyphs': glyphs, 'bounds': [offset, 100, offset+220, 150]}

    def test_role_spacing_mirrors_and_dark_shield_edges(self):
        for mine in [True, False]:
            r = classify_headers([self.panel(0, mine)])['mine' if mine else 'theirs']
            self.assertEqual(r['party']['value'], 2)
            self.assertEqual(r['shields']['value'], 1)

    def test_conflicting_panels_are_unknown(self):
        a, b = self.panel(), self.panel(4)
        b['glyphs'][2].update(red_pixels=60, dark_pixels=10)
        value = classify_headers([a, b])['mine']['party']
        self.assertIsNone(value['value'])
        self.assertEqual(value['status'], 'contradictory')

    def test_count_run_confirmation_is_not_backdated_knowledge(self):
        values = [3, 3, 3, 2, 2, 2, 3, 3, 3]
        rows = [{'t': i/12, 'source_pts': i, 'source_time_base': '1/12',
                 'headers': {'mine': {'party': {'value': v}}}} for i, v in enumerate(values)]
        result = stable_counter_runs(rows, 'mine', 'party')
        self.assertEqual(result[1]['first_visible_seconds'], .25)
        self.assertGreater(result[1]['confirmed_seconds'], .25)
        self.assertEqual(result[2]['continuity'], 'increase_requires_review')

    def test_center_bar_switches_owner_only_after_release(self):
        row = {'t': 4, 'health': {s: {'status': 'not_visible'} for s in ['mine', 'theirs']}}
        row['health']['center'] = {'status': 'observed', 'bar': {'fraction': .5}}
        timeline = {'clip_origin_seconds': 0, 'charged': [{'t': 1, 'side': 'mine',
                      'announcement_clip_seconds': [8], 'side_evidence': 'explicit_cue'}]}
        self.assertIsNotNone(health_owners(row, timeline)['mine'])
        row['t'] = 8.5
        self.assertTrue(all(v is None for v in health_owners(row, timeline).values()))
        row['t'] = 9.1
        self.assertIsNotNone(health_owners(row, timeline)['theirs'])

    def test_disguise_without_counter_drop_never_spends_shield(self):
        timeline = {'clip_origin_seconds': 0, 'end': 30, 'charged': [
            {'t': 5, 'side': 'theirs', 'blocked': True, 'announcement_clip_seconds': [12]}]}
        counters = {'mine': {'shields': [{'first_visible_seconds': 0, 'confirmed_seconds': .2, 'value': 2}]},
                    'theirs': {'shields': []}}
        looks = [{'t': 13, 'foe_charged': 'DRUM_BEATING', 'my_shields': 1}]
        report = reconcile_source_shields(looks, timeline, counters)
        self.assertEqual(looks[0]['my_shields'], 2)
        self.assertEqual(report['assignments'], [])

    def test_centered_victim_does_not_become_the_replacement_header(self):
        row={'t':11,'health':{s:{'status':'not_visible'} for s in ['mine','theirs']}}
        row['health']['center']={'status':'observed','bar':{'fraction':0}}
        timeline={'clip_origin_seconds':0,'charged':[dict(t=1,side='theirs',actor='Attacker',announcement_clip_seconds=[8])],
                  'field':{'mine':[dict(t=0,name='Victim'),dict(t=10,name='Replacement')],'theirs':[dict(t=0,name='Attacker')]}}
        self.assertEqual(health_owners(row,timeline)['mine']['camera_species'],'Victim')

    def test_future_announcement_does_not_name_the_earlier_camera(self):
        row={'t':4,'health':{s:{'status':'not_visible'} for s in ['mine','theirs']}}
        row['health']['center']={'status':'observed','bar':{'fraction':.5}}
        timeline={'clip_origin_seconds':0,'charged':[dict(t=1,side='mine',actor='FutureName',announcement_clip_seconds=[8])],
                  'field':{'mine':[dict(t=0,name='ObservedName')],'theirs':[]}}
        self.assertEqual(health_owners(row,timeline)['mine']['camera_species'],'ObservedName')

    def test_no_shield_requires_actual_unchanged_readback(self):
        timeline=dict(clip_origin_seconds=0,charged=[dict(t=3,side='theirs',announcement_clip_seconds=[10])])
        def sample(t,value):return dict(t=t,source_pts=round(t*120),source_time_base='1/120',headers={'mine':{'shields':{'value':value}}})
        before=[sample(t,2) for t in [2.5,2.6,2.7]]
        self.assertEqual(shield_readbacks(before,timeline)[0]['status'],'unknown')
        after=[sample(t,2) for t in [11,11.1,11.2]]
        decision=shield_readbacks(before+after,timeline)[0]
        self.assertFalse(decision['shielded'])
        self.assertEqual(decision['confirmed_at_seconds'],11.2)

    def test_equal_shield_counts_bound_an_unreadable_charge_gap(self):
        timeline=dict(clip_origin_seconds=0,charged=[dict(t=20,side='theirs',announcement_clip_seconds=[27])])
        def sample(t,v):return dict(t=t,source_pts=round(t*120),source_time_base='1/120',headers={s:{'shields':{'value':v}} for s in ['mine','theirs']})
        native=[sample(t,1) for t in [2,2.1,2.2,28,28.1,28.2]]
        decision=shield_readbacks(native,timeline)[0]
        self.assertEqual(decision['status'],'confirmed_no_spend')
        self.assertEqual(decision['confirmed_at_seconds'],28.2)
        self.assertEqual(decision['before_confirmed_seconds'],2.2)

    def test_shield_increase_breaks_historical_no_spend_proof(self):
        timeline=dict(clip_origin_seconds=0,charged=[dict(t=20,side='theirs',announcement_clip_seconds=[27])])
        def sample(t,v):return dict(t=t,source_pts=round(t*120),source_time_base='1/120',headers={s:{'shields':{'value':v}} for s in ['mine','theirs']})
        native=[sample(t,v) for times,v in [([2,2.1,2.2],0),([10,10.1,10.2],1),([28,28.1,28.2],1)] for t in times]
        self.assertEqual(shield_readbacks(native,timeline)[0]['status'],'unknown')


class IntegerEnergy(unittest.TestCase):
    def test_hidden_buttons_do_not_mean_zero(self):
        result = intersect_buttons([])
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['integer_ranges'], [[0, 100]])

    def test_ready_button_retains_multiple_helpings(self):
        result = intersect_buttons([{'observed': True, 'fill': .5, 'cost': 35, 'ready': True}])
        self.assertTrue(any(a <= 52 <= b for a, b in result['integer_ranges']))
        self.assertFalse(result['exact'])
        self.assertTrue(all(a >= 35 for a, b in result['integer_ranges']))

    def test_conflicting_buttons_remain_contradictory(self):
        result = intersect_buttons([{'observed': True, 'fill': .5, 'cost': 40, 'ready': False},
                                    {'observed': True, 'fill': .5, 'cost': 60, 'ready': False}], .01)
        self.assertEqual(result['status'], 'contradictory')

    def test_elapsed_time_does_not_force_an_attack(self):
        result = legal_transition([[10, 10]], elapsed_seconds=1,
                                  fast_options=[{'turns': 1, 'energy': 3}])
        self.assertEqual(result[0][0], 10)
        self.assertGreater(result[0][1], 10)
