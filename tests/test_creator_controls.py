import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_controls import ControlEvidence


def sample(t, labels=False, fills=(.5, .333)):
    return {'t': t, 'controls': {'status': 'observed', 'discs': [
        {'id': f'charge_{i}', 'center': [150+i*208, 970], 'radius': 40,
         'status': 'observed', 'measurement': {'fill': fill}, 'ready': None}
        for i, fill in enumerate(fills)]}, 'labels': [
        {'id': f'charge_{i}', 'name': name, 'cost': cost,
         'observed_at_seconds': t, 'confidence': .99} for i, (name, cost) in
        enumerate([('Surf', 40), ('Ice Beam', 60)])] if labels else []}


class CausalControls(unittest.TestCase):
    def test_unseen_or_single_label_does_not_supply_cost(self):
        tracker = ControlEvidence()
        for i in range(3):
            _, energy = tracker.update(sample(i/6, labels=i == 0), 'same:1490')
        self.assertEqual(energy['status'], 'unknown')
        _, energy = tracker.update(sample(1, labels=True), 'same:1490')
        for t in [7/6, 8/6]:
            _, energy = tracker.update(sample(t), 'same:1490')
        self.assertEqual(energy['status'], 'constrained')
        self.assertTrue(any(a <= 20 <= b for a, b in energy['integer_ranges']))

    def test_labels_do_not_transfer_to_an_unseen_replacement(self):
        tracker = ControlEvidence()
        tracker.update(sample(0, labels=True), 'old:1490')
        tracker.update(sample(1, labels=True), 'old:1490')
        for t in [2, 13/6, 14/6]:
            _, energy = tracker.update(sample(t), 'new:1490')
        self.assertEqual(energy['status'], 'unknown')

    def test_moving_fill_is_not_a_settled_energy_reading(self):
        tracker = ControlEvidence()
        tracker.update(sample(0, labels=True), 'same:1490')
        tracker.update(sample(1, labels=True), 'same:1490')
        for i in range(3):
            _, energy = tracker.update(sample(2+i/6, fills=(.2+i*.15, .1+i*.15)), 'same:1490')
        self.assertEqual(energy['status'], 'unknown')

    def test_no_identity_cannot_learn_a_move_for_a_later_header(self):
        tracker = ControlEvidence()
        tracker.update(sample(0, labels=True), None)
        tracker.update(sample(1, labels=True), None)
        for t in [2, 13/6, 14/6]:
            buttons, energy = tracker.update(sample(t), 'later:1490')
        self.assertTrue(all(b['move'] is None for b in buttons))
        self.assertEqual(energy['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
