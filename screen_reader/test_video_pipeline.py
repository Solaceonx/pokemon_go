from fractions import Fraction
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from button_reader import np
from extract_battles import encode_clip,export_candidates
from run_video_pipeline import run_pipeline,archive_analysis,predict_clip
from segment_battles import file_sha256,VERSION
import av


class ExtractionTests(unittest.TestCase):
    def test_non_frame_aligned_crop_preserves_source_pts_and_no_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);video=root/"source.mp4"
            with av.open(str(video),"w") as container:
                stream=container.add_stream("libx264",rate=10)
                stream.width,stream.height,stream.pix_fmt=160,180,"yuv420p"
                for index in range(30):
                    array=np.zeros((180,160,3),dtype=np.uint8);array[:,:,1]=80+index
                    frame=av.VideoFrame.from_ndarray(array,format="rgb24")
                    frame.pts=index;frame.time_base=Fraction(1,10)
                    for packet in stream.encode(frame):container.mux(packet)
                for packet in stream.encode():container.mux(packet)
            facts=encode_clip(video,{"id":"clip","start":.31,"end":1.39},[40,0,80,180],root/"clip")
            self.assertAlmostEqual(facts["source_start_seconds"],.4)
            self.assertEqual(facts["frames"],10)
            self.assertFalse(facts["audio_in_video"])
            with gzip.open(root/"clip/frame_alignment.jsonl.gz","rt",encoding="utf-8") as stream:
                rows=[json.loads(line) for line in stream]
            self.assertAlmostEqual(rows[0]["source_seconds"],.4)
            self.assertAlmostEqual(rows[-1]["source_seconds"],1.3)
            self.assertEqual(rows[0]["clip_seconds"],0)
            with av.open(str(root/"clip/video.mp4")) as container:
                frames=list(container.decode(video=0))
                self.assertEqual(len(frames),10)
                self.assertEqual((frames[0].width,frames[0].height),(80,180))
            self.assertEqual(file_sha256(root/"clip/video.mp4"),facts["video_sha256"])
            with self.assertRaises(FileExistsError):
                encode_clip(video,{"id":"clip","start":.31,"end":1.39},[40,0,80,180],root/"clip")

    def test_changed_source_is_rejected_before_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/"source.mp4";source.write_bytes(b"changed")
            manifest={"source_video":str(source),"source_sha256":"wrong","segments":[]}
            with self.assertRaises(ValueError):export_candidates(manifest,root/"library",viewport=[0,0,80,180])
            self.assertFalse((root/"library").exists())

    def test_existing_reviewed_clip_is_reused_without_media_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/"original.mp4";source.write_bytes(b"original")
            library=root/"battles";folder=library/"reviewed-01";folder.mkdir(parents=True)
            (folder/"video.mp4").write_bytes(b"saved clip")
            meta={"id":"reviewed-01","reference_id":"source","source_start_seconds":0,"source_end_seconds":100,"video_file":"video.mp4"}
            (folder/"battle.json").write_text(json.dumps(meta))
            candidate={"id":"source-auto-01","start":1,"end":99,"first_hud_seconds":5}
            manifest={"source_id":"source","source_video":str(source),"source_sha256":file_sha256(source),"detector":VERSION,"segments":[candidate]}
            with patch('extract_battles.encode_clip') as encode:
                result=export_candidates(manifest,library,viewport=[0,0,80,180])
                encode.assert_not_called()
            self.assertEqual(result[0]["id"],"reviewed-01")
            self.assertTrue(result[0]["reused_organized_clip"])
            self.assertEqual(json.loads((folder/"battle.json").read_text()),meta)
            self.assertTrue((folder/"boundary-candidates.json").exists())
            self.assertFalse((library/"source-auto-01").exists())

    def test_prior_analysis_archived_once_and_media_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            for name,data in [('video.mp4',b'media'),('viewer-data.json.gz',b'old readings'),('screen_readings.jsonl.gz',b'old raw')]:
                (folder/name).write_bytes(data)
            archive=archive_analysis(folder)
            self.assertEqual((folder/archive/'viewer-data.json.gz').read_bytes(),b'old readings')
            self.assertEqual((folder/archive/'screen_readings.jsonl.gz').read_bytes(),b'old raw')
            self.assertFalse((folder/archive/'video.mp4').exists())
            self.assertEqual(archive_analysis(folder),archive)
            self.assertEqual(len(list((folder/'analysis-archive').iterdir())),1)
            self.assertEqual((folder/'video.mp4').read_bytes(),b'media')


