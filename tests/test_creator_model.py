"""Unsupported model formats must not discard or replace source evidence."""
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_model import support, unavailable
from game_record import build, text
from pogo.gamedata import GameData


class CreatorModelTests(unittest.TestCase):
    def test_registered_mega_is_retained_without_claiming_ranked_model(self):
        result = support({'field': {'mine': [{'name': 'Houndoom (Mega)'}]}}, {'pokemon': []}, GameData())
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['unranked_visible_species'], ['Houndoom (Mega)'])
        self.assertTrue(result['source_observations_usable'])

    def test_supported_species_still_uses_model(self):
        self.assertEqual(support({'field': {}}, {'pokemon': [{'species':'Azumarill'}]}, GameData())['status'], 'available')

    def test_old_model_data_is_preserved_and_cannot_appear_as_new_prediction(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            old = b'{"t":1,"made_before_current_replay":true}\n'
            (folder/'states.jsonl').write_bytes(old)
            (folder/'states.jsonl.gz').write_bytes(gzip.compress(old))
            verdict = unavailable(folder, {'status':'unavailable'})
            self.assertEqual((folder/'states.jsonl').read_bytes(), b'')
            self.assertEqual(next((folder/'model-history').glob('*/states.jsonl')).read_bytes(), old)
            self.assertEqual(verdict['verdict'], 'fail')
            self.assertIsNone(json.loads((folder/'track.json').read_text())['unexplained'])

    def test_source_record_survives_without_model_and_preserves_unknowns_and_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            unavailable(folder, {'status':'unavailable'})
            def save(name, obj):
                (folder/name).write_text(json.dumps(obj), encoding='utf8')
            save('timeline.json', dict(public_footage=True, clip_origin_seconds=2, end=20, result='win'))
            save('verdict.json', dict(verdict='fail', failed=['unsupported model']))
            event = dict(kind='charged', side='mine', pokemon='Mega Houndoom', move='Dark Pulse+',
                         t=10, confirmed_at_seconds=11, shielded=None, model_build_used=False)
            (folder/'source-events.jsonl').write_text(json.dumps(event)+'\n')
            record = build(folder)
            self.assertEqual(record['actions'][0]['move'], 'Dark Pulse+')
            self.assertEqual(record['actions'][0]['t'], 8)
            self.assertEqual(record['actions'][0]['confirmed_at_seconds'], 9)
            self.assertIsNone(record['summary']['shields_left']['theirs'])
            self.assertIsNone(record['fighting_turns'])
            self.assertEqual(record['summary']['faints']['theirs'], 0)
            self.assertEqual(record['teams']['mine'], [])
            self.assertIn('shield decision unknown', text(record))
            self.assertEqual(record['model_status'], 'unavailable')

    def test_corrupt_source_data_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            unavailable(folder, {'status':'unavailable'})
            (folder/'source-events.jsonl').write_text('not valid json\n')
            with self.assertRaises(json.JSONDecodeError):
                build(folder)
