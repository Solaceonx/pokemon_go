import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_faint_support import faint_support


class FaintSupportTests(unittest.TestCase):
    def setUp(self):
        self.death=dict(side='mine',species='Example',clip_seconds=10,confirmed_clip_seconds=11)
        self.timeline=dict(clip_origin_seconds=0,field={'mine':[dict(t=0,name='Example')]},charged=[])

    def frames(self, before, after):
        return [dict(t=t,headers={'mine':{'party':{'value':n}}}) for t,n in
                [(9.8,before),(10.2,after),(10.3,after),(10.4,after),(12,after)]]

    def test_switch_at_one_hp_is_not_a_faint(self):
        self.timeline['field']['mine'].append(dict(t=11,name='Replacement'))
        self.assertEqual(faint_support(self.death,self.timeline,self.frames(3,3))['status'],'contradicted')

    def test_later_return_refutes_earlier_empty_pixels(self):
        self.timeline['field']['mine'] += [dict(t=11,name='Replacement'),dict(t=50,name='Example')]
        self.assertEqual(faint_support(self.death,self.timeline,self.frames(3,2))['status'],'contradicted')

    def test_counter_drop_confirms_at_third_source_sample(self):
        proof=faint_support(self.death,self.timeline,self.frames(3,2))
        self.assertEqual(proof['status'],'confirmed')
        self.assertEqual(proof['confirmed_seconds'],10.4)

    def test_terminal_zero_does_not_need_a_result_screen(self):
        self.assertEqual(faint_support(self.death,self.timeline,self.frames(1,1))['status'],'confirmed')

    def test_missing_evidence_is_unconfirmed(self):
        self.assertEqual(faint_support(self.death,self.timeline,[])['status'],'unconfirmed')

    def test_later_release_without_queue_proof_requires_review(self):
        self.timeline['charged']=[dict(side='mine',actor='Example',announcement_clip_seconds=[14])]
        self.assertEqual(faint_support(self.death,self.timeline,self.frames(3,2))['status'],'unconfirmed')

    def test_late_confirmed_header_can_disprove_old_victim_without_backdating_knowledge(self):
        self.timeline['field']['mine'].append(dict(t=9.9,name='ActualVictim',header_seen_clip_seconds=10.1,header_first_visible_clip_seconds=5))
        self.death['confirmed_clip_seconds']=10.4
        self.assertEqual(faint_support(self.death,self.timeline,self.frames(1,1))['reason'],'different_active_physically_identified_before_proposed_faint')

    def test_replacement_near_zero_does_not_rename_lingering_victim(self):
        self.timeline['field']['mine'].append(dict(t=10.1,name='Replacement',header_seen_clip_seconds=10.1,header_first_visible_clip_seconds=10.1))
        self.assertEqual(faint_support(self.death,self.timeline,self.frames(3,2))['status'],'confirmed')

    def impact_fixture(self):
        self.timeline['charged']=[dict(t=5,side='theirs',announcement_clip_seconds=[8])]
        self.death.update(method='native_empty_bar_and_fade_with_counter_or_fresh_replacement_header',
            first_zero=dict(t=10,bar=dict(live_pixels=0)),
            confirmed_zero=dict(t=10.2,bar=dict(live_pixels=0)))
        return [dict(t=t,headers={'mine':{'party':{'value':n}}}) for t,n in
                [(4.5,3),(4.6,3),(4.7,3),(12,2),(12.1,2),(12.2,2)]]

    def test_native_zero_fade_after_incoming_keeps_pre_cue_counter_provenance(self):
        proof=faint_support(self.death,self.timeline,self.impact_fixture())
        self.assertEqual((proof['status'],proof['confirmed_seconds']),('confirmed',12.2))

    def test_native_zero_fade_fallback_needs_both_actual_zero_witnesses(self):
        native=self.impact_fixture();self.death['confirmed_zero']['bar']['live_pixels']=1
        self.assertEqual(faint_support(self.death,self.timeline,native)['status'],'unconfirmed')

    def test_native_zero_fade_fallback_cannot_cross_another_entry(self):
        native=self.impact_fixture()
        self.timeline['field']['mine'].append(dict(t=9,name='Different'))
        self.assertNotEqual(faint_support(self.death,self.timeline,native)['status'],'confirmed')

    def test_native_zero_fade_fallback_requires_a_named_incoming_release(self):
        native=self.impact_fixture();self.timeline['charged'][0]['side']='mine'
        self.assertEqual(faint_support(self.death,self.timeline,native)['status'],'unconfirmed')


if __name__=='__main__':unittest.main()
