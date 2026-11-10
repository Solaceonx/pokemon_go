"""Import audited live logs into the canonical game-record-v1 live-log v2 layout.

Existing game.json/game.txt and raw logs are preserved. Conflicts are errors.
Additional observations live beside each record, without replacing its beliefs.
No phone API or media encoding is used.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

import live_record


def read(path,default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def sha(data):return hashlib.sha256(data).hexdigest()


def install(path,data):
    """Never replace an existing source or evidence package with different bytes."""
    if path.exists():
        if path.read_bytes()!=data:raise ValueError(f'Existing file differs: {path.name}')
        return False
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)
    return True


def mode_for(stamp,rows,context,media_root=None):
    start=next((r for r in rows if r.get('kind')=='start'),{})
    if 'league' in start:
        return ('league' if start['league'] else 'training'),'explicit log start.league'
    entry=context.get(stamp,{})
    if entry.get('mode') in ('league','training'):
        return entry['mode'],entry.get('mode_from','stored context')
    if media_root:
        collections=[p.parent.name for p in media_root.glob('*/battle-'+stamp+'.times')]
        if len(collections)==1 and collections[0].endswith('-training'):
            return 'training','recording collection '+collections[0]
    # Opponent species do not prove a battle was against a Team Leader.
    raise ValueError(f'Unknown context for {stamp}; provide context.json evidence')


def build_missing(stamp,rows,mode,mode_from,notes,context,teams):
    record=live_record.Battle(stamp,rows).record(notes.get(stamp),context.get(stamp),teams)
    record['source']['mode']=mode
    record['source']['mode_from']=mode_from
    log=f'games/live/{stamp}/log.jsonl' if mode=='league' else f'runs/live/{stamp}.jsonl'
    record['source']['log']=log;record['built_from']=[log]
    return record


def run(root,evidence,logs,source_logs=None,media_root=None):
    root=root.resolve();games=root/'games/live'
    index=read(evidence/'index.json')
    if index is None:raise ValueError('Evidence index missing')
    notes=read(games/'notes.json',{});context=read(games/'context.json',{});teams=read(games/'our_teams.json',{})
    receipt={'schema':'canonical-evidence-import-v1','audited_records':len(index['games']),
             'new_records':[],'preserved_records':[],'source_logs_added':[],
             'evidence_attached':[],'pixel_evidence_attached':[]}
    existing_hashes={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in games.glob('*/game.*') if p.name in ('game.json','game.txt')}
    for summary in index['games']:
        stamp=summary['stamp']
        if not re.fullmatch(r'\d{8}-\d{6}',stamp):raise ValueError('Invalid game ID')
        source=logs/(stamp+'.jsonl');raw=source.read_bytes()
        if sha(raw)!=summary['input_sha256']:raise ValueError(f'Source hash changed for {stamp}')
        rows=[json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
        folder=games/stamp;path=folder/'game.json'
        if path.exists():
            record=read(path)
            if record.get('schema')!='game-record-v1' or record.get('variant')!='live-log':raise ValueError('Existing schema differs')
            receipt['preserved_records'].append(stamp)
        else:
            mode,proof=mode_for(stamp,rows,context,media_root)
            record=build_missing(stamp,rows,mode,proof,notes,context,teams)
            if mode=='league' and record['result']['value'] not in live_record.RESULTS:
                raise ValueError('Unresolved league result; do not guess it')
            folder.mkdir(parents=True,exist_ok=True)
            install(path,(json.dumps(record,indent=1)+'\n').encode())
            install(folder/'game.txt',live_record.text(record).encode())
            context.setdefault(stamp,{}).update(mode=mode,mode_from=proof)
            receipt['new_records'].append(stamp)
        log_path=(root/record['source']['log']).resolve()
        if not log_path.is_relative_to(root):raise ValueError('Record log path escapes repository')
        if install(log_path,raw):receipt['source_logs_added'].append(log_path.relative_to(root).as_posix())
        source_folder=evidence/stamp
        files={'evidence.jsonl.gz':'evidence.jsonl.gz','evidence-summary.json':'summary.json',
               'review-flags.jsonl.gz':'review-flags.jsonl.gz'}
        if (source_folder/'pixel-summary.json').exists():
            files.update({'pixels.jsonl.gz':'pixels.jsonl.gz','pixel-summary.json':'pixel-summary.json'})
            receipt['pixel_evidence_attached'].append(stamp)
        manifest={'schema':'game-enrichment-v1','source_log_sha256':sha(raw),
                  'accuracy_verified':False,'classification':{'mode':record['source']['mode'],
                  'from':record['source'].get('mode_from') or 'existing canonical game record'},
                  'role':'additional observations and logged beliefs; not replacement game truth','files':{}}
        for dest_name,source_name in files.items():
            data=(source_folder/source_name).read_bytes();install(folder/dest_name,data)
            manifest['files'][dest_name]={'sha256':sha(data),'bytes':len(data)}
        install(folder/'enrichment.json',(json.dumps(manifest,indent=2)+'\n').encode())
        receipt['evidence_attached'].append(stamp)
    # Existing records outside this audit also need their referenced source logs.
    missing=[]
    for path in games.glob('*/game.json'):
        rec=read(path);dest=(root/rec['source']['log']).resolve()
        if not dest.is_relative_to(root):raise ValueError('Log path escapes repository')
        if dest.exists():continue
        choices=[logs/(path.parent.name+'.jsonl')]
        if source_logs:choices.append(source_logs/(path.parent.name+'.jsonl'))
        candidate=next((p for p in choices if p.exists()),None)
        if candidate:
            if install(dest,candidate.read_bytes()):receipt['source_logs_added'].append(dest.relative_to(root).as_posix())
        else:missing.append(path.parent.name)
    if missing:raise ValueError('Missing canonical source logs: '+','.join(missing))
    (games/'context.json').write_text(json.dumps(context,indent=1)+'\n',encoding='utf-8')
    for name,value in existing_hashes.items():
        if sha((root/name).read_bytes())!=value:raise ValueError('Existing record changed')
    previous_out=live_record.OUT;previous_root=live_record.ROOT
    try:
        live_record.OUT=games;live_record.ROOT=root;catalog=live_record.write_index()
    finally:live_record.OUT=previous_out;live_record.ROOT=previous_root
    from collections import Counter
    receipt.update(total_records=len(catalog),mode_counts=dict(Counter(e['mode'] for e in catalog)),
                   result_counts_by_mode={mode:dict(Counter(e['result'] for e in catalog if e['mode']==mode)) for mode in set(e['mode'] for e in catalog)},
                   existing_canonical_files_unchanged=len(existing_hashes))
    return receipt


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    ap.add_argument('--evidence',type=Path,required=True);ap.add_argument('--logs',type=Path,required=True)
    ap.add_argument('--source-logs',type=Path);ap.add_argument('--media-root',type=Path)
    ap.add_argument('--receipt',type=Path,required=True)
    a=ap.parse_args();receipt=run(a.root,a.evidence,a.logs,a.source_logs,a.media_root)
    a.receipt.parent.mkdir(parents=True,exist_ok=True);a.receipt.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:receipt[k] for k in ['audited_records','total_records','mode_counts','result_counts_by_mode','existing_canonical_files_unchanged']}))


if __name__=='__main__':main()
