import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_charge_evidence import actor_for_release,actor_consensus,historical_side,prior_minigame


class ReleaseEvidenceTests(unittest.TestCase):
    def test_illegal_nearest_species_does_not_beat_later_exact_banner(self):
        pairs=(('Durant','Stone Edge'),('Cramorant','Dive'))
        self.assertIsNone(actor_for_release('orant','Dive',pairs))
        exact=actor_for_release('Cramorant','Dive',pairs)
        result=actor_consensus([dict(name='Durant',quality=.8,t=99),dict(t=100,**exact)])
        self.assertEqual((result['name'],result['t']),('Cramorant',100))

    def test_conflicting_exact_actors_remain_unresolved(self):
        self.assertIsNone(actor_consensus([dict(name='A',quality=1,t=4),dict(name='B',quality=1,t=5)]))

    def test_unread_move_and_garbled_actor_stay_unknown_without_crashing(self):
        pairs=(('Cramorant','Dive'),)
        self.assertIsNone(actor_for_release('orant',None,pairs))
        self.assertEqual(actor_for_release('Cramorant',None,pairs)['name'],'Cramorant')

    def test_future_header_cannot_set_side_and_mirror_stays_ambiguous(self):
        fields={'mine':[dict(name='Cramorant',seen=10)],'theirs':[dict(name='Mimikyu',seen=20),dict(name='Cramorant',seen=60)]}
        self.assertEqual(historical_side('Cramorant',fields,56),'mine')
        self.assertIsNone(historical_side('Cramorant',fields,61))

    def test_minigame_before_missing_cue_must_follow_previous_release(self):
        texts=[dict(t=t,text=[('middle',word)]) for t,word in [(18,'EXCELLENT!'),(26,'NICE!'),(29,'EXCELLENT!')]]
        self.assertEqual(prior_minigame(texts,22,30),26)
        self.assertIsNone(prior_minigame(texts,29.5,30))

    def test_source_identity_knowledge_is_not_backdated_to_garbled_banner(self):
        from creator_event_ledger import source_events
        timeline=dict(clip_origin_seconds=0,field={'mine':[],'theirs':[]},charged=[dict(t=92,side='theirs',actor='Cramorant',move='Dive',announcement_clip_seconds=[99,100],actor_confirmed_clip_seconds=100)])
        result=source_events(timeline,dict(faints=[]),{})[0]
        self.assertEqual((result['t'],result['confirmed_at_seconds']),(99,100))


if __name__=='__main__':unittest.main()
