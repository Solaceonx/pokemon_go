import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_stage_resets import collect,StageResetEvidence


def inputs():
    old=dict(species='Golurk',cp=1490,confirmed_seconds=9.5,first_visible_seconds=5,
             source_pts=285,source_time_base='1/30')
    new=dict(species='Tinkaton',cp=1499,confirmed_seconds=10.2,first_visible_seconds=10,
             source_pts=306,source_time_base='1/30')
    identities=[dict(t=9.5,values={'mine':old}),dict(t=10.2,values={'mine':new})]
    raw=[dict(t=9.5,mine=dict(species='Golurk',cp=1490)),
         dict(t=10,mine=dict(species='Tinkaton',cp=1499)),
         dict(t=10.2,mine=dict(species='Tinkaton',cp=1499))]
    alignment={10.033333:dict(clip_seconds=10.033333333,source_pts=301,source_time_base='1/30')}
    return [[dict(t=10.033333,species='Tinkaton')],identities,raw,dict(charged=[]),[],alignment]


def team(event):
    def mon(name,cp):
        return dict(species={'value':name},cp={'value':cp},attack_stage={'value':None},defense_stage={'value':None})
    return dict(mine=dict(active=event['identity'],pokemon={event['identity']:mon('Tinkaton',1499),
        event['last_pre_entry_header_identity']:mon('Golurk',1490)}),opponent=dict(active=None,pokemon={}))


