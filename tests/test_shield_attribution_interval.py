import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_observations import stable_counter_runs,reconcile_source_shields


class ShieldChangeIntervals(unittest.TestCase):
    def fixture(self,old_last=16,new_first=27.5):
        timeline=dict(clip_origin_seconds=0,end=50,charged=[
            dict(t=10,side='mine',announcement_clip_seconds=[17]),
            dict(t=20,side='theirs',announcement_clip_seconds=[27]),
            dict(t=35,side='mine',announcement_clip_seconds=[42])])
        counters=dict(mine=dict(shields=[]),theirs=dict(shields=[
            dict(value=2,first_visible_seconds=0,confirmed_seconds=.2,last_visible_seconds=old_last),
            dict(value=1,first_visible_seconds=new_first,confirmed_seconds=new_first+.2)]))
        looks=[dict(t=18,my_charged='A'),dict(t=28,foe_charged='B'),dict(t=43,my_charged='C')]
        return looks,timeline,counters

    def test_an_opposing_camera_can_delay_a_unique_spend_readback(self):
        looks,timeline,counters=self.fixture()
        result=reconcile_source_shields(looks,timeline,counters)
        self.assertEqual(len(result['assignments']),1)
        event=result['assignments'][0]
        self.assertEqual(event['charge_index'],0)
        self.assertEqual(event['counter_change_interval_seconds'],[16,27.5])
        self.assertEqual(event['counter']['confirmed_seconds'],27.7)

    def test_a_hidden_interval_with_two_incoming_attacks_stays_unresolved(self):
        looks,timeline,counters=self.fixture(old_last=.2,new_first=43)
        result=reconcile_source_shields(looks,timeline,counters)
        self.assertEqual(result['assignments'],[])
        self.assertEqual(result['unresolved_decrements'][0]['candidate_charges'],[0,2])

    def test_a_later_old_value_rules_out_the_earlier_attack(self):
        looks,timeline,counters=self.fixture(old_last=30,new_first=43)
        self.assertEqual(reconcile_source_shields(looks,timeline,counters)['assignments'][0]['charge_index'],2)

    def test_two_spends_cannot_be_claimed_by_one_attack(self):
        looks,timeline,counters=self.fixture(old_last=15,new_first=18)
        timeline['charged']=timeline['charged'][:1]
        counters['theirs']['shields'][1]['last_visible_seconds']=19
        counters['theirs']['shields'].append(dict(value=0,first_visible_seconds=20,confirmed_seconds=20.2))
        result=reconcile_source_shields(looks,timeline,counters)
        self.assertEqual(result['assignments'],[])
        self.assertEqual(len(result['unresolved_decrements']),2)

    def test_counter_increase_invalidates_later_attribution(self):
        looks,timeline,counters=self.fixture()
        counters['theirs']['shields'][0]['continuity']='increase_requires_review'
        self.assertEqual(reconcile_source_shields(looks,timeline,counters)['assignments'],[])

    def test_last_visible_is_a_measured_witness_not_the_first_confirmation(self):
        values=[2,2,2,2,None,2,2,2,1,1,1]
        native=[dict(t=i/12,source_pts=i,source_time_base='1/12',headers={'mine':{'shields':{'value':v}}})
                for i,v in enumerate(values)]
        runs=stable_counter_runs(native,'mine','shields')
        self.assertEqual(runs[0]['confirmed_seconds'],2/12)
        self.assertEqual(runs[0]['last_visible_seconds'],7/12)
        self.assertEqual(runs[0]['last_source_pts'],7)
        self.assertEqual(runs[1]['first_visible_seconds'],8/12)
