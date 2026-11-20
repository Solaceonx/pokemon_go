"""Terminal damage needs continuous pixels, not a result or a vanished bar."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_impact import zero_transition, apply_impact, record_faint, measure_center


def samples():
    result = []
    for i in range(46):
        bar = {'bounds': [184, 510, 328, 524], 'live_pixels': 70 if i < 3 else 0,
               'orange_pixels': 0 if i < 3 else 70, 'width': 138}
        result.append({'t': i/20, 'bar': bar if i < 24 else None})
    return result


class CenterImpact(unittest.TestCase):
    def test_live_yellow_and_red_are_not_the_orange_damage_trail(self):
        try:
            import cv2
            import numpy as np
            convert = cv2.cvtColor
        except (ImportError, AttributeError):
            self.skipTest('Optional native video dependencies unavailable')
        fake = SimpleNamespace(read_health_bar=lambda *args: {
            'bounds': [184, 510, 328, 524], 'outline_method': 'edge_contour'})
        for hue, expected_live, expected_orange in [(81, 70, 0), (31, 70, 0), (2, 70, 0), (19, 0, 70)]:
            rgb = np.zeros((1080, 508, 3), dtype=np.uint8)
            color = convert(np.array([[[hue, 230, 240]]], dtype=np.uint8), cv2.COLOR_HSV2RGB)[0, 0]
            rgb[513:521, 187:257] = color
            with patch.dict(sys.modules, {'health_reader': fake}):
                actual = measure_center(rgb, 144)
            self.assertEqual(actual['live_pixels'], expected_live, hue)
            self.assertEqual(actual['orange_pixels'], expected_orange, hue)

    def test_positive_live_strip_to_zero_has_frame_evidence(self):
        proof = zero_transition(samples())
        self.assertIsNotNone(proof)
        self.assertEqual(proof['first_zero']['bar']['live_pixels'], 0)
        self.assertGreater(proof['missing_tail_samples'], 2)

    def test_disappearance_without_a_measured_zero_is_not_a_faint(self):
        values = samples()
        for row in values[3:]:
            row['bar'] = None
        self.assertIsNone(zero_transition(values))

    def test_initially_orange_bar_is_not_a_zero_transition(self):
        values = samples()
        for row in values[:3]:
            row['bar']['live_pixels'] = 0
            row['bar']['orange_pixels'] = 70
        self.assertIsNone(zero_transition(values))

    def test_camera_cut_and_sparse_zero_samples_are_rejected(self):
        values = samples()
        for row in values[3:24]:
            row['bar']['bounds'] = [200, 600, 344, 614]
        self.assertIsNone(zero_transition(values))
        values = samples()
        for i, row in enumerate(values):
            row['t'] = i/3
        self.assertIsNone(zero_transition(values))

    def test_flash_that_returns_to_live_health_is_not_terminal(self):
        values = samples()
        values[16]['bar']['live_pixels'] = 25
        self.assertIsNone(zero_transition(values))

    def test_clip_ending_at_zero_has_insufficient_faint_evidence(self):
        self.assertIsNone(zero_transition(samples()[:8]))

    def test_terminal_look_resolves_final_attack_without_changing_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            timeline = {'clip_origin_seconds': 5, 'result': 'win'}
            (game/'timeline.json').write_text(json.dumps(timeline))
            (game/'observations.jsonl').write_text(json.dumps({'t': 2, 'foe_left': 1})+'\n'+
                json.dumps({'t': 20, 'my_charged': 'Acrobatics', 'note': 'unresolved final attack'})+'\n')
            trace = {'accepted': True, 'side': 'theirs', 'attack_side': 'mine',
                     'attack_start_clip_seconds': 8, 'measurement': {'first_zero': {'t': 14}, 'confirmed_zero': {'t': 15}}}
            with patch('creator_impact.sample_impact', return_value=trace):
                actual = apply_impact(game, game, game)
            rows = [json.loads(line) for line in (game/'observations.jsonl').read_text().splitlines()]
            self.assertEqual(rows[-1]['t'], 9)
            self.assertEqual(rows[-1]['foe_left'], 0)
            self.assertEqual(rows[-1]['foe_hp'], 0)
            self.assertEqual(rows[-1]['my_charged'], 'Acrobatics')
            self.assertEqual(json.loads((game/'timeline.json').read_text()), timeline)
            self.assertEqual(actual['tracker_seconds'], 9)

    def test_measured_faint_is_recorded_once_even_without_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game/'events.jsonl').write_text('')
            (game/'track.json').write_text('{"events":{}}')
            trace = {'accepted': True, 'side': 'theirs', 'tracker_seconds': 10, 'species': 'Mimikyu'}
            record_faint(game, trace)
            record_faint(game, trace)
            rows = (game/'events.jsonl').read_text().splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0])['known_from'], 'centered_impact_pixels')
            self.assertEqual(json.loads((game/'track.json').read_text())['events']['foe_faint'], 1)


if __name__ == '__main__':
    unittest.main()
