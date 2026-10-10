import tempfile
import unittest
from pathlib import Path
import json
from battle_io import open_log, read_jsonl


class LogIOTests(unittest.TestCase):
    def test_lossless_plain_and_compressed_roundtrip(self):
        rows = [{"t": 0.033333, "note": "Pokémon", "unknown": None}, {"t": 1, "hp": 0.731884}]
        with tempfile.TemporaryDirectory() as folder:
            for name in ["looks.jsonl", "looks.jsonl.gz"]:
                path = Path(folder) / name
                with open_log(path, "wt") as log:
                    for row in rows:
                        log.write(json.dumps(row, ensure_ascii=False) + "\n")
                self.assertEqual(list(read_jsonl(path)), rows)

    def test_compressed_write_does_not_create_plain_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "looks.jsonl.gz"
            with open_log(path, "wt") as log:
                log.write('{"t":0}\n')
            self.assertFalse((Path(folder) / "looks.jsonl").exists())
            self.assertEqual(list(read_jsonl(path)), [{"t": 0}])


if __name__ == "__main__":
    unittest.main()
