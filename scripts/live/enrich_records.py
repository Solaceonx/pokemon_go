"""Offline evidence sidecars for completed live logs; never connects to a phone.

python scripts/live/enrich_records.py --logs PATH --records games/live --out OUTPUT
Outputs are separate from game.json and preserve input line references. No tuning.
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

SCHEMA = 'battle-evidence-v1'
# Intentionally exclude OCR text, account names, filesystem paths and error messages.
FIELDS = {'action','ms','move','to','foe','was','now','gaps','after_tap_s','cue_t',
          'queued','shield','foe_energy','counted','read','least','most','icons_seen',
          'px','prompted','counted_already','by','result','foes','point','live','note'}
OBS_FIELDS = {'my_species','foe_species','my_hp','foe_hp','my_energy','my_shields',
              'foe_shields','my_left','foe_left','foe_charged','paused','foe_hits','my_hits',
              'my_cp','foe_cp','foe_out_for','my_charged','charged_move','my_fainted'}
FAULTS = {'throw_not_taken','throw_beaten','throw_fainted','throw_cancelled',
          'switch_not_taken','decision_dropped','queued_dropped','tracker_error','engine_error'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def number(x):
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def distribution(values):
    values = sorted(values)
    if not values:
        return {'n':0,'median':None,'p95':None,'max':None}
    return {'n':len(values),'median':round(statistics.median(values),4),
            'p95':round(values[max(0,math.ceil(len(values)*.95)-1)],4),'max':round(values[-1],4)}


def load_log(path):
    raw = Path(path).read_bytes()
    rows = []
    for line, text in enumerate(raw.decode('utf-8-sig').splitlines(),1):
        if not text.strip():
            continue
        row = json.loads(text)
        if not isinstance(row,dict) or not isinstance(row.get('kind'),str) or number(row.get('t')) is None:
            raise ValueError(f'Invalid log row at line {line}')
        rows.append({**row,'line':line})
    return raw,rows


def safe_view(view):
    """Only fields from the documented numeric/species engine view, never arbitrary text."""
    if not isinstance(view,dict) or 'error' in view:
        return None
    mon_fields = {'species','level','ivs','fast','charged','hp','energy','stages'}
    mon = lambda m: {k:v for k,v in m.items() if k in mon_fields} if isinstance(m,dict) else None
    me = view.get('me') or {}
    out = {k:view[k] for k in ['turn','foe_shields','foe_switch_wait','foe_busy','foe_left',
                               'foe_move_odds','foe_energy_odds'] if k in view}
    out.update(me={k:me[k] for k in ['active','shields','switch_wait','busy'] if k in me},
               foe=mon(view.get('foe')),foe_shown=[mon(m) for m in view.get('foe_shown',[])])
    out['me']['team']=[mon(m) for m in me.get('team',[])]
    return out


def analyze(stamp,rows,raw_hash,mode='unknown'):
    start = next((r for r in rows if r['kind']=='start'),None)
    end = next((r for r in reversed(rows) if r['kind']=='end'),None)
    looks = sorted((r for r in rows if r['kind']=='look'),key=lambda r:(r['t'],r['line']))
    if not start or not end or not looks:
        raise ValueError('Requires start, end, and screen readings')
    times=[r['t'] for r in looks]
    evidence=[];anomalies=[];previous={};energy_errors=[];views=0
    for r in rows:
        k,t=r['kind'],r['t']
        if k in ('start','team'):
            continue
        e={'line':r['line'],'t':t,'kind':k}
        if k=='look':
            obs=r.get('obs') or {}
            e.update(observation={key:val for key,val in obs.items() if key in OBS_FIELDS},
                     buttons=r.get('buttons'),counted_energy=r.get('counted'),foe_tracker=r.get('foe'),
                     provenance='logged_screen_observation_and_tracker_belief; not independently verified')
            for side,prefix in [('mine','my'),('theirs','foe')]:
                species=obs.get(prefix+'_species');hp=number(obs.get(prefix+'_hp'))
                if species and hp is not None:
                    prior=previous.get(side)
                    if prior and species==prior[0] and 0<t-prior[1]<=2 and hp-prior[2]>.10:
                        anomalies.append({'kind':'health_increase_review','side':side,'t':t,
                                          'line':r['line'],'previous_line':prior[3],
                                          'species':species,'before':prior[2],'after':hp,
                                          'meaning':'Reading inconsistency or unlogged switch; not evidence of healing'})
                    previous[side]=(species,t,hp,r['line'])
        else:
            # Tap notes are known bot labels; free-form text is never retained.
            e.update({key:val for key,val in r.items() if key in FIELDS and key!='note'})
            if k=='tap':
                e['is_fast_tap']=r.get('note')=='fast move'
                e['provenance']='input_attempt; does not establish an executed move'
            if k in ('decision','throw_before_fainting','throw_before_theirs'):
                i=bisect.bisect_right(times,t)-1
                e['preceding_look_line']=looks[i]['line'] if i>=0 else None
                e['preceding_look_age_seconds']=round(t-times[i],4) if i>=0 else None
                view=safe_view(r.get('view'))
                if view:
                    e['engine_view']=view;views+=1
                    e['view_provenance']='logged_assumed_engine_state; builds and integer HP are not verified actual stats'
                else:
                    e['engine_view']=None
            if k=='energy_read' and number(r.get('counted')) is not None and number(r.get('read')) is not None:
                energy_errors.append(abs(float(r['counted'])-float(r['read'])))
        evidence.append(e)
    counts=Counter(r['kind'] for r in rows)
    energy_looks=sum(number((r.get('obs') or {}).get('my_energy')) is not None for r in looks)
    shield_readings={}
    for side,key in [('mine','my_shields'),('theirs','foe_shields')]:
        vals=[number((r.get('obs') or {}).get(key)) for r in looks]
        vals=[v for v in vals if v is not None and 0<=v<=2]
        shield_readings[side]={'observed_looks':len(vals),'first':vals[0] if vals else None,
                               'minimum':min(vals) if vals else None,
                               'header_decrease':vals[0]-min(vals) if vals else None}
    duration=float(end['t'])
    summary={'stamp':stamp,'mode':mode,'result':end.get('result'),'duration_seconds':duration,
             'input_sha256':raw_hash,'screen_looks':len(looks),'evidence_rows':len(evidence),
             'event_counts':dict(sorted(counts.items())),'fault_counts':{k:counts[k] for k in sorted(FAULTS)},
             'button_energy_observed_looks':energy_looks,'button_energy_look_share':energy_looks/len(looks),
             'look_gap_seconds':distribution([b-a for a,b in zip(times,times[1:])]),
             'count_vs_button_disagreement':distribution(energy_errors),
             'throw_start_delay_seconds':distribution([float(r['after_tap_s']) for r in rows if r['kind']=='throw_started' and number(r.get('after_tap_s')) is not None]),
             'decision_runtime_ms':distribution([float(r['ms']) for r in rows if r['kind']=='decision' and number(r.get('ms')) is not None]),
             'logged_engine_views':views,'decisions_without_logged_view':sum(r['kind']=='decision' and not safe_view(r.get('view')) for r in rows),
             'health_increase_review_flags':len(anomalies),'shield_header_evidence':shield_readings,
             'start_epoch':start.get('epoch'),'bot_commit':start.get('commit'),'bot_dirty':start.get('dirty'),
             'actual_team_ivs_verified':False,'actual_integer_hp_known':False,'accuracy_verified':False}
    return summary,evidence,anomalies


def write_gzip(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=''.join(json.dumps(r,separators=(',',':'),ensure_ascii=False)+'\n' for r in rows).encode()
    path.write_bytes(gzip.compress(data,mtime=0))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--logs',type=Path,required=True)
    ap.add_argument('--records',type=Path,default=Path('games/live'))
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--stamps',nargs='*')
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    summaries=[];skipped=[]
    for path in sorted(args.logs.glob('*.jsonl')):
        if not re.fullmatch(r'\d{8}-\d{6}',path.stem) or args.stamps and path.stem not in args.stamps:
            continue
        try:
            raw,rows=load_log(path)
            record=args.records/path.stem/'game.json'
            mode=json.loads(record.read_text(encoding='utf-8')).get('source',{}).get('mode','unknown') if record.exists() else 'unknown'
            start=next((r for r in rows if r['kind']=='start'),{})
            if mode=='unknown' and start.get('league'):
                mode='league' if 'league' in start['league'].lower() else 'unknown'
            summary,evidence,anomalies=analyze(path.stem,rows,digest(raw),mode)
        except (ValueError,OSError) as exc:
            skipped.append({'stamp':path.stem,'reason':type(exc).__name__});continue
        folder=args.out/path.stem;folder.mkdir(exist_ok=True)
        summary['context_source']='existing_game_record' if record.exists() and mode!='unknown' else 'explicit_start_league' if mode!='unknown' else 'unknown'
        summary['context_record_sha256']=digest(record.read_bytes()) if record.exists() else None
        write_gzip(folder/'evidence.jsonl.gz',evidence)
        write_gzip(folder/'review-flags.jsonl.gz',anomalies)
        summary['evidence_sha256']=digest((folder/'evidence.jsonl.gz').read_bytes())
        summary['evidence_bytes']=(folder/'evidence.jsonl.gz').stat().st_size
        (folder/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        summaries.append(summary)
    aggregate={'schema':SCHEMA,'battles':len(summaries),'screen_looks':sum(s['screen_looks'] for s in summaries),
               'evidence_rows':sum(s['evidence_rows'] for s in summaries),'logged_engine_views':sum(s['logged_engine_views'] for s in summaries),
               'event_counts':dict(sum((Counter(s['event_counts']) for s in summaries),Counter())),
               'mode_counts':dict(Counter(s['mode'] for s in summaries)),
               'accuracy_verified':False,'interpretation':'Logged beliefs and observations, not independently labelled ground truth',
               'storage_bytes':sum(p.stat().st_size for p in args.out.rglob('*') if p.is_file() and p.name!='index.json'),
               'source_code_sha256':digest(Path(__file__).read_bytes()),'games':summaries,'skipped':skipped}
    (args.out/'index.json').write_text(json.dumps(aggregate,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:aggregate[k] for k in ['battles','screen_looks','evidence_rows','logged_engine_views','mode_counts','storage_bytes']}))


if __name__=='__main__':
    main()
