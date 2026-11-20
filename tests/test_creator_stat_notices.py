import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_stat_notices import parse,collect,StatNoticeEvidence


def rows():
    return [dict(t=10,text=[['caption','DEFENSE FELL!']])],{10:dict(clip_seconds=10.016,source_pts=30048,source_time_base='1/3000')}


def state():
    def mon():return dict(attack_stage=dict(value=0),defense_stage=dict(value=0))
    return {s:dict(active='active',pokemon={'active':mon(),'bench':mon()}) for s in ('mine','opponent')}


class LiteralStatNotices(unittest.TestCase):
    def event(self):return collect(*rows())['events'][0]

    def test_only_complete_literal_banners_are_classified(self):
        self.assertEqual(parse(' DEFENSE FELL! ')['direction'],'decrease')
        self.assertEqual(parse('Attack rose.')['stat'],'attack_stage')
        for text in ('Attack incoming!','Defense fell for someone','used Defense Fell','rose','',None):
            self.assertIsNone(parse(text),text)

    def test_modifiers_are_retained_without_assuming_magnitude(self):
        for text in ('ATTACK ROSE SHARPLY!','Defense harshly fell!','Attack drastically rose!'):
            self.assertIsNotNone(parse(text)['wording_modifier'])
            self.assertIsNone(parse(text)['stage_delta'])

    def test_source_frame_alignment_is_required(self):
        text,alignment=rows();event=collect(text,alignment)['events'][0]
        self.assertEqual(event['t'],10.016)
        self.assertEqual(event['source_pts'],30048)
        self.assertFalse(collect(text,{})['events'])

    def test_duplicate_samples_do_not_invent_additional_stat_changes(self):
        text,alignment=rows()
        for at in (10,11,12,15):
            text.append(dict(t=at,text=[['caption','DEFENSE FELL!']]))
            alignment[at]=dict(clip_seconds=at+.016,source_pts=int(at*3000)+48,source_time_base='1/3000')
        self.assertEqual(len(collect(text,alignment)['events']),2)

    def test_unattributed_banner_invalidates_active_stat_without_touching_bench_or_other_stat(self):
        sides=state();notice=StatNoticeEvidence([self.event()])
        self.assertFalse(notice.advance(10,sides))
        self.assertEqual(len(notice.advance(10.016,sides)),2)
        for team in sides.values():
            self.assertIsNone(team['pokemon']['active']['defense_stage']['value'])
            self.assertEqual(team['pokemon']['active']['attack_stage']['value'],0)
            self.assertEqual(team['pokemon']['bench']['defense_stage']['value'],0)
        self.assertFalse(notice.advance(10.02,sides))

    def test_old_banner_cannot_invalidate_a_later_replacement(self):
        sides=state()
        self.assertFalse(StatNoticeEvidence([self.event()]).advance(11,sides))
        self.assertEqual(sides['mine']['pokemon']['active']['defense_stage']['value'],0)

    def test_missing_or_fainted_active_is_not_modified(self):
        sides=state();sides['mine']['active']=None
        sides['opponent']['pokemon']['active']['fainted']=dict(value=True)
        self.assertFalse(StatNoticeEvidence([self.event()]).advance(10.016,sides))

    def test_bad_source_or_invented_target_and_magnitude_are_rejected(self):
        for update in (dict(source_pts=True),dict(source_time_base='0'),dict(source_time_base='1/0'),
                       dict(t=float('nan')),dict(confirmed_at_seconds=11),dict(side='mine'),
                       dict(target_identity='Mimikyu:1498'),dict(stage_delta=-1),dict(stat='energy')):
            event=copy.deepcopy(self.event());event.update(update)
            self.assertFalse(StatNoticeEvidence([event]).events,update)

    def test_client_wording_distinguishes_single_and_double_step_messages(self):
        for text,steps,resource in [('Attack rose!',[1],'combat_buff_lvl1'),
                ('Defense fell!',[-1],'combat_debuff_lvl1'),
                ('Attack rose sharply!',[2],'combat_buff_lvl2'),
                ('Defense harshly fell!',[-2],'combat_debuff_lvl2')]:
            notice=parse(text)
            self.assertEqual(notice['message_change_step_candidates'],steps)
            self.assertEqual(notice['wording_resource_id'],resource)
            self.assertIsNone(notice['stage_delta'])

    def test_severe_message_retains_larger_change_ambiguity(self):
        self.assertEqual(parse('Defense severely fell!')['message_change_step_candidates'],[-4,-3])
        self.assertEqual(parse('Attack rose drastically!')['message_change_step_candidates'],[3,4])
        self.assertIsNone(parse('Defense severely fell!')['stage_delta'])

    def test_incompatible_modifier_and_direction_are_not_game_messages(self):
        for text in ('Attack harshly rose!','Defense fell sharply!','Defense severely rose!'):
            self.assertIsNone(parse(text))
