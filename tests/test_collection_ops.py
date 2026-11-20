import copy
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
from pathlib import Path
from scripts.recording.collection_ops import selected_manifest, digest, pin, verify_freeze, retire, write, finish

class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.witness=self.root/'witness.jpg'
        self.witness.write_bytes(b'frame evidence')
        self.manifest={'source_id':'123','views':{'pov':[{'id':'one','match_id':'match-1'}]}}
        self.review={'source_id':'123','decisions':[{'candidate_id':'one','league':'open_great_league',
            'in_game_league_evidence':{'context':'selected_league','reviewed_by':'reviewer',
                'witnesses':[{'file':str(self.witness),'sha256':digest(self.witness),'source_seconds':10}]}}]}
    def tearDown(self):self.tmp.cleanup()
    def test_selected_proof(self):
        self.assertEqual(selected_manifest(self.manifest,self.review,self.root)['export_selection']['clip_ids'],['one'])
    def test_duplicate(self):
        self.review['decisions']*=2
        with self.assertRaises(ValueError):selected_manifest(self.manifest,self.review,self.root)
    def test_option_not_selected(self):
        self.review['decisions'][0]['in_game_league_evidence']['context']='menu_option'
        with self.assertRaises(ValueError):selected_manifest(self.manifest,self.review,self.root)
    def test_wrong_source(self):
        self.review['source_id']='456'
        with self.assertRaises(ValueError):selected_manifest(self.manifest,self.review,self.root)
    def test_missing_decision(self):
        self.review['decisions']=[]
        with self.assertRaises(ValueError):selected_manifest(self.manifest,self.review,self.root)
    def test_changed_witness(self):
        self.witness.write_bytes(b'changed')
        with self.assertRaises(ValueError):selected_manifest(self.manifest,self.review,self.root)
    def test_outside_witness(self):
        with self.assertRaises(ValueError):selected_manifest(self.manifest,self.review,self.root/'other')
    def test_unknown_not_selected(self):
        self.review['decisions'][0]['league']='unknown'
        self.assertEqual(selected_manifest(self.manifest,self.review,self.root)['export_selection']['clip_ids'],[])
    def test_restricted_not_selected(self):
        self.review['decisions'][0]['league']='restricted_cup'
        self.assertEqual(selected_manifest(self.manifest,self.review,self.root)['export_selection']['clip_ids'],[])

