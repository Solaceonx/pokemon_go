import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/recording'))
from creator_sources import classify,league_from_title
from creator_analysis import energy_bucket,clustered_difference
from vod_track import without_raw_text,creator_export
from vod_segments import discover_segments
from vod import reuse_existing_candidates


class CreatorFootage(unittest.TestCase):
    def test_live_and_non_battle_listings_are_not_completed_battle_sources(self):
        self.assertEqual(classify({'title':'Great League','is_live':True},'twitch')[0],'excluded')
        self.assertEqual(classify({'title':'Great League tier list','duration':900},'youtube')[0],'excluded')
        self.assertEqual(classify({'title':'GBL battle footage','duration':900},'youtube')[0],'candidate')
        self.assertEqual(league_from_title('UL battles'),'Ultra League')
        self.assertEqual(league_from_title('hello'),'unknown')

    def test_unknown_energy_is_not_put_in_a_low_energy_habit_bucket(self):
        self.assertEqual(energy_bucket(None),'unknown')
        self.assertEqual(energy_bucket(30,50),'range_crosses_buckets')
        self.assertEqual(energy_bucket(40,50),'35-54')

    def test_difference_uncertainty_is_clustered_by_battle(self):
        rows=[{'game':'one','agree':False,'human_wins':0,'bot_wins':1} for _ in range(100)]
        rows += [{'game':'two','agree':False,'human_wins':1,'bot_wins':0}]
        result=clustered_difference(rows)
        self.assertEqual(result['battles'],2);self.assertEqual(result['mean'],0)
        self.assertLess(result['interval95'][0],0);self.assertGreater(result['interval95'][1],0)

    def test_unrestricted_ocr_and_trainer_fields_never_enter_creator_package(self):
        value={'species':'jumpluff','evidence':{'raw_text':'PRIVATE TRAINER','text':'OTHER NAME'},'trainer_name':'PRIVATE','nickname':'NAME'}
        safe=without_raw_text(value)
        self.assertNotIn('PRIVATE',json.dumps(safe));self.assertEqual(safe['species'],'jumpluff')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'local';game.mkdir();out=root/'public/itsaxn'
            (game/'team.json').write_text(json.dumps(value));(game/'text.json').write_text(json.dumps({'text':'PRIVATE'}))
            meta={'reference_id':'123','match_id':'tw-123-full-match-004-r12345678','view_id':'pov'}
            exported=creator_export(root,game,meta,out)
            self.assertEqual(exported.name,'123-004-r12345678')
            self.assertFalse((exported/'text.json').exists())
            self.assertNotIn('PRIVATE',(exported/'team.json').read_text())

    def test_short_lobby_with_starting_and_single_countdown_is_a_new_game(self):
        rows=[{'t':t,'hud':t<40 or t>=64,'party':[1,2] if t<40 else [2,3],
               'shields_total':None,'context_text':'Attack incoming!' if 40<=t<48 else '',
               'battle_starting':t==56,'countdown':{'digit':2,'confidence':.99} if t==62 else None}
              for t in range(120)]
        def legacy(facts,identity):return [{'start':0,'first_hud_seconds':0,'cues':[{'kind':'first_visible_hud'}]}]
        from types import SimpleNamespace
        with patch.dict(sys.modules,{'segment_battles':SimpleNamespace(propose_segments=legacy)}):
            clips=discover_segments(rows,'source',120)
            self.assertEqual(len(clips),2)
            self.assertEqual(clips[1]['first_hud_seconds'],64)
            rows[56]['battle_starting']=False
            self.assertEqual(len(discover_segments(rows,'source',120)),1)

    def test_new_split_cannot_steal_the_match_id_of_a_reused_later_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            view={'id':'pov','viewport':[0,0,508,1080]}
            fingerprint={'source_sha256':'source','reader_sha256':{'extract_battles.py':'reader'},'layout':{'views':[view]}}
            old={'id':'tw-1-full-pov-002','match_id':'tw-1-full-match-002','start':200,'end':300,'first_hud_seconds':201,
                 'view_id':'pov','completeness':'result_unseen_or_edited'}
            meta={'id':old['id'],'reference_id':'1','source_sha256':'source','view_id':'pov','source_viewport':view['viewport'],
                  'encoding_crf':23,'boundary_candidate':old,'vod_intake_fingerprint':fingerprint}
            folder=root/old['id'];folder.mkdir();(folder/'battle.json').write_text(json.dumps(meta))
            candidates={'pov':[
                {'match_id':'tw-1-match-001','view_id':'pov','start':0,'end':90,'first_hud_seconds':1},
                {'match_id':'tw-1-match-002','view_id':'pov','start':100,'end':190,'first_hud_seconds':101},
                {'match_id':'tw-1-match-003','view_id':'pov','start':200,'end':300,'first_hud_seconds':201}]}
            result=reuse_existing_candidates(candidates,root,fingerprint,'twitch','1')['pov']
            self.assertEqual(result[2]['id'],old['id'])
            self.assertEqual(result[2]['match_id'],old['match_id'])
            self.assertEqual(len({r['match_id'] for r in result}),3)


if __name__=='__main__':unittest.main()