class SourceStageResets(unittest.TestCase):
    def event(self):return collect(*inputs())['events'][0]

    def test_literal_entry_changed_header_and_exact_source_frame_establish_reset(self):
        event=self.event()
        self.assertEqual(event['identity'],'Tinkaton:1499')
        self.assertEqual(event['last_pre_entry_header_identity'],'Golurk:1490')
        self.assertNotIn('previous_identity',event)
        self.assertEqual(event['exit_identity_status'],'unresolved')
        self.assertEqual(event['t'],10.033333333)
        self.assertEqual(event['confirmed_at_seconds'],10.2)
        self.assertEqual((event['attack_stage'],event['defense_stage']),(0,0))
        self.assertEqual(len(StageResetEvidence([event]).events),1)

    def test_first_clipped_header_and_a_header_without_go_do_not_reset(self):
        args=inputs();args[1]=args[1][1:]
        self.assertFalse(collect(*args)['events'])
        args=inputs();args[0]=[]
        self.assertFalse(collect(*args)['events'])

    def test_same_header_reappearance_cannot_erase_buff_history(self):
        args=inputs();args[1][0]['values']['mine'].update(species='Tinkaton',cp=1499)
        self.assertFalse(collect(*args)['events'])

    def test_two_same_species_with_different_cp_can_be_a_real_switch(self):
        args=inputs();args[0][0]['species']='Mimikyu'
        args[1][0]['values']['mine']['species']='Mimikyu'
        args[1][1]['values']['mine']['species']='Mimikyu'
        for r in args[2]:r['mine']['species']='Mimikyu'
        event=collect(*args)['events'][0]
        self.assertEqual((event['last_pre_entry_header_identity'],event['identity']),('Mimikyu:1490','Mimikyu:1499'))

    def test_two_possible_sides_are_not_resolved_from_a_roster(self):
        args=inputs()
        for r in args[1]:r['values']['theirs']=copy.deepcopy(r['values']['mine'])
        for r in args[2]:r['theirs']=copy.deepcopy(r['mine'])
        self.assertFalse(collect(*args)['events'])

    def test_different_raw_identity_even_before_confirmation_blocks_reset(self):
        args=inputs();args[2].append(dict(t=10.1,mine=dict(species='Tinkaton',cp=1498)))
        self.assertFalse(collect(*args)['events'])

    def test_a_late_or_future_dated_header_is_not_neutral_now(self):
        for change in (dict(confirmed_seconds=10.3),dict(first_visible_seconds=8),dict(cp=True)):
            args=inputs();args[1][1]['values']['mine'].update(change)
            self.assertFalse(collect(*args)['events'],change)

    def test_an_intervening_release_or_stat_notice_prevents_reset(self):
        args=inputs();args[3]['charged']=[dict(announcement_clip_seconds=[10.1])]
        self.assertFalse(collect(*args)['events'])
        args=inputs();args[4]=[dict(kind='stat_notice',t=10.1)]
        self.assertFalse(collect(*args)['events'])

    def test_two_nearby_new_cp_runs_are_not_cherry_picked(self):
        args=inputs();value=copy.deepcopy(args[1][1]['values']['mine'])
        value.update(cp=1498,first_visible_seconds=10.3,confirmed_seconds=10.5)
        args[1].append(dict(t=10.5,values={'mine':value}))
        self.assertFalse(collect(*args)['events'])

    def test_repeated_entry_text_is_one_reset(self):
        args=inputs();args[0].append(dict(t=11.033333,species='Tinkaton'))
        self.assertEqual(len(collect(*args)['events']),1)

    def test_missing_original_frame_alignment_is_withheld(self):
        args=inputs();args[5]={}
        self.assertFalse(collect(*args)['events'])

    def test_zero_does_not_appear_before_confirmation_and_bench_resets_too(self):
        event=self.event();state=team(event);evidence=StageResetEvidence([event])
        self.assertFalse(evidence.advance(10.1,state))
        self.assertIsNone(state['mine']['pokemon'][event['identity']]['attack_stage']['value'])
        updates=evidence.advance(10.2,state)
        self.assertEqual(len(updates),4)
        for mon in state['mine']['pokemon'].values():
            for name in ('attack_stage','defense_stage'):
                self.assertEqual(mon[name]['value'],0)
                self.assertEqual(mon[name]['confirmed_at_seconds'],10.2)

    def test_missing_identity_or_large_time_gap_cannot_apply_an_old_reset(self):
        event=self.event();state=team(event);state['mine']['pokemon'].pop(event['identity'])
        evidence=StageResetEvidence([event]);self.assertFalse(evidence.advance(10.2,state))
        state=team(event)
        self.assertFalse(evidence.advance(10.3,state))
        self.assertFalse(StageResetEvidence([event]).advance(11,state))

    def test_later_active_or_fainted_identity_cannot_be_rewritten(self):
        event=self.event();state=team(event);state['mine']['active']=event['last_pre_entry_header_identity']
        self.assertFalse(StageResetEvidence([event]).advance(10.2,state))
        state=team(event);state['mine']['pokemon'][event['identity']]['fainted']={'value':True}
        self.assertFalse(StageResetEvidence([event]).advance(10.2,state))

    def test_malformed_timing_cp_stages_or_source_witness_is_rejected(self):
        for change in (dict(confirmed_at_seconds=9),dict(cp=True),dict(attack_stage=False),
                       dict(last_pre_entry_header_seconds=10.3),dict(header_source_pts=True),
                       dict(header_source_time_base='0'),dict(source_time_base='1/0'),
                       dict(last_pre_entry_header_identity='Tinkaton:1499'),dict(last_pre_entry_header_identity='unknown')):
            event=self.event();event.update(change)
            self.assertFalse(StageResetEvidence([event]).events,change)

    def test_bench_rule_does_not_depend_on_a_guessed_exit_actor(self):
        event=self.event();state=team(event)
        state['mine']['pokemon']['Lapras:1497']=dict(species={'value':'Lapras'},cp={'value':1497},
            attack_stage={'value':2},defense_stage={'value':-1})
        updates=StageResetEvidence([event]).advance(10.2,state)
        self.assertEqual(len(updates),6)
        for mon in state['mine']['pokemon'].values():
            self.assertEqual(mon['attack_stage']['value'],0)
            self.assertEqual(mon['defense_stage']['value'],0)
        self.assertEqual(state['mine']['pokemon']['Lapras:1497']['attack_stage']['exit_identity_status'],'unresolved')
