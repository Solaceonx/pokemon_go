import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH=Path(__file__).resolve().parents[1]/'scripts/live/enrich_records.py'
spec=importlib.util.spec_from_file_location('enrich_records',PATH)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
pixel_spec=importlib.util.spec_from_file_location('read_saved_pixels',PATH.with_name('read_saved_pixels.py'))
pixel=importlib.util.module_from_spec(pixel_spec);pixel_spec.loader.exec_module(pixel)


class EvidenceTests(unittest.TestCase):
    def rows(self):
        return [dict(line=1,t=0,kind='start',epoch=100),
                dict(line=2,t=1,kind='look',obs={'my_species':'stunfisk','my_hp':.1,'my_energy':40},foe=['toxtricity',20,25,'SPARK','guessed']),
                dict(line=3,t=1.2,kind='decision',action='charged:DISCHARGE',ms=300),
                dict(line=4,t=1.5,kind='look',obs={'my_species':'stunfisk','my_hp':.4}),
                dict(line=5,t=2,kind='energy_read',counted=60,read=40),
                dict(line=6,t=3,kind='end',result='loss')]

    def test_decision_links_only_preceding_reading_and_does_not_invent_view(self):
        summary,evidence,flags=module.analyze('example',self.rows(),'hash')
        decision=next(e for e in evidence if e['kind']=='decision')
        self.assertEqual(decision['preceding_look_line'],2)
        self.assertAlmostEqual(decision['preceding_look_age_seconds'],.2)
        self.assertIsNone(decision['engine_view'])
        self.assertEqual(summary['decisions_without_logged_view'],1)
        self.assertEqual(summary['button_energy_observed_looks'],1)
        self.assertEqual(summary['count_vs_button_disagreement']['median'],20)
        self.assertEqual(len(flags),1)
        self.assertFalse(summary['actual_integer_hp_known'])

    def test_health_change_on_switch_is_not_same_species_increase(self):
        rows=self.rows();rows[3]['obs']['my_species']='jellicent'
        _,_,flags=module.analyze('example',rows,'hash')
        self.assertEqual(flags,[])

    def test_private_text_is_not_exported_and_taps_are_only_attempts(self):
        rows=self.rows();rows.insert(3,dict(line=7,t=1.3,kind='tap',note='fast move',text='PRIVATE TRAINER',point=[.5,.4]))
        rows[0]['account']='PRIVATE ACCOUNT';rows[2]['error']='C:/private/path'
        _,evidence,_=module.analyze('example',rows,'hash')
        self.assertNotIn('PRIVATE',json.dumps(evidence));self.assertNotIn('private/path',json.dumps(evidence))
        tap=next(e for e in evidence if e['kind']=='tap')
        self.assertTrue(tap['is_fast_tap']);self.assertIn('attempt',tap['provenance'])

    def test_assumed_builds_carry_belief_provenance_and_views_drop_unknown_keys(self):
        rows=self.rows();rows[2]['view']={'me':{'team':[{'species':'stunfisk','ivs':[0,15,15],'hp':100,'trainer':'PRIVATE'}]},'foe':{'species':'toxtricity'},'private':'PRIVATE'}
        s,events,_=module.analyze('example',rows,'hash')
        decision=next(e for e in events if e['kind']=='decision')
        self.assertEqual(s['logged_engine_views'],1)
        self.assertNotIn('PRIVATE',json.dumps(decision))
        self.assertIn('not verified',decision['view_provenance'])

    def test_unfinished_battle_is_not_published_as_complete(self):
        with self.assertRaisesRegex(ValueError,'Requires'):
            module.analyze('unfinished',self.rows()[:-1],'hash')

    def test_deterministic_lossless_compression(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b=Path(tmp)/'a.gz',Path(tmp)/'b.gz';rows=[{'t':.5,'energy':None}]
            module.write_gzip(a,rows);module.write_gzip(b,rows)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            self.assertEqual([json.loads(s) for s in gzip.decompress(a.read_bytes()).splitlines()],rows)

    def test_invalid_values_do_not_silently_become_numbers(self):
        for v in [True,None,'unknown',float('nan'),float('inf')]:
            self.assertIsNone(module.number(v))

    def test_frame_times_keep_duplicates_but_reject_backward_or_missing_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'frames.times';path.write_text('100\n100\n100.02\n')
            self.assertEqual(pixel.frame_times(path),[100,100,100.02])
            for value in ['100\n99\n','100\nnan\n','']:
                path.write_text(value)
                with self.assertRaises(ValueError):pixel.frame_times(path)

    def test_numpy_values_are_saved_as_plain_json_numbers_and_booleans(self):
        import numpy as np
        encoded=json.dumps({'left':np.int64(3),'header':np.bool_(True)},default=pixel.native)
        self.assertEqual(json.loads(encoded),{'left':3,'header':True})


if __name__=='__main__':unittest.main()
