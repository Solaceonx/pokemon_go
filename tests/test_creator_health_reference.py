import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from score_creator_health_reference import score


class NativeReferenceTests(unittest.TestCase):
    def run_score(self, *, status='observed', species='Victim', reference_status='measured', future=False):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'channel'/'record';folder.mkdir(parents=True)
            state=dict(sides={'mine':dict(active='id',active_status='observed',pokemon={'id':dict(species={'value':species},health=dict(value=[.48,.52],status=status))})})
            (folder/'continuity.jsonl').write_text(json.dumps(dict(t=2 if future else 1,game_state=state))+'\n')
            reference=dict(frames=[dict(channel='channel',record='record',requested_seconds=1,native_witness={'source_seconds':1},sides={'mine':dict(status=reference_status,fraction_interval=[.49,.51])})])
            truth=dict(battles=[dict(record='record',state_anchors=[dict(t=1,expected={'mine.species':'Victim'})])])
            return score(reference,truth,Path(tmp))['counts']

    def test_matching_value_and_identity(self):
        self.assertEqual(self.run_score()['correct'],1)

    def test_wrong_owner_is_incorrect_even_with_matching_fraction(self):
        self.assertEqual(self.run_score(species='Replacement')['correct'],0)

    def test_pending_does_not_count_as_usable(self):
        self.assertEqual(self.run_score(status='pending')['usable'],0)

    def test_hidden_reference_stays_in_coverage_but_not_accuracy(self):
        counts=self.run_score(reference_status='not_visible')
        self.assertEqual((counts['possible'],counts['reference_measured'],counts['scorable_usable']),(1,0,0))
        self.assertIsNone(counts['usable_accuracy'])

    def test_future_snapshot_cannot_answer_earlier_reference(self):
        self.assertEqual(self.run_score(future=True)['usable'],0)
