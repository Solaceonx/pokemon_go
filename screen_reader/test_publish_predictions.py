import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from publish_predictions import promote_prediction,validate_provenance
from segment_battles import file_sha256


class PublicationTests(unittest.TestCase):
    def fixture(self,root):
        folder=root/'battle';folder.mkdir()
        video=folder/'video.mp4';video.write_bytes(b'frozen media')
        profile=root/'profile.json';profile.write_text('{"templates":[]}')
        reader=root/'reader.py';reader.write_text('frozen reader')
        meta={'id':'battle','video_file':'video.mp4','source_start_seconds':10,'source_end_seconds':10.2,'frames':2,'fps':10}
        (folder/'battle.json').write_text(json.dumps(meta))
        previous={'readings':[],'states':[{'t':0,'state':{'value':'kept'}}],'observations':[{'t':0,'look':{'foo':'kept'}}],
                  'events':[{'t':0,'event':{'kind':'kept'}}],'origin':.5}
        (folder/'viewer-data.json.gz').write_bytes(gzip.compress(json.dumps(previous).encode()))
        (folder/'screen_readings.jsonl.gz').write_bytes(b'previous raw')
        with gzip.open(folder/'frame_alignment.jsonl.gz','wt',encoding='utf-8') as stream:
            for i in range(2):stream.write(json.dumps({'clip_seconds':i/10,'source_seconds':10+i/10,'source_pts':1000+i*10,'source_time_base':'1/100'})+'\n')
        provenance={'video_sha256':file_sha256(video),'profile_sha256':file_sha256(profile),
                    'reader_code_sha256':{'reader.py':file_sha256(reader)},'coverage':'full_clip'}
        rows=[{'schema_version':'battle-observation-v1','frame_index':i,'timestamp_seconds':i/10,'phase':{'value':None},
               'source_pts':i*1536,'source_time_base':'1/15360','phase_estimate':{'value':'normal_fighting','status':'inferred'}} for i in range(2)]
        prediction=root/'prediction.json.gz';prediction.write_bytes(gzip.compress(json.dumps({'readings':rows,'prediction_provenance':provenance}).encode()))
        return folder,video,profile,reader,previous,provenance,prediction

    def test_promote_corrects_source_pts_and_preserves_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder,video,profile,reader,old,provenance,prediction=self.fixture(root)
            with patch('battle_reader.EventTracker') as tracker,patch('build_viewer.compact',side_effect=lambda row:{'t':row['timestamp_seconds']}):
                tracker.return_value.update.side_effect=lambda row:[{'kind':'visual','observed_at_seconds':row['timestamp_seconds']}]
                result=promote_prediction(prediction,folder,profile,root=root)
            self.assertEqual(result['decoded_frames'],2)
            with gzip.open(folder/'viewer-data.json.gz','rt',encoding='utf-8') as stream:new=json.load(stream)
            for key in ['states','observations','events','origin']:self.assertEqual(new[key],old[key])
            self.assertEqual(len(new['screen_events']),2)
            self.assertEqual(new['readings'][0]['phase_estimate']['status'],'inferred')
            with gzip.open(folder/'screen_readings.jsonl.gz','rt',encoding='utf-8') as stream:raw=[json.loads(line) for line in stream]
            self.assertEqual(raw[1]['source_pts'],1010)
            self.assertEqual(raw[1]['source_time_base'],'1/100')
            self.assertEqual(raw[1]['clip_pts'],1536)
            self.assertEqual(raw[1]['clip_time_base'],'1/15360')
            self.assertEqual(raw[1]['source_timestamp_seconds'],10.1)
            self.assertTrue((folder/result['prior_analysis_archive']/'screen_readings.jsonl.gz').exists())
            self.assertTrue(promote_prediction(prediction,folder,profile,root=root)['reused_publication'])

    def test_changed_reader_or_video_rejects_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder,video,profile,reader,old,provenance,prediction=self.fixture(root)
            reader.write_text('changed reader')
            with self.assertRaisesRegex(ValueError,'changed'):
                validate_provenance(provenance,video,profile,root)
            reader.write_text('frozen reader');video.write_bytes(b'replaced')
            with self.assertRaisesRegex(ValueError,'video'):
                validate_provenance(provenance,video,profile,root)
            self.assertFalse((folder/'analysis-archive').exists())

    def test_generation_template_hash_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder,video,profile,reader,old,provenance,prediction=self.fixture(root)
            template=root/'cue.png';template.write_bytes(b'original template')
            provenance['template_sha256']={'cue.png':file_sha256(template)}
            self.assertTrue(validate_provenance(provenance,video,profile,root))
            template.write_bytes(b'replaced template')
            with self.assertRaisesRegex(ValueError,'Template'):
                validate_provenance(provenance,video,profile,root)


if __name__=='__main__':unittest.main()