class PipelineTests(unittest.TestCase):
    def test_refresh_keeps_tracker_outputs_and_archives_old_readings(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            with av.open(str(folder/'video.mp4'),'w') as container:
                stream=container.add_stream('libx264',rate=10)
                stream.width,stream.height,stream.pix_fmt=80,180,'yuv420p'
                for index in range(3):
                    frame=av.VideoFrame.from_ndarray(np.zeros((180,80,3),dtype=np.uint8),format='rgb24')
                    frame.pts=index;frame.time_base=Fraction(1,10)
                    for packet in stream.encode(frame):container.mux(packet)
                for packet in stream.encode():container.mux(packet)
            meta={'id':'test','video_file':'video.mp4','source_start_seconds':0,'source_end_seconds':.3,'frames':3,'fps':10}
            (folder/'battle.json').write_text(json.dumps(meta))
            profile=folder/'profile.json';profile.write_text('{"templates":[]}')
            previous={'readings':[{'t':0,'old':True}], 'states':[{'t':0,'state':{'from':'tracker'}}],
                      'observations':[{'t':0,'look':{'my_species':'test'}}],
                      'events':[{'t':0,'event':{'kind':'tracker_event'}}], 'origin':4.8,'bookmarks':[]}
            old_bytes=gzip.compress(json.dumps(previous).encode())
            (folder/'viewer-data.json.gz').write_bytes(old_bytes)
            (folder/'screen_readings.jsonl.gz').write_bytes(b'old raw bytes')
            def detect(image,t,index,viewport):
                fields={name:{'value':None,'status':'unknown'} for name in ['species','cp','health_bar','shields_left','pokemon_left','energy']}
                return {'timestamp_seconds':t,'frame_index':index,'phase':{'value':None},'mine':fields,'opponent':fields,
                        'phase_estimate':{'value':'normal_fighting','status':'inferred'}}
            with patch('battle_reader.BattleReader') as reader,patch('battle_reader.EventTracker') as tracker,patch('local_ocr.LocalOCR'),patch('build_viewer.compact',side_effect=lambda row:{'t':row['timestamp_seconds']}):
                reader.return_value.detect.side_effect=detect
                tracker.return_value.update.side_effect=lambda row:[{'kind':'screen_cue','observed_at_seconds':row['timestamp_seconds']}]
                result=predict_clip(folder,profile)
            with gzip.open(folder/'viewer-data.json.gz','rt',encoding='utf-8') as stream:new=json.load(stream)
            for name in ['states','observations','events','origin']:
                self.assertEqual(new[name],previous[name])
            self.assertEqual(len(new['screen_events']),3)
            self.assertEqual(new['readings'][0]['phase_estimate']['status'],'inferred')
            self.assertEqual(result['decoded_frames'],3)
            archived=json.loads((folder/'battle.json').read_text())['prior_analysis_archive']
            self.assertEqual((folder/archived/'viewer-data.json.gz').read_bytes(),old_bytes)
            self.assertEqual((folder/archived/'screen_readings.jsonl.gz').read_bytes(),b'old raw bytes')

    def test_detect_reuses_original_and_validated_feature_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);video=root/"original.mp4";video.write_bytes(b"original media")
            profile=root/"layout.json";profile.write_text(json.dumps({"viewport":[0,0,508,1080]}))
            folder=root/"sources/youtube/example";folder.mkdir(parents=True)
            facts={"detector":VERSION,"source_sha256":file_sha256(video),"profile":json.loads(profile.read_text()),
                   "sample_interval_seconds":.5,"duration_seconds":30,"samples":[]}
            with gzip.open(folder/"segmentation-samples.json.gz","wt",encoding="utf-8") as stream:json.dump(facts,stream)
            source={"platform":"youtube","source_id":"example","media_file":"original.mp4","url":"https://example.test/video"}
            with patch('run_video_pipeline.import_source',return_value=source),patch('run_video_pipeline.scan_video') as scan:
                result=run_pipeline(source["url"],profile=profile,stage="detect",root=root)
                scan.assert_not_called()
            self.assertEqual(result["candidate_count"],0)
            self.assertEqual(result["source_sha256"],file_sha256(video))
            self.assertFalse(result["full_game_state_verified"])
            self.assertEqual(list(root.glob('*.mp4')),[video])
            video.write_bytes(b"replaced original")
            with patch('run_video_pipeline.import_source',return_value=source),patch('run_video_pipeline.scan_video') as scan:
                with self.assertRaises(ValueError):run_pipeline(source["url"],profile=profile,stage="detect",root=root)
                scan.assert_not_called()

    def test_unknown_recording_does_not_assume_known_creator_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source={"platform":"youtube","source_id":"unseen","media_file":"original.mp4","url":"https://example.test/video"}
            with patch('run_video_pipeline.import_source',return_value=source):
                with self.assertRaisesRegex(ValueError,'calibrated'):
                    run_pipeline(source["url"],stage="detect",root=root)


if __name__=="__main__":unittest.main()
