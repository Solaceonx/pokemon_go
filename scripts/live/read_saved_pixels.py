"""Read a saved Android recording with a pinned screen-only module. No device API.

python scripts/live/read_saved_pixels.py STAMP --media FOLDER --log FILE
    --reader-root SNAPSHOT --out FOLDER [--hz 5]
Requires existing PyAV/numpy; no OCR, downloads, taps, or player imports.
"""
from __future__ import annotations
import argparse
import bisect
from dataclasses import asdict
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


def native(value):
    if hasattr(value,'item'):
        return value.item()
    raise TypeError(f'Cannot serialize {type(value).__name__}')


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def frame_times(path):
    times=[float(line) for line in path.read_text().splitlines() if line.strip()]
    if not times or any(not math.isfinite(t) for t in times) or any(b<a for a,b in zip(times,times[1:])):
        raise ValueError('Frame timestamps must be finite and nondecreasing')
    return times


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stamp');ap.add_argument('--media',type=Path,required=True)
    ap.add_argument('--log',type=Path,required=True);ap.add_argument('--reader-root',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--hz',type=float,default=5)
    args=ap.parse_args()
    if not 0<args.hz<=30:ap.error('--hz must be in (0,30]')
    import av
    from enrich_records import distribution,load_log
    raw,rows=load_log(args.log)
    start=next(r for r in rows if r['kind']=='start');epoch=start['epoch']
    end=next(r['t'] for r in reversed(rows) if r['kind']=='end')
    looks=sorted((r for r in rows if r['kind']=='look'),key=lambda r:r['t']);look_times=[r['t'] for r in looks]
    team=next(r['team'] for r in rows if r['kind']=='team')
    gm_path=Path(__file__).resolve().parents[2]/'data/gamemaster.json'
    costs={m['moveId']:m.get('energy') for m in json.loads(gm_path.read_text())['moves']}
    team_costs={sid:[costs.get(m) for m in moves] for sid,_,moves,_ in team}
    module_path=args.reader_root/'pogo/android_screen.py'
    spec=importlib.util.spec_from_file_location('_pinned_screen_reader',module_path)
    screen=importlib.util.module_from_spec(spec);sys.modules[spec.name]=screen;spec.loader.exec_module(screen)
    # android_screen imports the button geometry relative to its own file.
    dependency=args.reader_root/'scripts/recording/buttons.py'
    if not dependency.is_file():raise ValueError('Pinned button dependency missing')
    sys.path.insert(0,str(dependency.parent));sys.modules.pop('buttons',None)
    video=args.media/f'battle-{args.stamp}.h264';times_path=video.with_suffix('.times')
    times=frame_times(times_path)
    args.out.mkdir(parents=True,exist_ok=True)
    output=args.out/'pixels.jsonl.gz';temporary=args.out/'pixels.jsonl.gz.incomplete'
    frames=sampled=heads=raw_mine=raw_theirs=held_mine=held_theirs=energy_n=typed=0
    disagreements=[];last=-math.inf;comparison_n=logged_energy_n=0
    direct_additions=0;additional_bars=0
    with av.open(str(video),format='h264') as container,gzip.open(temporary,'wt',encoding='utf-8') as sink:
        for i,frame in enumerate(container.decode(video=0)):
            frames+=1
            if i>=len(times):continue  # buffered tail frames have no saved wall-clock timestamp
            t=times[i]-epoch
            if t<0 or t>end or t-last<1/args.hz-1e-6:continue
            last=t;sampled+=1
            a=frame.to_ndarray(format='rgb24')
            if a.shape[1]/a.shape[0] < .43 or a.shape[1]/a.shape[0] > .47:
                raise ValueError('Reader is calibrated for a 540:1200 Android phone, not this layout')
            raw_bars=screen.bars(a);look=screen.read(a,t)
            levels=[screen.button_level(a,k) for k in (0,1)]
            labels=screen.button_labels(a)
            types={side:screen.header_types(a,side) for side in ['mine','theirs']} if look.header else {}
            heads+=look.header;typed+=bool(types.get('theirs'))
            raw_mine+='mine' in raw_bars;raw_theirs+='theirs' in raw_bars
            held_mine+='mine' in look.bars;held_theirs+='theirs' in look.bars
            j=bisect.bisect_right(look_times,t)-1
            before=looks[j] if j>=0 and t-look_times[j]<=.75 else None
            observation=before.get('obs',{}) if before else {}
            species=observation.get('my_species');charged_costs=team_costs.get(species)
            energy=screen.my_energy(a,charged_costs) if charged_costs and all(isinstance(c,(int,float)) and c>0 for c in charged_costs) and look.header else None
            energy_n+=energy is not None
            if before:
                comparison_n+=1
                logged_energy_n+=observation.get('my_energy') is not None
                direct_additions+=energy is not None and observation.get('my_energy') is None
                additional_bars+=look.header and 'mine' in look.bars and observation.get('my_hp') is None
                for side,key in [('mine','my_hp'),('theirs','foe_hp')]:
                    old=observation.get(key);fresh=look.bars.get(side)
                    if isinstance(old,(int,float)) and fresh is not None:
                        disagreements.append(abs(old-fresh))
            evidence={'frame_index':i,'t':round(t,6),'epoch':times[i],
                      'pixels':asdict(look),'raw_bar_fractions':raw_bars,'header_types':types,
                      'button_levels':levels,'move_name_visible':labels,'button_energy_estimate':energy,
                      'energy_context':{'species_from_preceding_logged_look':species,'charged_costs':charged_costs},
                      'preceding_log_line':before['line'] if before else None,
                      'preceding_log_age_seconds':round(t-before['t'],6) if before else None,
                      'accuracy_verified':False}
            sink.write(json.dumps(evidence,separators=(',',':'),default=native)+'\n')
    temporary.replace(output)
    report={'schema':'offline-pixel-evidence-v1','stamp':args.stamp,'sample_hz':args.hz,
            'decoded_frames':frames,'frame_timestamp_rows':len(times),'sampled_frames':sampled,'header_frames':heads,
            'timestamp_mapping':'decoded frame order to saved arrival-time order; not independently verified',
            'untimed_decoded_frames_skipped':max(0,frames-len(times)),
            'timestamp_rows_without_decoded_frame':max(0,len(times)-frames),
            'complete_frame_timestamp_coverage':frames==len(times),
            'raw_bar_read_frames':{'mine':raw_mine,'theirs':raw_theirs},
            'filtered_or_reacquired_bar_read_frames':{'mine':held_mine,'theirs':held_theirs},
            'foe_type_icon_frames':typed,'button_energy_estimate_frames':energy_n,
            'aligned_comparison_frames':comparison_n,'aligned_frames_with_old_energy':logged_energy_n,
            'fresh_energy_when_preceding_log_had_none':direct_additions,
            'fresh_my_bar_when_preceding_log_had_none':additional_bars,
            'bar_disagreement_with_preceding_log':distribution(disagreements),
            'input_sha256':{'video':sha(video),'times':sha(times_path),'log':hashlib.sha256(raw).hexdigest(),
                            'screen_reader':sha(module_path),'buttons':sha(dependency),'game_data':sha(gm_path),
                            'offline_reader':sha(Path(__file__))},
            'output_sha256':sha(output),'output_bytes':output.stat().st_size,'accuracy_verified':False,
            'limitations':['No manual accuracy labels; additional readings are candidates, not verified corrections.',
                           'Comparison uses the most recent logged look up to 0.75s earlier; actual state may change.',
                           'Filtered/reacquired bars include temporal hypotheses; raw bars are exported separately.',
                           'Move-cost context is from logged team/species, not independently recognized species.',
                           'Type-icon observations do not uniquely identify a species or form.']}
    (args.out/'pixel-summary.json').write_text(json.dumps(report,indent=2,default=native)+'\n',encoding='utf-8')
    print(json.dumps(report,default=native),flush=True)


if __name__=='__main__':main()
