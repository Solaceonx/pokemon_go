import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_forms import collect,FormEvidence
from public_state import PublicState
from test_public_state import frame,SLIM


def evidence():
    text=[dict(t=t,text=[['banner',"Mimikyu's disguise is busted!"]]) for t in (12,13)]
    timeline=dict(clip_origin_seconds=0,charged=[dict(t=9,side='mine',move='Shadow Sneak',
        announcement_clip_seconds=[10],side_confirmed_clip_seconds=9)],
        field={'mine':[],'theirs':[dict(name='Mimikyu',header_seen_clip_seconds=1)]})
    events=[dict(kind='charged',side='mine',charge_index=0,confirmed_at_seconds=10,shielded=False)]
    def sample(t,cp=1498):return dict(t=t,values={'theirs':dict(species='Mimikyu',cp=cp,
        confirmed_seconds=t,source_pts=round(t*30),source_time_base='1/30')})
    native=[sample(8),sample(14)]
    raw=[dict(t=r['t'],theirs=dict(species='Mimikyu',cp=r['values']['theirs']['cp'])) for r in native]
    return [text,timeline,events,native,raw]


class DeferredFormTarget(unittest.TestCase):
    def test_recovery_confirms_form_at_return_not_at_earlier_caption(self):
        event=collect(*evidence())['events'][0]
        self.assertEqual((event['t'],event['confirmed_at_seconds']),(12,14))
        self.assertEqual(event['target_recovery_identity'],'Mimikyu:1498')
        self.assertEqual(event['target_recovery_seconds'],14)
        self.assertIn('bracketed_causal_target',event['method'])
        self.assertEqual(len(FormEvidence([event]).events),1)

    def test_future_recovery_is_not_a_past_game_state_fact(self):
        event=collect(*evidence())['events'][0]
        ledger=PublicState({},form_events=[event])
        def reading(t):
            value=frame(t,name='Mimikyu',cp=1497)
            value['opponent']['species']['value']='Mimikyu'
            value['opponent']['cp']['value']=1498
            return value
        for t in (1,1.4,12,13.9):
            state=ledger.update(reading(t),SLIM)
            self.assertIsNone(state['sides']['opponent']['pokemon']['Mimikyu:1498']['form']['value'])
        state=ledger.update(reading(14),SLIM)
        self.assertEqual(state['sides']['opponent']['pokemon']['Mimikyu:1498']['form']['value'],'mimikyu_busted')

    def test_a_different_recovery_cp_does_not_borrow_the_previous_target(self):
        args=evidence();args[3][-1]['values']['theirs']['cp']=1496
        self.assertFalse(collect(*args)['events'])

    def test_any_intervening_unconfirmed_header_or_entry_blocks_the_bracket(self):
        args=evidence();args[4].insert(1,dict(t=13.5,theirs=dict(species='Mimikyu',cp=1496)))
        self.assertFalse(collect(*args)['events'])
        args=evidence();args[1]['field']['theirs'].append(dict(name='Mimikyu',header_seen_clip_seconds=13.5))
        self.assertFalse(collect(*args)['events'])

    def test_first_return_is_authoritative_not_a_later_matching_return(self):
        args=evidence();args[3].insert(1,dict(t=13.5,values={'theirs':dict(species='Lapras',cp=1497,confirmed_seconds=13.5)}))
        self.assertFalse(collect(*args)['events'])

    def test_one_caption_is_still_insufficient(self):
        args=evidence();args[0]=args[0][:1]
        self.assertFalse(collect(*args)['events'])

    def test_an_edited_or_conflicting_cue_cannot_bridge_the_hidden_target(self):
        args=evidence();args[1]['charged'][0]['cue_conflict']=dict(reason='edited transition')
        self.assertFalse(collect(*args)['events'])

    def test_pre_cue_and_return_gaps_are_bounded(self):
        args=evidence();args[3][0].update(t=6);args[3][0]['values']['theirs']['confirmed_seconds']=6
        self.assertFalse(collect(*args)['events'])
        args=evidence();args[3][-1].update(t=20);args[3][-1]['values']['theirs']['confirmed_seconds']=20
        self.assertFalse(collect(*args)['events'])

    def test_a_future_confirmation_inside_a_header_is_not_a_reading(self):
        args=evidence();args[3][-1]['values']['theirs']['confirmed_seconds']=15
        self.assertFalse(collect(*args)['events'])

    def test_shield_conflict_known_by_return_suppresses_the_form(self):
        args=evidence();args[2][0].update(shielded=True,shield_confirmed_at_seconds=13.5)
        self.assertFalse(collect(*args)['events'])

    def test_same_species_on_both_sides_keeps_the_physical_target_cp(self):
        args=evidence()
        for sample in args[3]:sample['values']['mine']=dict(species='Mimikyu',cp=1491,confirmed_seconds=sample['t'])
        self.assertEqual(collect(*args)['events'][0]['identity'],'Mimikyu:1498')

    def test_typed_bracket_records_cannot_claim_knowledge_before_recovery(self):
        event=collect(*evidence())['events'][0]
        for changed in [dict(confirmed_at_seconds=13),dict(target_recovery_identity='Mimikyu:1496'),
                        dict(target_header_seen_seconds=15),dict(target_recovery_seconds=float('inf'))]:
            self.assertFalse(FormEvidence([{**event,**changed}]).events)
