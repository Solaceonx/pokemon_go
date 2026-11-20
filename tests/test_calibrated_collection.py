import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
import calibrated_collection as cal
import collection_ops as ops


class CalibrationReview(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.evidence=self.root/'witnesses/123';self.evidence.mkdir(parents=True)
        self.frame=self.evidence/'source.jpg';self.frame.write_bytes(b'physical source witness')
        self.witness={'file':str(self.frame),'sha256':ops.digest(self.frame),'source_seconds':9}
        self.profiles=self.root/'profiles';self.profiles.mkdir();(self.profiles/'henry-great.json').write_text('{}')
        self.sha='1'*64
        self.source={'source_id':'123','creator':'ItsAXN','media':{'sha256':self.sha,'width':1920,'height':1080,'duration_seconds':100}}
        self.layout={'schema':'creator-source-calibration-v1','source_id':'123','source_sha256':self.sha,'channel':'itsaxn',
            'source_kind':'direct_creator_phone','broadcast_regions':[],'manual_context_review_required':True,'reviewed_by':'assistant source-frame review',
            'frame_size':[1920,1080],'views':[{'id':'pov','base_profile':'henry-great.json','viewport':[706,0,508,1080]}],
            'witnesses':[self.witness,{**self.witness,'source_seconds':90}]}
        self.raw=[{'id':'frag1','source_id':'123','start':10,'end':20,'first_hud_seconds':11,'notes':[]},
                  {'id':'frag2','source_id':'123','start':30,'end':40,'first_hud_seconds':31,'notes':[]}]
        self.pending={'source_id':'123','scan_coverage':{'source_seconds':100},'fingerprint':{'source_sha256':self.sha,'layout':{'channel':'itsaxn'}},'views':{'pov':self.raw}}
        self.review={'source_id':'123','source_sha256':self.sha,'whole_coarse_context_reviewed':True,'replays_reviewed':True,
            'layout_changes_reviewed':True,'reviewed_by':'assistant source-frame review','battles':[{
                'raw_fragment_ids':['frag1','frag2'],'start':9,'end':41,'replay_status':'direct_phone','layout_status':'consistent',
                'all_internal_gaps_reviewed':True,'all_visible_boundaries_reviewed':True,'context_witnesses':[self.witness],
                'gap_reviews':[{'start':20,'end':30,'continuous_same_battle':True,'witnesses':[{**self.witness,'source_seconds':25}]}],
                'boundary_evidence':{'start':{'status':'visible_go','witnesses':[self.witness]},
                    'end':{'status':'visible_result','witnesses':[{**self.witness,'source_seconds':41}]}},
                'observed_go_seconds':[9],'observed_result_seconds':[41]}]}
    def tearDown(self):self.tmp.cleanup()
    def validate_layout(self):return cal.validate_layout(self.layout,self.source,self.evidence,self.profiles)
    def approve(self):return cal.review_battles(self.pending,self.review,self.evidence)
    def test_real_source_channel_preserved_with_shared_pixel_profile(self):
        self.assertEqual(self.validate_layout()['channel'],'itsaxn')
    def test_creator_name_cannot_fake_another_layout_channel(self):
        self.layout['channel']='homeslicehenry'
        with self.assertRaises(ValueError):self.validate_layout()
    def test_no_invented_full_chat_replay_region(self):
        self.layout['broadcast_regions']=[{'kind':'replay','rect':[0,0,1920,1080]}]
        with self.assertRaises(ValueError):self.validate_layout()
    def test_frozen_profile_overrides_refused(self):
        self.layout['views'][0]['overrides']={'threshold':0}
        with self.assertRaises(ValueError):self.validate_layout()
    def test_crop_outside_recording_refused(self):
        self.layout['views'][0]['viewport']=[1900,0,508,1080]
        with self.assertRaises(ValueError):self.validate_layout()
    def test_wrong_source_bytes_refused(self):
        self.layout['source_sha256']='2'*64
        with self.assertRaises(ValueError):self.validate_layout()
    def test_changed_layout_source_witness_refused(self):
        self.frame.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.validate_layout()
    def test_two_fragments_become_one_continuous_battle_including_animation_gap(self):
        before=copy.deepcopy(self.pending)
        battles=self.approve()
        self.assertEqual(len(battles),1)
        self.assertEqual((battles[0]['start'],battles[0]['end']),(9,41))
        self.assertEqual(battles[0]['raw_fragment_ids'],['frag1','frag2'])
        self.assertEqual(self.pending,before)
    def test_charged_animation_gap_cannot_be_removed(self):
        self.review['battles'][0]['end']=20
        with self.assertRaises(ValueError):self.approve()
    def test_missing_raw_fragment_refused(self):
        self.review['battles'][0]['raw_fragment_ids']=['frag1']
        with self.assertRaises(ValueError):self.approve()
    def test_duplicate_fragment_assignment_refused(self):
        self.review['battles'].append(copy.deepcopy(self.review['battles'][0]))
        with self.assertRaises(ValueError):self.approve()
    def test_two_observed_go_events_cannot_be_merged(self):
        self.review['battles'][0]['observed_go_seconds']=[9,29]
        with self.assertRaises(ValueError):self.approve()
    def test_unresolved_replay_is_not_exportable(self):
        self.review['battles'][0]['replay_status']='unknown'
        with self.assertRaises(ValueError):self.approve()
    def test_unresolved_layout_is_not_exportable(self):
        self.review['battles'][0]['layout_status']='changed'
        with self.assertRaises(ValueError):self.approve()
    def test_unreviewed_internal_gaps_refused(self):
        self.review['battles'][0]['all_internal_gaps_reviewed']=False
        with self.assertRaises(ValueError):self.approve()
    def test_missing_animation_gap_witness_refused(self):
        self.review['battles'][0]['gap_reviews']=[]
        with self.assertRaises(ValueError):self.approve()
    def test_unreviewed_visible_boundaries_refused(self):
        self.review['battles'][0]['all_visible_boundaries_reviewed']=False
        with self.assertRaises(ValueError):self.approve()
    def test_clipped_beginning_and_end_remain_allowed(self):
        row=self.review['battles'][0]
        row['boundary_evidence']={'start':{'status':'clipped'},'end':{'status':'clipped'}}
        row['observed_go_seconds']=[];row['observed_result_seconds']=[]
        battle=self.approve()[0]
        self.assertTrue(battle['incomplete_start']);self.assertTrue(battle['incomplete_end'])
        self.assertFalse(battle['eligible_for_complete_battle_evaluation'])
    def test_changed_review_artifact_blocks_export(self):
        proof=self.root/'review.json';proof.write_bytes(b'approved source boundaries')
        manifest={'schema':'source-calibrated-reviewed-battles-v1','source_calibration_proofs_sha256':{'review.json':ops.digest(proof)}}
        with patch.object(ops,'BASE',self.root):
            ops.verify_source_calibration_proofs(manifest)
            proof.write_bytes(b'edited after approval')
            with self.assertRaises(ValueError):ops.verify_source_calibration_proofs(manifest)
    def test_no_approval_artifact_cannot_be_exported(self):
        with self.assertRaises(ValueError):ops.verify_source_calibration_proofs({'schema':'source-calibrated-reviewed-battles-v1'})
    def test_prepare_is_pending_until_manual_review_compiles_one_continuous_battle(self):
        source_dir=self.root/'sources/twitch/123';source_dir.mkdir(parents=True)
        video=source_dir/'video.mp4';video.write_bytes(b'synthetic normalized source')
        source=copy.deepcopy(self.source)
        source.update(platform='twitch',url='https://www.twitch.tv/videos/123')
        source['media'].update(sha256=ops.digest(video),container='mov,mp4',container_start_seconds=0)
        layout=copy.deepcopy(self.layout);layout['source_sha256']=source['media']['sha256']
        review=copy.deepcopy(self.review);review['source_sha256']=source['media']['sha256']
        ops.write(source_dir/'source.json',source)
        layout_path=self.root/'layout.json';ops.write(layout_path,layout)
        review_path=self.root/'manual-review.json'
        frozen=self.root/'frozen'
        for folder,names in [(frozen/'scripts/recording',['vod.py','vod_media.py','vod_segments.py','vod_broadcast.py','vod_layout.py','vod_fixture.py']),
            (frozen/'screen_reader',['segment_battles.py','extract_battles.py','local_ocr.py']),
            (frozen/'screen_reader/profiles',['henry-great.json'])]:
            folder.mkdir(parents=True,exist_ok=True)
            for name in names:(folder/name).write_text('{}')
        profiles={'pov':{'viewport':[706,0,508,1080]}}
        scan={'duration_seconds':100,'fingerprint':{'source_sha256':source['media']['sha256'],'profiles':profiles},'views':{'pov':[]}}
        def coarse(video,profiles,path):
            with gzip.open(path,'wt',encoding='utf8') as stream:json.dump(scan,stream)
            return scan
        modules={'vod_segments':SimpleNamespace(VERSION='frozen-version',profiles_for=Mock(return_value=profiles),
            coarse_scan=Mock(side_effect=coarse),discover_segments=Mock(return_value=self.raw),annotate_segments=Mock(return_value=self.raw)),
            'vod_broadcast':SimpleNamespace(marker_scan=Mock(side_effect=AssertionError('No invented full-chat scan')))}
        with patch.object(ops,'BASE',self.root),patch.object(ops,'FROZEN',frozen),patch.object(ops,'worker_root',return_value=self.root),\
             patch.object(ops,'frozen_modules',return_value=SimpleNamespace()),patch.object(ops,'verify_freeze',return_value={'unchanged':True}),\
             patch.dict(sys.modules,modules):
            prepared=cal.prepare('worker-b','123',layout_path)
            canonical=self.root/'runs/123/battle-candidates.json'
            self.assertFalse(prepared['exportable']);self.assertFalse(canonical.exists())
            pending_path=self.root/'runs/123/calibrated-v1/calibrated-candidates.pending.json'
            original=pending_path.read_bytes()
            review['replays_reviewed']=False;ops.write(review_path,review)
            with self.assertRaises(ValueError):cal.approve('worker-b','123',review_path)
            self.assertFalse(canonical.exists())
            review['replays_reviewed']=True;ops.write(review_path,review)
            approved=cal.approve('worker-b','123',review_path)
            manifest=ops.load(canonical)
            self.assertEqual(approved['raw_fragments'],2)
            self.assertEqual(approved['reviewed_continuous_battles'],1)
            self.assertEqual((manifest['views']['pov'][0]['start'],manifest['views']['pov'][0]['end']),(9,41))
            self.assertEqual(pending_path.read_bytes(),original)
            self.assertFalse(manifest['broadcast_label_scan_performed'])
            self.assertFalse(manifest['full_game_state_verified'])
            ops.verify_source_calibration_proofs(manifest)


if __name__=='__main__':unittest.main()
