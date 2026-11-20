import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
import collection_exclusion as ex
import collection_ops as ops


class ExclusionGuards(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.run=self.root/'runs/123'
        self.video=self.root/'sources/twitch/123/video.mp4'
        self.video.parent.mkdir(parents=True)
        self.video.write_bytes(b'full synthetic source')
        self.sha=ops.digest(self.video)
        self.frame=self.root/'witnesses/123/frame.jpg'
        self.frame.parent.mkdir(parents=True)
        self.frame.write_bytes(b'LAIC selected frame')
        self.manifest={'source_id':'123','views':{'pov':[{'id':'one','start':20,'end':70,'match_id':'m1'}]}}
        self.review={'source_id':'123','source_sha256':self.sha,'context_coverage_reviewed':True,'league_change_review_complete':True,
            'decisions':[{'candidate_id':'one','league':'restricted_laic_cup','in_game_league_evidence':{
                'context':'selected_league','reviewed_by':'assistant manual source-frame review',
                'witnesses':[{'file':str(self.frame),'sha256':ops.digest(self.frame),'source_seconds':10}]},
                'continuity_review':{'from_source_seconds':10,'to_source_seconds':80,'unresolved_transitions':0,
                    'method':'full_coarse_context_and_source_frames'}}]}
        self.frozen=self.root/'frozen'
        self.stop={'source_id':'123','worker':'worker-b','post_stop_cim_verified':True,'remaining_owned_processes':[],'processes':[{'pid':999999,
            'command_line':str((self.frozen/'scripts/recording/vod.py').resolve())+' https://www.twitch.tv/videos/123 --run-dir '+str(self.run.resolve()),
            'verified_before_stop':True,'stopped':True}]}
        self.decoder={'source_id':'123','source_sha256':self.sha,'decoder_provenance_resolved':True,'actual_disagreement':False,
            'all_hashes_agree_per_requested_timestamp':True,'source_replacement_ruled_out':True,'native_matrix_samples':6,
            'matrix_files':[{'file':str(self.frame),'sha256':ops.digest(self.frame)}]}
        self.review_path=self.root/'review.json';ops.write(self.review_path,self.review)
        self.decoder_path=self.root/'decoder.json';ops.write(self.decoder_path,self.decoder)
        self.stop_path=self.root/'stop.json';ops.write(self.stop_path,self.stop)
        ops.write(self.video.parent/'source.json',{'media':{'sha256':self.sha,'duration_seconds':100},'upload_date':'20261119'})
        self.run.mkdir(parents=True)
        self.scan={'fingerprint':{'source_sha256':self.sha},'duration_seconds':100,'views':{}}
        self.save_scan()
    def tearDown(self):self.tmp.cleanup()
    def save_scan(self):
        with gzip.open(self.run/'coarse-scan.json.gz','wt') as f:json.dump(self.scan,f)
    def validate(self):return ex.validate_nonopen(self.manifest,self.review,self.root/'witnesses/123',100)
    def execute(self,retire=True):
        with patch.object(ops,'worker_root',return_value=self.root),patch.object(ops,'FROZEN',self.frozen),\
            patch.object(ops,'verify_freeze',return_value={'files_checked':511,'unchanged':True}),\
            patch.object(ex,'candidate_manifest',return_value=self.manifest),patch.object(ex,'inactive',return_value=True):
            return ex.exclude('worker-b','123',self.review_path,self.decoder_path,self.stop_path,retire=retire)
    def test_nonopen_context_accepted(self):self.assertTrue(self.validate()['league_review_completed'])
    def test_actual_master_mega_category_accepted(self):
        self.review['decisions'][0]['league']='mega_master_league'
        self.assertTrue(self.validate()['league_review_completed'])
    def test_actual_ultra_mega_category_accepted(self):
        self.review['decisions'][0]['league']='mega_ultra_league'
        self.assertTrue(self.validate()['league_review_completed'])
    def test_open_refused(self):
        self.review['decisions'][0]['league']='open_great_league'
        with self.assertRaises(ValueError):self.validate()
    def test_unknown_refused(self):
        self.review['decisions'][0]['league']='unknown'
        with self.assertRaises(ValueError):self.validate()
    def test_unreviewed_context_refused(self):
        self.review['context_coverage_reviewed']=False
        with self.assertRaises(ValueError):self.validate()
    def test_unrecognized_league_refused(self):
        self.review['decisions'][0]['league']='definitely_not_open'
        with self.assertRaises(ValueError):self.validate()
    def test_context_gap_refused(self):
        self.review['decisions'][0]['continuity_review']['to_source_seconds']=69
        with self.assertRaises(ValueError):self.validate()
    def test_future_witness_refused(self):
        self.review['decisions'][0]['in_game_league_evidence']['witnesses'][0]['source_seconds']=21
        with self.assertRaises(ValueError):self.validate()
    def test_active_process_refused(self):
        with self.assertRaises(ValueError):ex.validate_stop(self.stop,worker='worker-b',sid='123',run=self.run,frozen=self.frozen,is_inactive=lambda _:False)
    def test_unchecked_descendants_refused(self):
        self.stop['post_stop_cim_verified']=False
        with self.assertRaises(ValueError):ex.validate_stop(self.stop,worker='worker-b',sid='123',run=self.run,frozen=self.frozen,is_inactive=lambda _:True)
    def test_active_orchestrator_refused(self):
        self.stop['processes'][0]['parent_pid']=999998
        self.stop['orchestrators']=[{'pid':999998,'command_line':str((ops.REPO/'scripts/recording/collection_ops.py').resolve())+' detect --worker worker-b --source-id 123','verified_before_stop':True,'stopped':True}]
        with self.assertRaises(ValueError):ex.validate_stop(self.stop,worker='worker-b',sid='123',run=self.run,frozen=self.frozen,is_inactive=lambda p:p!=999998)
    def test_other_worker_process_refused(self):
        self.stop['processes'][0]['command_line']='other reader https://www.twitch.tv/videos/123'
        with self.assertRaises(ValueError):ex.validate_stop(self.stop,worker='worker-b',sid='123',run=self.run,frozen=self.frozen,is_inactive=lambda _:True)
    def test_only_pinned_legacy_a_wrapper_accepted(self):
        wrapper=self.root/'helpers/worker_a_detect.py'
        wrapper.parent.mkdir()
        wrapper.write_bytes(b'synthetic inspected wrapper')
        row=self.stop['processes'][0]
        row.update(command_line=str(wrapper)+' 123',legacy_wrapper=str(wrapper),owned_run_dir=str(self.run))
        self.stop['worker']='worker-a'
        with patch.object(ops,'BASE',self.root),patch.object(ex,'LEGACY_A_WRAPPER_SHA256',ops.digest(wrapper)):
            ex.validate_stop(self.stop,worker='worker-a',sid='123',run=self.run,frozen=self.frozen,is_inactive=lambda _:True)
        wrapper.write_bytes(b'changed wrapper')
        with patch.object(ops,'BASE',self.root):
            with self.assertRaises(ValueError):ex.validate_stop(self.stop,worker='worker-a',sid='123',run=self.run,frozen=self.frozen,is_inactive=lambda _:True)
    def test_exact_source_retired_without_fake_reader_pass(self):
        receipt=self.execute()
        self.assertTrue(receipt['done']);self.assertTrue(receipt['source_retired'])
        self.assertFalse(receipt['reader_detection_completed']);self.assertFalse(self.video.exists())
        self.assertTrue(self.frame.exists());self.assertTrue(self.review_path.exists())
    def test_changed_source_retained(self):
        self.video.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.execute()
        self.assertTrue(self.video.exists())
    def test_wrong_review_source_retained(self):
        self.review['source_sha256']='f'*64;ops.write(self.review_path,self.review)
        with self.assertRaises(ValueError):self.execute()
        self.assertTrue(self.video.exists())
    def test_capped_source_retained(self):
        self.scan['duration_seconds']=50;self.save_scan()
        with self.assertRaises(ValueError):self.execute()
        self.assertTrue(self.video.exists())
    def test_source_suffix_retained(self):
        self.scan['fingerprint']['scan_start_seconds']=5;self.save_scan()
        with self.assertRaises(ValueError):self.execute()
        self.assertTrue(self.video.exists())
    def test_unresolved_decoder_retained(self):
        self.decoder['actual_disagreement']=True;ops.write(self.decoder_path,self.decoder)
        with self.assertRaises(ValueError):self.execute()
        self.assertTrue(self.video.exists())


if __name__=='__main__':unittest.main()
