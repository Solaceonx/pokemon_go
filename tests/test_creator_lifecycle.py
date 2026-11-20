import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_lifecycle import resolve_forms, active
from creator_impact import corroborated_empty_transition
from creator_impact import zero_transition
from creator_impact import measured_outline, measure_palette
from creator_impact import complete_empty_target
from creator_lifecycle import jumping_bar
from unittest.mock import patch
from types import SimpleNamespace
from assemble import public_announced_move
from pogo.gamedata import GameData
from pogo.tracker import Tracker, Observation


class Lifecycle(unittest.TestCase):
    def test_empty_camera_target_needs_full_rectangles_and_fade(self):
        samples = [{'t': i/15, 'bar': {'bounds': [182, 500, 326, 514],
                    'live_pixels': 0, 'outline_method': 'edge_contour'} if i < 18 else None}
                   for i in range(50)]
        self.assertIsNotNone(complete_empty_target(samples, .1))
        for s in samples:
            if s['bar']:
                s['bar']['outline_method'] = 'paired_outline'
        self.assertIsNone(complete_empty_target(samples, .1))
    def test_victim_uses_fresh_header_not_early_inferred_switch_time(self):
        timeline = {'clip_origin_seconds': 0, 'field': {'mine': [
            {'t': 100, 'header_seen_clip_seconds': 101, 'name': 'Victreebel'},
            {'t': 147, 'header_seen_clip_seconds': 148, 'name': 'Turtonator'}]}}
        self.assertEqual(active(timeline, 'mine', 147.5), 'Victreebel')
        self.assertEqual(active(timeline, 'mine', 148), 'Turtonator')

    def test_complete_outline_beats_cropped_width_and_false_rails_are_rejected(self):
        try:
            import numpy as np
            import cv2
            if not hasattr(cv2, 'cvtColor'):
                self.skipTest('native pixel libraries unavailable')
        except ImportError:
            self.skipTest('native pixel libraries unavailable')
        rgb = np.zeros((100, 220, 3), dtype=np.uint8)
        guessed = {'bounds': [40, 30, 184, 44], 'outline_method': 'paired_outline'}
        actual = {'bounds': [30, 30, 184, 44], 'outline_method': 'edge_contour'}
        module = SimpleNamespace(read_health_bar=lambda image, region, width: actual if width == 154 else guessed)
        with patch.dict(sys.modules, {'health_reader': module}):
            self.assertEqual(measured_outline(rgb, [0, 0, 220, 100], 144), actual)
        module.read_health_bar = lambda *args: guessed
        with patch.dict(sys.modules, {'health_reader': module}):
            self.assertIsNone(measured_outline(rgb, [0, 0, 220, 100], 144))
            self.assertIsNotNone(measured_outline(rgb, [0, 0, 220, 100], 144, calibrated_width=144))
            rgb[30:44, 40] = 255
            rgb[30:44, 183] = 255
            self.assertIsNotNone(measured_outline(rgb, [0, 0, 220, 100], 144))

    def test_one_live_pixel_after_outline_padding_is_not_zero(self):
        try:
            import numpy as np
            import cv2
            if not hasattr(cv2, 'cvtColor'):
                self.skipTest('native pixel libraries unavailable')
        except ImportError:
            self.skipTest('native pixel libraries unavailable')
        rgb = np.zeros((30, 160, 3), dtype=np.uint8)
        rgb[3:11, 5] = [255, 0, 0]
        bar = {'bounds': [0, 0, 144, 14], 'outline_method': 'edge_contour'}
        self.assertGreater(measure_palette(rgb, bar)['live_pixels'], 0)

    def timeline(self):
        return {'clip_origin_seconds': 0, 'charged': [],
                'field': {'mine': [{'t': 0, 'name': 'Kingdra'}],
                          'theirs': [{'t': 0, 'name': 'Araquanid'}]}}








    def test_initial_empty_impact_requires_counter_and_fade(self):
        samples = [{'t': i/15, 'bar': {'live_pixels': 0, 'width': 138} if i < 4 else None}
                   for i in range(25)]
        self.assertIsNone(corroborated_empty_transition(samples, []))
        self.assertIsNotNone(corroborated_empty_transition(samples, [{'first': 1}]))
        samples[-1]['bar'] = {'live_pixels': 1, 'width': 138}
        # A surviving strip inside the corroboration window rejects this zero.
        samples[15]['bar'] = {'live_pixels': 1, 'width': 138}
        self.assertIsNone(corroborated_empty_transition(samples, [{'first': 1}]))

    def test_weather_ball_variant_needs_unique_legal_actor(self):
        self.assertEqual(public_announced_move('weatherball', 'Hippowdon'), 'Weather Ball (Rock)')
        self.assertEqual(public_announced_move('weatherball', 'Castform'), 'Weather Ball')

    def test_native_faint_follows_vertical_bounce_but_rejects_live_return(self):
        samples = []
        for i in range(45):
            y = 600+(i%3)*20
            bar = {'bounds': [30, y, 174, y+14], 'live_pixels': 1 if i < 4 else 0,
                   'orange_pixels': 0, 'width': 138} if i < 18 else None
            samples.append({'t': i/15, 'bar': bar})
        proof = zero_transition(samples, require_orange=False, minimum_positive_pixels=1, geometry=jumping_bar)
        self.assertIsNotNone(proof)
        self.assertEqual(proof['first_zero']['t'], 4/15)
        samples[15]['bar']['live_pixels'] = 1
        self.assertIsNone(zero_transition(samples, require_orange=False, minimum_positive_pixels=1, geometry=jumping_bar))

    def test_form_is_resolved_only_by_unique_legal_observed_moves(self):
        gd = GameData()
        timeline = self.timeline()
        timeline['field']['mine'][0]['name'] = 'Qwilfish'
        timeline['charged'] = [{'t': 5, 'side': 'mine', 'move': 'Dark Pulse'},
                               {'t': 20, 'side': 'mine', 'move': 'Aqua Tail'}]
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game/'team.json').write_text(json.dumps({'pokemon': [{'species': 'Qwilfish'}]}))
            resolved = resolve_forms(game, timeline, gd)
            self.assertEqual(resolved[0]['resolved_species'], 'Qwilfish (Hisuian)')
            (game/'team.json').write_text(json.dumps({'pokemon': [{'species': 'Qwilfish'}]}))
            timeline['charged'] = timeline['charged'][1:]
            self.assertEqual(resolve_forms(game, timeline, gd), [])

    def test_source_faint_is_logged_once_before_replacement(self):
        gd = GameData()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'events.jsonl'
            tracker = Tracker(gd, [gd.default('kingdra'), gd.default('turtonator')], path=path)
            tracker.update(Observation(t=0, my_species='kingdra', foe_species='araquanid'))
            tracker.update(Observation(t=2, my_species='kingdra', my_hp=0, my_fainted=True))
            self.assertEqual(tracker.me.mon.hp, 0)
            tracker.update(Observation(t=12, my_species='turtonator'))
            tracker.close()
            events = [json.loads(l) for l in path.read_text().splitlines()]
            faints = [e for e in events if e['event'] == 'my_faint']
            self.assertEqual(len(faints), 1)
            self.assertEqual(faints[0]['t'], 2)
            self.assertEqual(faints[0]['species'], 'kingdra')


if __name__ == '__main__':
    unittest.main()
