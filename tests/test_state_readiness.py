import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from state_readiness import known,interval,available_fields,verified_events,assess


class ReadinessTests(unittest.TestCase):
    def test_pending_and_future_knowledge_cannot_enable_analysis(self):
        self.assertFalse(known(dict(value=.4,status='pending'),10))
        self.assertFalse(known(dict(value=.4,status='observed',observed_at_seconds=11),10))
        self.assertFalse(known(dict(value=.4,status='observed',confirmed_at_seconds=11),10))
        self.assertFalse(known(dict(value=.4),10))
        self.assertFalse(known(dict(value=.4,status='observed',observed_at_seconds=None),10))
        self.assertTrue(known(dict(value=.4,status='observed',observed_at_seconds=10),10))

    def test_uninformative_or_fractional_energy_is_unavailable(self):
        self.assertFalse(interval(dict(value=[0,100],status='estimated'),10,0,100,15,True))
        self.assertFalse(interval(dict(value=[40.5,41.5],status='estimated'),10,0,100,15,True))
        self.assertTrue(interval(dict(value=[40,45],status='estimated'),10,0,100,15,True))

    def test_old_fainted_header_is_not_a_known_new_active(self):
        field=lambda v:dict(value=v,status='observed')
        state={'sides':{'mine':dict(active='old',active_status='awaiting_replacement',
            pokemon={'old':dict(species=field('Example'),cp=field(1500),health=field([0,0]))})}}
        values=available_fields(state,10)
        self.assertFalse(values['mine.active_identity'])
        self.assertFalse(values['mine.health_fraction'])

    def test_a_new_export_cannot_inherit_previous_reference_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);hashes={}
            for name in ['source.json','timeline.json','continuity.jsonl.gz','source-events.jsonl.gz']:
                (folder/name).write_bytes(b'original');hashes[name]=hashlib.sha256(b'original').hexdigest()
            reference=dict(processing_complete=True,prediction_sha256=hashes,
                events={k:dict(tp=1,fp=0,fn=0,timing={'matches_by_tolerance_seconds':{'1':1}}) for k in ['charged','shield','faint']},
                shield_decisions=dict(reference_charges=1,correct=1))
            self.assertTrue(verified_events(folder,reference)['counts_ready'])
            reference['events']['faint']['timing']['matched_with_timing_uncertainty_over_one_second']=1
            self.assertFalse(verified_events(folder,reference)['timing_ready'])
            (folder/'source-events.jsonl.gz').write_bytes(b'replayed')
            self.assertFalse(verified_events(folder,reference)['counts_ready'])

    def test_missing_video_time_stays_in_the_coverage_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            state={'sides':{s:dict(left=dict(value=3,status='observed'),shields=dict(value=2,status='observed')) for s in ['mine','opponent']}}
            rows=[dict(t=t,game_state=state) for t in [0,5]]
            (folder/'continuity.jsonl.gz').write_bytes(gzip.compress(''.join(json.dumps(r)+'\n' for r in rows).encode('utf8')))
            report=assess(folder)
            self.assertEqual(report['duration_seconds'],5)
            self.assertEqual(report['unobserved_gap_seconds'],5)
            self.assertEqual(report['observable_field_coverage']['mine.party']['fraction'],0)
            self.assertFalse(report['full_game_state_ready'])


if __name__=='__main__':unittest.main()
