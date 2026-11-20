from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_faint_support import faint_support, queued_counter_deadline


class FaintConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.death = dict(side='mine', species='Example', clip_seconds=10, confirmed_clip_seconds=10.5,
            method='native_stream_positive_zero_fade_and_independent_confirmation',
            first_zero=dict(t=10, bar=dict(live_pixels=0)), zero_frames=3, missing_frames=3)
        self.timeline = dict(clip_origin_seconds=0, charged=[], field=dict(mine=[dict(name='Example',t=1)],theirs=[]),
                             replacement_selection_prompt_clip_seconds=[11])

    def test_mandatory_selection_confirms_actual_zero_fade_without_visible_party_count(self):
        result = faint_support(self.death, self.timeline, [])
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(result['confirmed_seconds'], 11)
        self.assertEqual(self.death['clip_seconds'], 10)

    def test_prompt_does_not_prove_opponent_faint_or_unmeasured_disappearance(self):
        self.death['side']='theirs'
        self.timeline['field']['theirs']=[dict(name='Example',t=1)]
        self.assertEqual(faint_support(self.death,self.timeline,[])['status'], 'unconfirmed')
        self.death['side']='mine'
        self.death['zero_frames']=2
        self.assertEqual(faint_support(self.death,self.timeline,[])['status'], 'unconfirmed')
        self.death['zero_frames']=3
        self.death['missing_frames']=0
        self.assertEqual(faint_support(self.death,self.timeline,[])['status'], 'unconfirmed')

    def test_stale_prompt_and_intervening_entry_do_not_confirm_prior_zero(self):
        self.timeline['replacement_selection_prompt_clip_seconds']=[9,15]
        self.assertEqual(faint_support(self.death,self.timeline,[])['status'],'unconfirmed')
        self.timeline['replacement_selection_prompt_clip_seconds']=[11]
        self.timeline['field']['mine'].append(dict(name='Other',t=10.5))
        self.assertNotEqual(faint_support(self.death,self.timeline,[])['status'],'confirmed')

    def test_survivor_return_still_refutes_prompt_based_faint(self):
        self.timeline['field']['mine'] += [dict(name='Other',t=12), dict(name='Example',t=20)]
        self.assertEqual(faint_support(self.death,self.timeline,[])['status'],'contradicted')

    def test_queued_confirmation_waits_until_physically_visible_replacement(self):
        q = dict(side='theirs', actor='Example', announcement_clip_seconds=[20,21])
        self.timeline['field']['theirs']=[dict(t=25,name='Other',header_first_visible_clip_seconds=25)]
        self.assertEqual(queued_counter_deadline(q,self.timeline),25)

    def test_no_unbounded_confirmation_or_future_entry_knowledge(self):
        q = dict(side='theirs', actor='Example', announcement_clip_seconds=[20,21])
        self.timeline['field']['theirs']=[dict(t=35,name='Other')]
        self.assertEqual(queued_counter_deadline(q,self.timeline),24)
        self.timeline['field']['theirs']=[dict(t=25,name='Example')]
        self.assertEqual(queued_counter_deadline(q,self.timeline),24)
