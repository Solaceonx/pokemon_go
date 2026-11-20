import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from source_snapshot import create,verify,extract


class ExactSourceSnapshot(unittest.TestCase):
    def setup_source(self,root):
        (root/'source').mkdir();raw=b'# exact\r\nvalue = 1\r\n'
        (root/'source/a.py').write_bytes(raw)
        return raw,{'source/a.py':hashlib.sha256(raw).hexdigest()}

    def test_roundtrip_preserves_crlf_bytes_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw,pins=self.setup_source(root)
            create(root,pins,root/'one.gz');create(root,pins,root/'two.gz')
            self.assertEqual((root/'one.gz').read_bytes(),(root/'two.gz').read_bytes())
            self.assertEqual(extract(root/'one.gz',root/'restored'),1)
            self.assertEqual((root/'restored/source/a.py').read_bytes(),raw)

    def test_manifest_mismatch_is_rejected_before_archive_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,pins=self.setup_source(root);pins['source/a.py']='0'*64
            with self.assertRaises(ValueError):create(root,pins,root/'bad.gz')
            self.assertFalse((root/'bad.gz').exists())

    def test_modified_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,pins=self.setup_source(root);archive=root/'one.gz';create(root,pins,archive)
            data=json.loads(gzip.decompress(archive.read_bytes()));data['files'][0]['source_utf8']+='x'
            archive.write_bytes(gzip.compress(json.dumps(data).encode()))
            with self.assertRaises(ValueError):verify(archive)

    def test_unsafe_paths_and_duplicates_are_rejected_before_extraction(self):
        for name in ('../outside.py','/outside.py','C:/outside.py','a\\outside.py','a//outside.py'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);raw,pins=self.setup_source(root);archive=root/'one.gz';create(root,pins,archive)
                data=json.loads(gzip.decompress(archive.read_bytes()));data['files'][0]['path']=name
                archive.write_bytes(gzip.compress(json.dumps(data).encode()))
                with self.assertRaises(ValueError):extract(archive,root/'restored')
                self.assertFalse((root/'restored').exists())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,pins=self.setup_source(root);archive=root/'one.gz';create(root,pins,archive)
            data=json.loads(gzip.decompress(archive.read_bytes()));data['files'].append(data['files'][0])
            archive.write_bytes(gzip.compress(json.dumps(data).encode()))
            with self.assertRaises(ValueError):verify(archive)

    def test_existing_destination_and_different_archive_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,pins=self.setup_source(root);archive=root/'one.gz';create(root,pins,archive)
            destination=root/'keep';destination.mkdir();(destination/'mine.txt').write_text('keep')
            with self.assertRaises(ValueError):extract(archive,destination)
            self.assertEqual((destination/'mine.txt').read_text(),'keep')
            (root/'source/a.py').write_bytes(b'changed');pins['source/a.py']=hashlib.sha256(b'changed').hexdigest()
            before=archive.read_bytes()
            with self.assertRaises(ValueError):create(root,pins,archive)
            self.assertEqual(archive.read_bytes(),before)
