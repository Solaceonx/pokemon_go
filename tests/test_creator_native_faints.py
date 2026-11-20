import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_native_faints import native_faints, disappearance_faints, counter_zero_faints, caught_entry_faints, queued_charge_faints


class NativeFaintTiming(unittest.TestCase):
    def fixture(self):
        rows = []
        for i in range(20):
            t = i/12
            bar = {'bounds': [30, 500, 180, 514], 'live_pixels': 4 if i < 2 else 0}
            health = {s: {'status': 'not_visible'} for s in ['mine', 'theirs', 'center']}
            if i < 5:
                health['mine'] = {'status': 'observed', 'bar': bar}
            rows.append({'t': t, 'health': health, 'source_pts': i, 'source_time_base': '1/12'})
        timeline = {'clip_origin_seconds': 0, 'charged': [], 'field': {'mine': [
            {'t': 0, 'name': 'Kingdra', 'header_seen_clip_seconds': 0},
            {'t': 2, 'name': 'Victreebel', 'header_seen_clip_seconds': 2}], 'theirs': []}}
        counters = {'mine': {'party': [
            {'first_visible_seconds': 0, 'confirmed_seconds': .1, 'value': 3},
            {'first_visible_seconds': .75, 'confirmed_seconds': 1, 'value': 2}]}, 'theirs': {'party': []}}
        return rows, timeline, counters

    def test_date_is_zero_while_confirmation_is_later(self):
        rows, timeline, counters = self.fixture()
        event = native_faints(rows, timeline, counters)[0]
        self.assertAlmostEqual(event['clip_seconds'], 2/12)
        self.assertEqual(event['confirmed_clip_seconds'], 1)

    def test_missing_bar_alone_does_not_mean_faint(self):
        rows, timeline, counters = self.fixture()
        for r in rows:
            if r['health']['mine']['status'] == 'observed':
                r['health']['mine']['bar']['live_pixels'] = 4
        self.assertEqual(native_faints(rows, timeline, counters), [])

    def test_later_named_release_refutes_apparent_palette_zero(self):
        rows, timeline, counters = self.fixture()
        timeline['charged'] = [{'t': .3, 'side': 'mine', 'announcement_clip_seconds': [1.2]}]
        self.assertEqual(native_faints(rows, timeline, counters), [])

    def test_delayed_replacement_does_not_backdate_faint_to_earlier_fade(self):
        rows, timeline, counters = self.fixture()
        counters['mine']['party'] = counters['mine']['party'][:1]
        timeline['field']['mine'][1]['header_seen_clip_seconds'] = 14
        self.assertEqual(native_faints(rows, timeline, counters), [])

    def tiny_fixture(self,drop=True):
        native=[]
        for i in range(20):
            health={s:{'status':'not_visible'} for s in ['mine','theirs','center']}
            if i<4:
                health['mine']={'status':'observed','bar':{'live_pixels':0,'bounds':[30,500,180,514]}}
            native.append(dict(t=i/12,health=health,source_pts=i,source_time_base='1/12',
                headers={'mine':{'party':{'value':1 if drop and i>=6 else 2}}}))
        timeline=dict(clip_origin_seconds=0,charged=[],field={'mine':[dict(t=-1,name='Example')],'theirs':[]})
        return native,timeline

    def test_tiny_bar_uses_disappearance_time_with_independent_counter(self):
        native,timeline=self.tiny_fixture()
        event=disappearance_faints(native,timeline)[0]
        self.assertAlmostEqual(event['clip_seconds'],4/12)
        self.assertGreaterEqual(event['confirmed_clip_seconds'],8/12)

    def test_tiny_bar_switch_with_unchanged_party_is_not_a_faint(self):
        native,timeline=self.tiny_fixture(drop=False)
        timeline['field']['mine'].append(dict(t=1,name='Replacement'))
        self.assertEqual(disappearance_faints(native,timeline),[])

    def test_camera_changes_before_release_are_not_faints(self):
        native,timeline=self.tiny_fixture()
        timeline['charged']=[dict(t=0,side='mine',announcement_clip_seconds=[1])]
        self.assertEqual(disappearance_faints(native,timeline),[])

    def test_old_center_bar_cannot_faint_the_new_header(self):
        native,timeline=self.tiny_fixture()
        timeline['field']['mine'].append(dict(t=.2,name='Replacement'))
        for row in native[:4]:
            row['health']['mine']['bar']['camera_species']='Example'
        self.assertEqual(disappearance_faints(native,timeline)[0]['species'],'Example')
        for row in native[:4]:
            row['health']['mine']['bar'].pop('camera_species')
        self.assertEqual(disappearance_faints(native,timeline)[0]['species'],'Example')

    def test_low_nonzero_strip_needs_independent_decrement(self):
        native,timeline=self.tiny_fixture()
        for r in native[:4]:
            r['health']['mine']['bar']['live_pixels']=10
            r['health']['mine']['bar']['interior_width_pixels']=140
        self.assertEqual(len(disappearance_faints(native,timeline)),1)
        native,timeline=self.tiny_fixture(drop=False)
        for r in native:
            r['headers']['mine']['party']['value']=1
        for r in native[:4]:
            r['health']['mine']['bar']['live_pixels']=10
            r['health']['mine']['bar']['interior_width_pixels']=140
        self.assertEqual(disappearance_faints(native,timeline),[])

    def test_fast_damage_can_cross_low_strip_threshold_between_samples(self):
        native,timeline=self.tiny_fixture()
        for i,r in enumerate(native[:4]):
            r['health']['mine']['bar']['live_pixels']=9 if i==3 else 16
            r['health']['mine']['bar']['interior_width_pixels']=140
        self.assertEqual(len(disappearance_faints(native,timeline)),1)

    def test_counter_corrobates_zero_before_later_body_fade(self):
        native,timeline=self.tiny_fixture()
        import copy
        prefix=[]
        for t in [-.5,-.4,-.3]:
            r=copy.deepcopy(native[0]);r['t']=t;r['health']['mine']={'status':'not_visible'};prefix.append(r)
        native=prefix+native
        counters={'mine':{'party':[dict(value=2),dict(value=1,first_visible_seconds=.5)]},'theirs':{'party':[]}}
        event=counter_zero_faints(native,timeline,counters)[0]
        self.assertEqual(event['clip_seconds'],0)
        self.assertGreaterEqual(event['confirmed_clip_seconds'],8/12)

    def test_distant_drop_cannot_backdate_an_apparent_zero(self):
        native,timeline=self.tiny_fixture()
        counters={'mine':{'party':[dict(value=2),dict(value=1,first_visible_seconds=7)]},'theirs':{'party':[]}}
        self.assertEqual(counter_zero_faints(native,timeline,counters),[])

    def test_charge_target_zero_can_wait_for_headers_without_moving_death_to_replacement(self):
        native=[]
        for i in range(-6,85):
            t=i/12;health={s:{'status':'not_visible'} for s in ['mine','theirs','center']}
            if 3<=t<3.5:
                health['center']={'status':'observed','bar':dict(live_pixels=0,bounds=[180,500,325,514])}
            party=2 if t<=0 else 1 if t>=6 else None
            native.append(dict(t=t,health=health,source_pts=i,source_time_base='1/12',headers={'mine':{'party':{'value':party}}}))
        timeline=dict(clip_origin_seconds=0,charged=[dict(t=0,side='theirs',announcement_clip_seconds=[2])],field={'mine':[dict(t=-1,name='Victim')],'theirs':[]})
        counters={'mine':{'party':[dict(value=2),dict(value=1,first_visible_seconds=6)]},'theirs':{'party':[]}}
        event=counter_zero_faints(native,timeline,counters)[0]
        self.assertEqual(event['clip_seconds'],3)
        self.assertGreaterEqual(event['confirmed_clip_seconds'],6+2/12)

    def test_short_caught_return_counter_belongs_to_incoming_victim(self):
        timeline=dict(clip_origin_seconds=0,charged=[],field={'mine':[], 'theirs':[
            dict(t=0,name='Victim'),dict(t=5,name='Survivor'),dict(t=10,name='Victim'),dict(t=12,name='Survivor')]})
        counters={'mine':{'party':[]},'theirs':{'party':[dict(value=2),dict(value=1,first_visible_seconds=10.2,confirmed_seconds=10.4)]}}
        event=caught_entry_faints([],timeline,counters)[0]
        self.assertEqual(event['species'],'Victim')
        self.assertEqual(event['clip_seconds'],10.2)
        self.assertEqual(event['confirmed_clip_seconds'],12)
        counters['theirs']['party'][1]['value']=2
        self.assertEqual(caught_entry_faints([],timeline,counters),[])

    def test_queued_release_preserves_a_wide_death_interval_and_late_state_time(self):
        from creator_faint_support import faint_support,death_state_seconds
        native=[]
        for t in [1.5,1.6,1.7,2,2.1,2.2,8.5,8.6,8.7]:
            health={s:{'status':'not_visible'} for s in ['mine','theirs','center']}
            if 2<=t<=2.2:health['mine']={'status':'observed','bar':dict(bounds=[30,500,180,514],live_pixels=0)}
            native.append(dict(t=t,health=health,headers={'mine':{'party':{'value':2 if t<8 else 1}}},source_pts=round(t*60),source_time_base='1/60'))
        timeline=dict(clip_origin_seconds=0,charged=[dict(t=2,side='mine',actor='Victim',move='Dive',side_evidence='explicit_cue',announcement_clip_seconds=[8])],field={'mine':[dict(t=0,name='Victim')],'theirs':[]})
        counters={'mine':{'party':[dict(value=2),dict(value=1,first_visible_seconds=8.5,confirmed_seconds=8.7)]},'theirs':{'party':[]}}
        death=queued_charge_faints(native,timeline,counters)[0]
        self.assertEqual(death['timing_interval_seconds'],[2,8.5])
        self.assertEqual(death_state_seconds(death),8.5)
        self.assertEqual(faint_support(death,timeline,native)['status'],'confirmed')
        native.insert(6,dict(t=4,health={'mine':{'status':'observed','bar':dict(live_pixels=5,bounds=[30,500,180,514])},'theirs':{'status':'not_visible'},'center':{'status':'not_visible'}}))
        self.assertEqual(queued_charge_faints(native,timeline,counters),[])


if __name__ == '__main__':
    unittest.main()
