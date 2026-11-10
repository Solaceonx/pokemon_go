import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/live'))
import import_evidence as importer


class CanonicalImport(unittest.TestCase):
    def fixture(self,folder):
        root=folder/'repo';evidence=folder/'evidence';logs=folder/'logs';logs.mkdir()
        stamp='20261109-010000';game=evidence/stamp;game.mkdir(parents=True)
        rows=[{'kind':'team','t':0,'team':[['jellicent','HEX',['SURF','SHADOW_BALL'],1499]]},
              {'kind':'start','t':0,'epoch':1794200000,'league':None},
              {'kind':'look','t':1,'obs':{'my_species':'jellicent','foe_species':'flareon','my_hp':1,'foe_hp':1},'foe':['flareon',0,0,'EMBER','guessed']},
              {'kind':'end','t':5,'result':'win','foes':['flareon']}]
        raw=('\n'.join(json.dumps(r) for r in rows)+'\n').encode()
        (logs/(stamp+'.jsonl')).write_bytes(raw)
        (evidence/'index.json').write_text(json.dumps({'games':[{'stamp':stamp,'input_sha256':hashlib.sha256(raw).hexdigest()}]}))
        (game/'summary.json').write_text('{}')
        for name in ['evidence.jsonl.gz','review-flags.jsonl.gz']:(game/name).write_bytes(gzip.compress(b'',mtime=0))
        return root,evidence,logs,stamp

    def test_idempotent_import_preserves_existing_records_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,evidence,logs,stamp=self.fixture(Path(tmp))
            first=importer.run(root,evidence,logs)
            before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
            second=importer.run(root,evidence,logs)
            after={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
            self.assertEqual(first['new_records'],[stamp]);self.assertEqual(second['new_records'],[])
            rec=json.loads((root/'games/live'/stamp/'game.json').read_text())
            self.assertEqual(rec['variant_version'],2);self.assertEqual(rec['source']['mode'],'training')
            self.assertEqual(rec['built_from'],['runs/live/'+stamp+'.jsonl'])
            self.assertIsNone(rec['teams']['mine'][0]['ivs'])
            index=json.loads((root/'games/live/index.json').read_text())
            self.assertEqual(index[0]['evidence'],f'games/live/{stamp}/enrichment.json')

    def test_different_existing_evidence_is_a_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,evidence,logs,stamp=self.fixture(Path(tmp));importer.run(root,evidence,logs)
            (evidence/stamp/'evidence.jsonl.gz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Existing file differs'):importer.run(root,evidence,logs)

    def test_changed_source_is_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,evidence,logs,stamp=self.fixture(Path(tmp));(logs/(stamp+'.jsonl')).write_text('{}')
            with self.assertRaisesRegex(ValueError,'Source hash changed'):importer.run(root,evidence,logs)
            self.assertFalse((root/'games/live'/stamp/'game.json').exists())

    def test_opponent_species_does_not_classify_context(self):
        rows=[{'kind':'start','t':0},{'kind':'end','t':1,'foes':['flareon']}]
        with self.assertRaisesRegex(ValueError,'Unknown context'):importer.mode_for('20261109-010000',rows,{})
        self.assertEqual(importer.mode_for('20261109-010000',[{'kind':'start','league':'Great League'}],{})[0],'league')

    def test_training_collection_supplies_explicit_missing_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            media=Path(tmp);p=media/'20261109-training/battle-20261109-010000.times';p.parent.mkdir();p.write_text('1\n')
            mode,proof=importer.mode_for('20261109-010000',[{'kind':'start'}],{},media)
            self.assertEqual(mode,'training');self.assertIn('20261109-training',proof)


class ImportedLibrary(unittest.TestCase):
    def test_unified_catalog_is_current_and_does_not_count_views_as_games(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('index_games',ROOT/'scripts/index_games.py')
        indexer=importlib.util.module_from_spec(spec);spec.loader.exec_module(indexer)
        catalog=json.loads((ROOT/'games/catalog.json').read_text())
        self.assertEqual(catalog,indexer.build(ROOT))
        self.assertEqual(catalog['counts']['league_completed_games'],99)
        self.assertEqual(catalog['counts']['league_fragments'],1)
        self.assertLess(catalog['counts']['public_match_id_groups'],catalog['counts']['public_player_view_records'])

    def test_all_audited_records_have_hash_matched_source_and_evidence(self):
        report=ROOT/'runs/canonical-game-import-20261109.json'
        if not report.exists():self.skipTest('Import receipt not installed')
        receipt=json.loads(report.read_text())
        self.assertEqual(len(receipt['evidence_attached']),207)
        for stamp in receipt['evidence_attached']:
            folder=ROOT/'games/live'/stamp
            rec=json.loads((folder/'game.json').read_text())
            manifest=json.loads((folder/'enrichment.json').read_text())
            self.assertEqual(rec['schema'],'game-record-v1')
            self.assertEqual(hashlib.sha256((ROOT/rec['source']['log']).read_bytes()).hexdigest(),manifest['source_log_sha256'])
            for name,proof in manifest['files'].items():
                self.assertEqual(hashlib.sha256((folder/name).read_bytes()).hexdigest(),proof['sha256'])

    def test_catalog_and_raw_log_coverage(self):
        catalog=json.loads((ROOT/'games/live/index.json').read_text())
        self.assertEqual(len(catalog),len({r['stamp'] for r in catalog}))
        for entry in catalog:
            rec=json.loads((ROOT/entry['game']).read_text())
            self.assertTrue((ROOT/rec['source']['log']).is_file())
            self.assertTrue((ROOT/entry['game']).with_suffix('.txt').exists())


if __name__=='__main__':unittest.main()
