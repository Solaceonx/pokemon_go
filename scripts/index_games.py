"""Index canonical recorded game files, keeping records, camera views and games distinct."""
import argparse
from collections import Counter
import json
from pathlib import Path


def build(root):
    games=root/'games';entries=[]
    for path in sorted(games.rglob('game.json')):
        if 'example' in path.relative_to(games).parts:continue
        rec=json.loads(path.read_text(encoding='utf-8'))
        if rec.get('schema')!='game-record-v1':continue
        source=rec.get('source',{});kind=source.get('kind');mode=source.get('mode')
        entry={'id':rec['game'],'record':path.relative_to(root).as_posix(),
               'play_by_play':path.with_suffix('.txt').relative_to(root).as_posix(),
               'kind':kind,'mode':mode,'result':rec['result']['value'],
               'seconds':rec.get('seconds'),'match_id':source.get('match_id'),
               'view':source.get('view'),'fragment_of':rec['result'].get('fragment_of')}
        if kind=='live_bot':
            stamp=path.parent.name
            entry['group']='live:'+(entry['fragment_of'] or stamp)
            entry['log']=source['log']
            if (path.parent/'enrichment.json').exists():entry['evidence']=(path.parent/'enrichment.json').relative_to(root).as_posix()
        elif kind=='public_footage':entry['group']='public:'+(source.get('match_id') or entry['id'])
        else:entry['group']='recording-segment:'+entry['id']
        entries.append(entry)
    live=[e for e in entries if e['kind']=='live_bot'];public=[e for e in entries if e['kind']=='public_footage']
    own=[e for e in entries if e['kind']=='own_recording']
    counts={'total_canonical_records':len(entries),'live_records':len(live),
            'league_completed_games':sum(e['mode']=='league' and e['result'] in ('win','loss','draw') for e in live),
            'league_fragments':sum(e['mode']=='league' and e['result']=='fragment' for e in live),
            'training_records':sum(e['mode']=='training' for e in live),
            'training_unresolved_results':sum(e['mode']=='training' and e['result'] is None for e in live),
            'public_player_view_records':len(public),'public_match_id_groups':len({e['group'] for e in public}),
            'own_recording_segments':len(own),'live_records_with_extra_evidence':sum('evidence' in e for e in live)}
    return {'schema':'game-library-index-v1','counts':counts,
            'counting_note':'Records are not all unique games. Public match IDs group cameras; own recording segments may overlap. Synthetic examples and untracked video-only clips are excluded.',
            'games':entries}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument('--check',action='store_true');a=ap.parse_args();catalog=build(a.root)
    output=a.root/'games/catalog.json';text=json.dumps(catalog,indent=2)+'\n'
    if a.check:
        if not output.exists() or output.read_text(encoding='utf-8')!=text:raise SystemExit('Game catalog is stale')
    else:output.write_text(text,encoding='utf-8')
    print(json.dumps(catalog['counts']))


if __name__=='__main__':main()
