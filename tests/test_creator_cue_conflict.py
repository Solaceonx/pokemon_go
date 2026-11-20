from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_charge_evidence import conflicting_incoming_cue
from creator_event_ledger import source_events


class CueConflictTests(unittest.TestCase):
    def setUp(self):
        self.charge = dict(side='theirs', start=10, announcements=[14], ours=True,
                           user='Toxapex', actor_confirmed_clip_seconds=14)
        self.fields = dict(mine=[dict(name='Toxapex', seen=8)], theirs=[dict(name='Dunsparce', seen=8)])
        self.texts = [dict(t=13, text=[['banner','GREAT!']])]

    def resolve(self, after=9):
        return conflicting_incoming_cue(self.charge, self.fields, self.texts, after)

    def test_fresh_own_minigame_and_unique_actor_resolve_release_but_preserve_conflict(self):
        result = self.resolve()
        self.assertEqual(result['side'], 'mine')
        self.assertEqual(result['side_confirmed_clip_seconds'], 14)
        self.assertFalse(result['cue_conflict']['exact_action_start_verified'])
        self.assertEqual(result['cue_conflict']['clip_seconds'], 10)
        self.assertEqual(self.charge['side'], 'theirs')

    def test_future_or_mirrored_identity_cannot_resolve_side(self):
        self.fields['mine'][0]['seen'] = 15
        self.assertIsNone(self.resolve())
        self.fields['mine'][0]['seen'] = 8
        self.fields['theirs'][0]['name'] = 'Toxapex'
        self.assertIsNone(self.resolve())

    def test_old_or_future_minigame_cannot_override_incoming(self):
        self.texts[0]['t'] = 9
        self.assertIsNone(self.resolve())
        self.texts[0]['t'] = 14.1
        self.assertIsNone(self.resolve())
        self.texts[0]['t'] = 13
        self.assertIsNone(self.resolve(after=13.1))

    def test_actor_alone_or_unreleased_minigame_cannot_override_cue(self):
        self.texts = []
        self.assertIsNone(self.resolve())
        self.charge['announcements'] = []
        self.assertIsNone(self.resolve())

    def test_ledger_keeps_unresolved_original_cue_without_fabricating_second_release(self):
        q = {**self.charge, **self.resolve(), 't':10, 'actor':'Toxapex', 'move':'Sludge Wave',
             'announcement_clip_seconds':[14]}
        events = source_events(dict(clip_origin_seconds=0, field=self.fields, charged=[q]), {'faints':[]}, {})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['side'], 'mine')
        self.assertIn('cue_conflict', events[0])