class Retirement(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.source=self.root/'sources/twitch/123/video.mp4'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'complete synthetic source')
        self.witness=self.root/'witnesses/123/frame.jpg'
        self.witness.parent.mkdir(parents=True)
        self.witness.write_bytes(b'selected cup witness')
        self.review={'source_id':'123','decisions':[{'candidate_id':'one','league':'restricted_laic_cup',
            'in_game_league_evidence':{'context':'selected_league','reviewed_by':'reviewer','witnesses':[
                {'file':str(self.witness),'sha256':digest(self.witness),'source_seconds':10}]}}]}
        base={'source_id':'123','views':{'pov':[{'id':'one','match_id':'match-1'}]},
            'fingerprint':{'source_sha256':digest(self.source)},'scan_coverage':{'full_recording_scanned':True}}
        self.manifest=selected_manifest(base,self.review,self.root/'witnesses/123')
        write(self.root/'runs/123/battle-candidates.json',self.manifest)
        write(self.root/'runs/123/league-review.json',self.review)
        write(self.source.parent/'source.json',{'upload_date':'20261119'})
    def tearDown(self):self.tmp.cleanup()
    def call(self):
        with patch('scripts.recording.collection_ops.worker_root',return_value=self.root),patch('scripts.recording.collection_ops.verify_freeze',return_value={'unchanged':True}):
            return retire('worker-b','123')
    def test_zero_accepted_source_retired(self):
        receipt=self.call()
        self.assertTrue(receipt['deleted'])
        self.assertEqual(receipt['reason'],'no_eligible_battles')
        self.assertFalse(self.source.exists())
        self.assertTrue(self.witness.exists())
    def test_unresolved_source_retained(self):
        self.manifest['league_review_completed']=False
        write(self.root/'runs/123/battle-candidates.json',self.manifest)
        with self.assertRaises(ValueError):self.call()
        self.assertTrue(self.source.exists())
    def test_changed_source_retained(self):
        self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.call()
        self.assertTrue(self.source.exists())
    def test_changed_review_after_retirement_preserves_saved_provenance(self):
        self.call()
        path=self.root/'runs/123/league-review.json'
        before=path.read_bytes()
        changed=copy.deepcopy(self.review)
        changed['decisions'][0]['league']='restricted_cup'
        alternative=self.root/'changed-review.json'
        write(alternative,changed)
        modules={'vod_verify':SimpleNamespace(verify=Mock()),
                 'vod_track':SimpleNamespace(read_clip=Mock(),track_clip=Mock()),
                 'game_record':SimpleNamespace(write=Mock())}
        with patch('scripts.recording.collection_ops.worker_root',return_value=self.root),\
             patch('scripts.recording.collection_ops.frozen_modules',return_value=SimpleNamespace()),\
             patch.dict(sys.modules,modules),self.assertRaises(ValueError):
            finish('worker-b','123',alternative)
        self.assertEqual(path.read_bytes(),before)
    def test_tracking_after_source_retired_never_exports_again(self):
        self.review['decisions'][0]['league']='open_great_league'
        self.manifest['fingerprint']['layout']={'channel':'itsaxn','views':[{'id':'pov'}]}
        self.manifest['url']='https://www.twitch.tv/videos/123'
        self.manifest=selected_manifest(self.manifest,self.review,self.root/'witnesses/123')
        write(self.root/'runs/123/battle-candidates.json',self.manifest)
        write(self.root/'runs/123/league-review.json',self.review)
        folder=self.root/'cuts/one'
        folder.mkdir(parents=True)
        (folder/'video.mp4').write_bytes(b'synthetic retained cut')
        (folder/'frame_alignment.jsonl.gz').write_bytes(b'synthetic alignment')
        write(folder/'battle.json',{'video_file':'video.mp4','video_sha256':digest(folder/'video.mp4')})
        write(self.root/'runs/123/media-validation.json',{'media_checks_passed':True,'checked_clips':[{'id':'one'}]})
        self.call()
        self.assertFalse(self.source.exists())
        export=Mock(side_effect=AssertionError('must not export after retirement'))
        validate=Mock(side_effect=AssertionError('must use retained verification receipt'))
        read=Mock()
        track=Mock(return_value={'creator_game_folder':'records/itsaxn/fake'})
        def render(path):
            path.mkdir(parents=True,exist_ok=True)
            write(path/'game.json',{'schema':'synthetic-test'})
            (path/'game.txt').write_text('synthetic test')
        modules={'vod_verify':SimpleNamespace(verify=validate),'vod_track':SimpleNamespace(read_clip=read,track_clip=track),
            'game_record':SimpleNamespace(write=render)}
        with patch('scripts.recording.collection_ops.worker_root',return_value=self.root),patch('scripts.recording.collection_ops.FROZEN',self.root),\
             patch('scripts.recording.collection_ops.verify_freeze',return_value={'unchanged':True}),\
             patch('scripts.recording.collection_ops.frozen_modules',return_value=SimpleNamespace(export_one=export)),patch.dict(sys.modules,modules):
            finish('worker-b','123',self.root/'runs/123/league-review.json')
        read.assert_called_once()
        track.assert_called_once()
        export.assert_not_called()
        validate.assert_not_called()
        self.assertFalse(self.source.exists())
        self.assertTrue(__import__('json').loads((self.root/'receipts/123.json').read_text())['source_retired'])

if __name__=='__main__':unittest.main()
