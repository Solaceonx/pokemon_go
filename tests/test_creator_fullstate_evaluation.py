import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from evaluate_creator_fullstate import snapshot_at, usable, anchor_fields, visible_species, timing_diagnostics, shield_decision_accuracy,field_metrics
from creator_identity import header_identity, IdentityEvidence


class FullstateEvaluationTests(unittest.TestCase):
    def test_unknown_battle_reduces_field_coverage_even_when_usable_values_are_correct(self):
        record=lambda available:dict(anchors=[dict(fields=[dict(field='mine.species',reported=available,correct=available,usable=available)])])
        result=field_metrics([record(True),record(False)],repetitions=200)['species']
        self.assertEqual(result['usable_accuracy'],1)
        self.assertEqual(result['usable_coverage'],.5)
        self.assertEqual(result['usable_coverage_battle_bootstrap_95'],[0,1])
    def test_unknown_no_shield_decision_is_not_counted_correct(self):
        expected=[dict(kind='charged',side='mine',pokemon='Example',move='Surf',window=[10,11],shielded=False)]
        actual=[dict(kind='charged',side='mine',pokemon='Example',move='Surf',t=10,shielded=None)]
        self.assertEqual(shield_decision_accuracy(expected,actual)['unknown'],1)
        self.assertEqual(shield_decision_accuracy(expected,actual)['correct'],0)
        actual[0]['shielded']=False
        self.assertEqual(shield_decision_accuracy(expected,actual)['correct'],1)
    def test_late_event_can_pass_primary_score_but_fails_tighter_timing(self):
        expected=[dict(kind='faint',side='mine',pokemon='Example',window=[10,11])]
        actual=[dict(kind='faint',side='mine',pokemon='Example',t=13)]
        result=timing_diagnostics(expected,actual)
        self.assertEqual(result['matches_by_tolerance_seconds'],{'0':0,'1':0,'3':1})
        self.assertEqual(result['maximum_absolute_distance_seconds'],2)
        actual[0]['t']=24
        self.assertEqual(timing_diagnostics(expected,actual)['matched_events'],0)
    def test_lookup_does_not_use_future_confirmation(self):
        rows=[{'t':1,'game_state':{'value':'before'}},{'t':2,'game_state':{'value':'after'}}]
        self.assertEqual(snapshot_at(rows,.9),{})
        self.assertEqual(snapshot_at(rows,1.9),{'value':'before'})

    def test_a_matching_lower_bound_does_not_hide_a_wide_faint_interval(self):
        expected=[dict(kind='faint',side='mine',pokemon='Example',window=[10,11])]
        actual=[dict(kind='faint',side='mine',pokemon='Example',t=10,timing_interval_seconds=[10,19])]
        result=timing_diagnostics(expected,actual)
        self.assertEqual(result['matches_by_tolerance_seconds']['0'],1)
        self.assertEqual(result['matched_with_timing_uncertainty_over_one_second'],1)

    def test_pending_and_stale_values_do_not_count_as_usable(self):
        for status in ['pending','unknown','stale','historical','contradictory']:
            self.assertFalse(usable(dict(value=2,status=status)))
        self.assertTrue(usable(dict(value=2,status='retained',state_validity='carried_forward')))

    def test_unknown_field_stays_in_denominator(self):
        result=anchor_fields({},dict(expected={'mine.party':3},fraction_annotations={'mine':[.4,.6]}))
        self.assertEqual(len(result),2)
        self.assertTrue(all(not f['reported'] and not f['usable'] for f in result))

    def test_full_range_hp_is_not_an_accurate_measurement(self):
        state={'sides':{'mine':{'active':'x','pokemon':{'x':{'health':dict(value=[0,1],status='estimated')}}}}}
        field=anchor_fields(state,dict(expected={},fraction_annotations={'mine':[.4,.6]}))[0]
        self.assertFalse(field['correct'])
        self.assertTrue(field['interval_overlap'])

    def test_header_species_grade_does_not_require_unannotated_form(self):
        self.assertEqual(visible_species('qwilfish_hisuian',{'qwilfish_hisuian':'Qwilfish'}),'Qwilfish')

    def test_a_fainted_active_is_not_the_unread_replacement(self):
        state={'sides':{'mine':{'active':'x','active_status':'awaiting_replacement',
            'pokemon':{'x':{'species':dict(value='Cramorant',status='observed')}}}}}
        field=anchor_fields(state,dict(expected={'mine.species':'Cramorant'}))[0]
        self.assertTrue(field['reported'])
        self.assertFalse(field['usable'])


