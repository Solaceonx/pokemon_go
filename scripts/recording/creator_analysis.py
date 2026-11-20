"""Creator decision helpers; uncertainty is clustered by battle, not frame."""
from collections import defaultdict
import random
import statistics

def energy_bucket(low, high=None):
    high=low if high is None else high
    if low is None or high is None:return 'unknown'
    bucket=lambda x:'<35' if x<35 else '35-54' if x<55 else '55-74' if x<75 else '75+'
    return bucket(low) if bucket(low)==bucket(high) else 'range_crosses_buckets'

def clustered_difference(rows,seed=46):
    groups=defaultdict(list)
    for row in rows:
        if not row['agree']:groups[row['game']].append(row['bot_wins']-row['human_wins'])
    values=[statistics.mean(v) for v in groups.values()]
    if not values:return {'battles':0,'mean':None,'interval95':None}
    result={'battles':len(values),'mean':statistics.mean(values),'interval95':None}
    if len(values)>1:
        rng=random.Random(seed)
        means=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(2000))
        result['interval95']=[means[49],means[1949]]
    return result

def main():
    import argparse,json,sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'scripts'))
    import real_decisions as rd
    ap=argparse.ArgumentParser(description='Inspect creator decisions without treating inferred tracker states as truth')
    ap.add_argument('folders',nargs='+',type=Path);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();games=[];counts=defaultdict(int)
    for folder in a.folders:
        record=json.loads((folder/'game.json').read_text(encoding='utf-8'))
        verdict=json.loads((folder/'verdict.json').read_text(encoding='utf-8'))
        try:decisions=rd.decisions(folder)
        except (KeyError,ValueError,IndexError) as error:
            games.append({'game':folder.name,'decision_input_error':type(error).__name__});continue
        by_kind=defaultdict(int)
        for d in decisions:by_kind[d['kind']]+=1;counts[d['kind']]+=1
        games.append({'game':folder.name,'proposed_decisions':dict(by_kind),'ending_verdict':verdict['verdict'],
          'failed_checks':verdict.get('failed',[]),'scored_decisions':0,
          'comparison_status':'not_scored_pending_independent_action_and_state_review',
          'interpretation':'A proposed throw/shield/switch from tracker outputs is not a verified creator decision'})
    a.out.parent.mkdir(parents=True,exist_ok=True)
    report={'schema':'creator-decision-readiness-v1','games':games,'proposed_decisions':dict(counts),
            'scored_decisions':0,'task42_habits_ready':False,'accuracy_verified':False}
    a.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':main()
