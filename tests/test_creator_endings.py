"""Creator-only evidence adapters retain zero bars and counter-only observations."""
import copy,gzip,json,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from vod_track import confirmed_empty_bars,creator_readings,retain_counter_looks,rows,track_clip

def packed(path,values):
 path.write_bytes(gzip.compress(''.join(json.dumps(v)+'\n'for v in values).encode(),mtime=0))

class Evidence(unittest.TestCase):
 def test_uncorroborated_empty_bar_does_not_invent_health_or_faints(self):
  with tempfile.TemporaryDirectory()as tmp:
   raw=Path(tmp);side={'hp':0,'seg':[],'w':144,'left':1};unknown={'hp':None,'seg':None,'w':None,'left':1}
   values=[{'t':25,'m':side,'o':unknown,'result':None}];packed(raw/'readings-refined.jsonl.gz',values);before=(raw/'readings-refined.jsonl.gz').read_bytes()
   packed(raw/'text.jsonl.gz',[{'t':25,'text':[['middle','YOU WIN!']]}]);path,audit=creator_readings(raw);actual=list(rows(path))[0]
   self.assertEqual(actual['m']['seg'],[]);self.assertIsNone(actual['o']['seg']);self.assertEqual(actual['o']['left'],1)
   self.assertEqual(audit['empty_bar_measurements_preserved'],[])
   self.assertEqual(len(audit['uncorroborated_empty_bars_ignored']),1)
   self.assertEqual(actual['result'],'win');self.assertEqual(audit['knockouts_inferred_from_result'],0);self.assertEqual(before,(raw/'readings-refined.jsonl.gz').read_bytes())
 def test_split_result_words_and_surrender_are_evidence_not_faints(self):
  with tempfile.TemporaryDirectory()as tmp:
   raw=Path(tmp);side={'hp':.5,'seg':[['cyan',72]],'w':144,'left':2}
   packed(raw/'readings-refined.jsonl.gz',[{'t':25,'m':side,'o':side,'result':None},{'t':26,'m':side,'o':side,'result':None}])
   packed(raw/'text.jsonl.gz',[{'t':25,'text':[['middle','Surrender and exit?']]},{'t':26,'text':[['middle','GOOD'],['middle','EFFORT!']]}]);path,audit=creator_readings(raw);actual=list(rows(path))
   self.assertEqual(actual[1]['result'],'loss');self.assertEqual(actual[1]['m']['left'],2);self.assertEqual(audit['surrender_dialog_seconds'],[25])
 def test_non_result_and_opening_result_do_not_change_the_game(self):
  with tempfile.TemporaryDirectory()as tmp:
   raw=Path(tmp);side={'hp':None,'seg':[],'w':None,'left':3};values=[{'t':t,'m':side,'o':side,'result':None}for t in [2,25]]
   packed(raw/'readings-refined.jsonl.gz',values);packed(raw/'text.jsonl.gz',[{'t':2,'text':[['middle','YOU WIN!']]},{'t':25,'text':[['middle','YOU WINNER']]}]);path,audit=creator_readings(raw)
   self.assertTrue(all(v['result']is None for v in rows(path)));self.assertEqual(audit['result_evidence'],[])
 def test_counter_only_tail_is_retained_and_does_not_revive_a_party(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);(root/'timeline.json').write_text(json.dumps({'clip_origin_seconds':5,'end':25}));looks=[{'t':0,'my_left':3,'foe_left':3},{'t':18,'my_left':3,'foe_left':3}]
   (root/'observations.jsonl').write_text(''.join(json.dumps(v)+'\n'for v in looks));values=[{'t':i/3,'m':{'left':3 if i<54 else 2},'o':{'left':3}}for i in range(91)];packed(root/'readings.gz',values)
   retain_counter_looks(root,root/'readings.gz');actual=[json.loads(l)for l in (root/'observations.jsonl').read_text().splitlines()]
   self.assertTrue(any(13<r['t']<14 and r.get('my_left')==2 for r in actual));self.assertEqual(actual[-1]['my_left'],2);self.assertTrue(all(r.get('foe_left',3)>0 for r in actual))
 def bar_fixture(self):
  readings=[];rich=[]
  for i in range(12):
   t=round(i/3,6);hp=0 if i==6 else .05
   readings.append({'t':t,'m':{'left':3 if i<6 else 2,'hp':hp,'seg':[] if hp==0 else [['cyan',7]],'w':138},'o':{'left':3}})
   rich.append({'timestamp_seconds':t,'mine':{'health_bar':{'value':{'bounds_px':[30,690,174,704]}}}})
  return readings,rich
 def test_zero_requires_local_counter_drop_and_matching_previous_bar(self):
  readings,rich=self.bar_fixture()
  self.assertEqual(confirmed_empty_bars(readings,rich),{(2.0,'m')})
  rich[6]['mine']['health_bar']['value']['bounds_px']=[80,540,224,554]
  self.assertEqual(confirmed_empty_bars(readings,rich),set())
 def test_zero_rejects_counter_gaps_and_missing_previous_health(self):
  readings,rich=self.bar_fixture();readings[7]['m']['left']=None;readings[9]['m']['left']=None
  self.assertEqual(confirmed_empty_bars(readings,rich),set())
  readings,rich=self.bar_fixture();readings[5]['m']['hp']=None
  self.assertEqual(confirmed_empty_bars(readings,rich),set())
 def test_failed_replay_cannot_publish_stale_states_with_new_error(self):
  with tempfile.TemporaryDirectory()as tmp:
   folder=Path(tmp)/'clip';folder.mkdir();(folder/'battle.json').write_text('{}')
   exported=Path(tmp)/'exports';exported.mkdir();prior=exported/'game.json';prior.write_text('{"baseline":true}')
   with patch('vod_track.bootstrap'),patch('vod_markers.refine',side_effect=ValueError('bad source')),patch('vod_track.publish')as publish,patch('vod_track.creator_export')as export:
    with self.assertRaisesRegex(RuntimeError,'previous export retained'):track_clip(folder,Path(tmp),creator_root=exported)
    publish.assert_not_called();export.assert_not_called()
   self.assertEqual(prior.read_text(),'{"baseline":true}')
   self.assertFalse(json.loads((folder/'tracker/tracking-error.json').read_text())['creator_export_updated'])

if __name__=='__main__':unittest.main()