class SourceIdentityTests(unittest.TestCase):
    def test_conjoined_ocr_in_either_order(self):
        for text in ['CramorantCP1498','CP1498Cramorant','Cramorant CP 1498']:
            result=header_identity([dict(text=text,confidence=.96)],['Cramorant'])
            self.assertEqual((result['species'],result['cp']),('Cramorant',1498))

    def test_ambiguous_names_or_cps_are_unknown(self):
        read=lambda text:dict(text=text,confidence=.96)
        self.assertIsNone(header_identity([read('Cramorant CP1498'),read('Blastoise CP1500')],['Cramorant','Blastoise']))
        self.assertIsNone(header_identity([read('Cramorant')],['Cramorant']))
        self.assertIsNone(header_identity([read('Other CP1498')],['Cramorant']))

    def test_identity_requires_independent_repeated_reading(self):
        ledger=IdentityEvidence()
        def sample(t,cp=1498):return dict(t=t,mine=dict(species='Cramorant',cp=cp),theirs=None,source_pts=int(t*60),source_time_base='1/60')
        self.assertEqual(ledger.update(sample(1)),{})
        self.assertEqual(ledger.update(sample(1)),{})
        confirmed=ledger.update(sample(2))['mine']
        self.assertEqual(confirmed['confirmed_seconds'],2)
        self.assertEqual(ledger.update(sample(3,1486)),{})

    def test_exact_entry_and_physical_header_are_independent_corroboration(self):
        sample=dict(t=20,mine=dict(species='Hydreigon',cp=1494),theirs=None,source_pts=1200,source_time_base='1/60')
        ledger=IdentityEvidence()
        for t in [0,1]:ledger.update({**sample,'t':t})
        ledger.update({**sample,'t':2,'mine':None})
        self.assertEqual(ledger.update(sample,[dict(t=20.1,species='Hydreigon')]),{})
        self.assertEqual(ledger.update(sample,[dict(t=20,species='Melmetal')]),{})
        value=ledger.update(sample,[dict(t=20,species='Hydreigon')])['mine']
        self.assertEqual(value['confirmed_seconds'],20)
        self.assertEqual(value['method'],'physical_header_and_matching_entry_announcement')

    def test_entry_name_does_not_corroborate_a_first_or_misread_cp(self):
        sample=dict(t=10,mine=dict(species='Cramorant',cp=1499),theirs=None,source_pts=600,source_time_base='1/60')
        self.assertEqual(IdentityEvidence().update(sample,[dict(t=10,species='Cramorant')]),{})

    def test_unreadable_animation_preserves_pending_pair_but_not_a_changed_cp(self):
        sample=dict(t=1,mine=dict(species='Annihilape',cp=1498),theirs=None,source_pts=60,source_time_base='1/60')
        ledger=IdentityEvidence();self.assertEqual(ledger.update(sample),{})
        self.assertEqual(ledger.update({**sample,'t':5,'mine':None}),{})
        confirmed=ledger.update({**sample,'t':11,'source_pts':660})['mine']
        self.assertEqual((confirmed['first_visible_seconds'],confirmed['confirmed_seconds']),(1,11))
        ledger=IdentityEvidence();ledger.update(sample)
        ledger.update({**sample,'t':5,'mine':dict(species='Annihilape',cp=1499)})
        self.assertEqual(ledger.update({**sample,'t':11}),{})


if __name__=='__main__':unittest.main()
