import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_forms import collect, busted_caption, FormEvidence
from public_state import PublicState
from test_public_state import frame, SLIM


def inputs():
    text = [dict(t=t, text=[['banner', "Mimikyu's disguise is busted!"]]) for t in (12, 13)]
    timeline = dict(charged=[dict(side='mine', move='Shadow Sneak', announcement_clip_seconds=[10],
        side_confirmed_clip_seconds=9)], field={'theirs':[dict(name='Mimikyu', header_seen_clip_seconds=1)]})
    events = [dict(kind='charged', side='mine', charge_index=0, confirmed_at_seconds=10, shielded=False)]
    native = [dict(t=9.5, values={'theirs':dict(species='Mimikyu', cp=1498, confirmed_seconds=9.5,
                                               source_pts=285, source_time_base='1/30')})]
    raw = [dict(t=9.5, theirs=dict(species='Mimikyu', cp=1498))]
    return [text, timeline, events, native, raw]


class SourceForms(unittest.TestCase):
    def test_both_mimikyu_sides_do_not_make_the_target_ambiguous(self):
        result = collect(*inputs())
        self.assertEqual(len(result['events']), 1)
        event = result['events'][0]
        self.assertEqual((event['side'], event['identity'], event['t'], event['confirmed_at_seconds']),
                         ('theirs', 'Mimikyu:1498', 12, 13))

    def test_one_caption_or_duplicate_same_time_is_not_confirmation(self):
        args = inputs(); args[0] = args[0][:1]
        self.assertFalse(collect(*args)['events'])
        args[0] *= 2
        self.assertFalse(collect(*args)['events'])

    def test_blocking_or_partial_caption_cannot_choose_a_form(self):
        self.assertFalse(busted_caption('BLOCKED!'))
        self.assertFalse(busted_caption("Mimikyu's disguise"))
        self.assertFalse(busted_caption('disguise is busted'))

    def test_header_may_be_hidden_during_an_unchanged_charged_impact(self):
        args = inputs(); args[4] += [dict(t=11, theirs=None), dict(t=12, theirs=None)]
        self.assertEqual(len(collect(*args)['events']), 1)

    def test_charge_camera_can_hide_header_at_release_after_a_verified_cue_target(self):
        args = inputs(); args[3][0].update(t=8.5)
        args[3][0]['values']['theirs']['confirmed_seconds'] = 8.5
        args[3].append(dict(t=9.9, values={}))
        result = collect(*args)
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['target_proof_anchor_seconds'], 9)
        args[4].append(dict(t=9.6, theirs=dict(species='Mimikyu', cp=1497)))
        self.assertFalse(collect(*args)['events'])

    def test_same_species_different_cp_is_a_contrary_target(self):
        args = inputs(); args[4].append(dict(t=11, theirs=dict(species='Mimikyu', cp=1497)))
        self.assertFalse(collect(*args)['events'])

    def test_entry_even_of_same_species_blocks_cross_target_attribution(self):
        args = inputs(); args[1]['field']['theirs'].append(dict(name='Mimikyu', header_seen_clip_seconds=11))
        self.assertFalse(collect(*args)['events'])

    def test_missing_or_old_native_cp_does_not_get_filled_from_a_model(self):
        args = inputs(); args[3] = []
        self.assertFalse(collect(*args)['events'])
        args = inputs(); args[3][0]['values']['theirs']['confirmed_seconds'] = 8
        self.assertFalse(collect(*args)['events'])

    def test_future_release_side_or_header_proof_is_not_available(self):
        for field in ('release', 'side', 'header'):
            args = inputs()
            if field == 'release':args[2][0]['confirmed_at_seconds'] = 14
            elif field == 'side':args[1]['charged'][0]['side_confirmed_clip_seconds'] = 14
            else:args[3][0]['values']['theirs']['confirmed_seconds'] = 11
            self.assertFalse(collect(*args)['events'], field)

    def test_independent_shield_conflict_is_retained_without_a_form(self):
        args = inputs(); args[2][0].update(shielded=True, shield_confirmed_at_seconds=11)
        result = collect(*args)
        self.assertFalse(result['events'])
        self.assertTrue(all(r['status'] == 'contradictory' for r in result['candidates']))

    def test_unrestricted_text_does_not_leave_the_parser(self):
        args = inputs(); args[0][0]['text'].append(['header', 'PrivateTrainerExample'])
        self.assertNotIn('PrivateTrainerExample', json.dumps(collect(*args)))


class FormState(unittest.TestCase):
    def test_partial_or_invalid_form_records_are_not_accepted(self):
        event = collect(*inputs())['events'][0]
        bad = dict(event); bad.pop('source_observation_seconds')
        self.assertFalse(FormEvidence([bad]).events)
        bad = dict(event, form='mimikyu')
        self.assertFalse(FormEvidence([bad]).events)
        bad = dict(event, confirmed_at_seconds=float('inf'))
        self.assertFalse(FormEvidence([bad]).events)

    def test_confirmation_is_causal_and_only_changes_the_matching_cp(self):
        event = collect(*inputs())['events'][0]
        ledger = PublicState({}, form_events=[event])
        def sample(t):
            result = frame(t, name='Mimikyu', cp=1497)
            result['opponent']['species']['value'] = 'Mimikyu'
            result['opponent']['cp']['value'] = 1498
            return result
        before = ledger.update(sample(12), SLIM)
        self.assertIsNone(before['sides']['opponent']['pokemon']['Mimikyu:1498']['form']['value'])
        after = ledger.update(sample(13), SLIM)
        self.assertEqual(after['sides']['opponent']['pokemon']['Mimikyu:1498']['form']['value'], 'mimikyu_busted')
        self.assertIsNone(after['sides']['mine']['pokemon']['Mimikyu:1497']['form']['value'])
        self.assertIsNone(before['sides']['opponent']['pokemon']['Mimikyu:1498']['form']['value'])

    def test_busted_form_persists_when_the_pokemon_goes_to_the_bench(self):
        event = collect(*inputs())['events'][0]; event.update(side='mine', cp=1497, identity='Mimikyu:1497')
        ledger = PublicState({}, form_events=[event]); ledger.update(frame(12, name='Mimikyu', cp=1497), SLIM)
        ledger.update(frame(13, name='Mimikyu', cp=1497), SLIM)
        state = ledger.update(frame(14, name='Lanturn', cp=1496), SLIM)
        self.assertEqual(state['sides']['mine']['pokemon']['Mimikyu:1497']['form']['value'], 'mimikyu_busted')

    def test_missing_named_cp_never_changes_another_mimikyu(self):
        event = collect(*inputs())['events'][0]
        ledger = PublicState({}, form_events=[event]); state = ledger.update(frame(13, name='Mimikyu', cp=1497), SLIM)
        self.assertIsNone(state['sides']['mine']['pokemon']['Mimikyu:1497']['form']['value'])


if __name__ == '__main__':unittest.main()
