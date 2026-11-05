import unittest
import io
import tarfile
import tempfile
from pathlib import Path

from scripts.audit_standalone_final import audit, check_statistics, pairing_values


class FinalAuditTests(unittest.TestCase):
    def test_rejects_duplicate_archive_members_before_reading_experiment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inputs.tar.gz'
            with tarfile.open(path, 'w:gz') as archive:
                for _ in range(2):
                    member = tarfile.TarInfo('same.json')
                    member.size = 2
                    archive.addfile(member, io.BytesIO(b'{}'))
            with self.assertRaisesRegex(ValueError, 'duplicate bundle member'):
                audit('unused', Path('unused.json'), input_bundle=path)

    def test_rejects_parent_directory_archive_member(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inputs.tar.gz'
            with tarfile.open(path, 'w:gz') as archive:
                member = tarfile.TarInfo('../outside.json')
                member.size = 2
                archive.addfile(member, io.BytesIO(b'{}'))
            with self.assertRaisesRegex(ValueError, 'unsafe bundle member'):
                audit('unused', Path('unused.json'), input_bundle=path)

    def test_both_seats_and_draws_count(self):
        rows = [dict(index=0, winners=[0, 1], scores=[1, 1], score=1),
                dict(index=1, winners=[-1, 0], scores=[.5, 0], score=.25)]
        values, counts = pairing_values(rows, 2)
        self.assertEqual(values, [1, .25])
        self.assertEqual(counts, dict(wins=2, draws=1, losses=1))

    def test_rejects_wrong_second_seat_score(self):
        rows = [dict(index=0, winners=[0, 0], scores=[1, 1], score=1)]
        with self.assertRaisesRegex(ValueError, "winner/seat"):
            pairing_values(rows, 1)

    def test_rejects_duplicate_indices(self):
        row = dict(index=0, winners=[0, 1], scores=[1, 1], score=1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            pairing_values([row, row], 2)

    def test_rejects_inconsistent_reported_statistics(self):
        result = dict(score=.99, normal_margin95=0, hoeffding_lower97_5=0, ci95=[.99, 1])
        with self.assertRaisesRegex(ValueError, "score"):
            check_statistics([0, 1, .25, .75], result, "fixed-schedule")


if __name__ == "__main__":
    unittest.main()
