"""Accuracy counts must include duplicate, wrong-side and mistimed events."""
from pathlib import Path
from collections import Counter
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from score_creator_events import match, censored_prediction


class EventAccuracy(unittest.TestCase):
    def test_reference_has_two_per_channel_with_reproducible_frame_evidence(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root/'data/creator_ground_truth_v1.json').read_text(encoding='utf-8'))
        counts = Counter(b['channel'] for b in data['battles'])
        self.assertEqual(counts, {'homeslicehenry': 2, 'itsaxn': 2, 'reis2occasion': 2})
        for battle in data['battles']:
            self.assertEqual(len(battle['source']['video_sha256']), 64)
            for event in battle['events']:
                self.assertIn(event['kind'], ('charged', 'faint', 'charged_cue'))
                self.assertTrue(event['evidence'])
                for frame in event['evidence']:
                    self.assertIsInstance(frame['source_pts'], int)
                    self.assertEqual(len(frame['decoded_rgb_sha256']), 64)

    def truth(self):
        return {'kind': 'charged', 'side': 'mine', 'pokemon': 'Jumpluff',
                'move': 'Acrobatics', 'window': [10, 20]}

    def pred(self, **changes):
        return {'kind': 'charged', 'side': 'mine', 'pokemon': 'Jumpluff',
                'move': 'ACROBATICS', 't': 18, **changes}

    def test_duplicate_predictions_count_as_false_positives(self):
        score = match([self.truth()], [self.pred(), self.pred()])
        self.assertEqual((score['tp'], score['fp'], score['fn']), (1, 1, 0))

    def test_wrong_side_or_move_is_not_a_match(self):
        for change in [{'side': 'theirs'}, {'move': 'ENERGY_BALL'}]:
            score = match([self.truth()], [self.pred(**change)])
            self.assertEqual((score['tp'], score['fp'], score['fn']), (0, 1, 1))

    def test_late_identity_match_does_not_count_as_timely(self):
        predicted = self.pred(t=30)
        self.assertEqual(match([self.truth()], [predicted])['tp'], 0)
        self.assertEqual(match([self.truth()], [predicted], timed=False)['tp'], 1)

    def test_censored_own_release_does_not_hide_opponents_attack(self):
        cue = {'side': 'mine', 'pokemon': 'Cetitan', 'window': [125, 131]}
        self.assertFalse(censored_prediction(self.pred(side='theirs', pokemon='Hippowdon', t=125), [cue]))
        self.assertTrue(censored_prediction(self.pred(pokemon='Cetitan', t=128), [cue]))

    def test_shield_use_matching_does_not_require_a_guessed_attack_name(self):
        truth = {'kind': 'shield', 'side': 'mine', 'window': [10, 20]}
        self.assertEqual(match([truth], [{'kind': 'shield', 'side': 'mine', 't': 18}])['tp'], 1)


if __name__ == '__main__':
    unittest.main()
