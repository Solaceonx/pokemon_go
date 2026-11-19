import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_event_ledger import source_events


class SourceEventLedgerTests(unittest.TestCase):
    def timeline(self):
        return dict(clip_origin_seconds=10,field={'mine':[],'theirs':[]},
                    charged=[dict(t=5,side='theirs',actor='Ninetales',move='Weather Ball',announcement_clip_seconds=[22,23])])

    def test_generic_name_and_observed_release_survive_model_ambiguity(self):
        event=source_events(self.timeline(),dict(faints=[]),{})[0]
        self.assertEqual((event['move'],event['t']),('Weather Ball',22))
        self.assertFalse(event['model_build_used'])
        self.assertIsNone(event['shielded'])

    def test_late_counter_confirmation_does_not_move_the_release(self):
        measurements={'shield_reconciliation':{'assignments':[dict(charge_index=0,side='mine',counter=dict(first_visible_seconds=21,confirmed_seconds=24))]}}
        result=source_events(self.timeline(),dict(faints=[]),measurements)
        shield,charge=result
        self.assertEqual((shield['t'],shield['confirmed_at_seconds']),(21,24))
        self.assertEqual(charge['t'],22)
        self.assertTrue(charge['shielded'])

    def test_uncertain_faints_and_results_do_not_manufacture_knockouts(self):
        timeline=self.timeline();timeline['result']='win'
        lifecycle={'faints':[dict(side='mine',species='Example',clip_seconds=10,
                                 independent_support=dict(status='contradicted'))]}
        self.assertFalse(any(e['kind']=='faint' for e in source_events(timeline,lifecycle,{})))


if __name__=='__main__':unittest.main()
