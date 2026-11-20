"""Restore form-native stages after a source-confirmed switch.

Ordinary move modifiers clear, but form-native penalties can persist. Unknown
forms must not acquire a neutral baseline if their legal baselines disagree.
"""
import copy
import math
from functools import lru_cache


@lru_cache(maxsize=1)
def native_stage_data():
    import hashlib,json
    from pathlib import Path
    path=Path(__file__).resolve().parents[2]/'data/gamemaster.json'
    payload=path.read_bytes()
    return json.loads(payload),hashlib.sha256(payload).hexdigest()


def native_stage_options(mon,mon_identity,at,gamemaster):
    from visible_vocabulary import species_key
    key=species_key(mon.get('species',{}).get('value'))
    choices=[p for p in gamemaster.get('pokemon',[]) if key and species_key(p.get('speciesName'))==key]
    form=mon.get('form',{})
    # A later disguise caption must not resolve this earlier entry retrospectively.
    if (form.get('status') in ('observed','retained','inferred') and form.get('identity')==mon_identity
            and number(form.get('observed_at_seconds')) and number(form.get('confirmed_at_seconds'))
            and 0<=form['observed_at_seconds']<=form['confirmed_at_seconds']<=at):
        exact=[p for p in choices if p.get('speciesId')==form.get('value')]
        if exact:choices=exact
    baselines=[]
    for pokemon in choices:
        value=pokemon.get('nativeStatBuffs',[0,0])
        if (not isinstance(value,list) or len(value)!=2
                or any(type(n) is not int or not -4<=n<=4 for n in value)):
            return {name:[] for name in ('attack_stage','defense_stage')}
        baselines.append(value)
    return {name:sorted({pair[i] for pair in baselines})
            for i,name in enumerate(('attack_stage','defense_stage'))}


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def identity(value):
    if (not value or not isinstance(value.get('species'),str) or not value['species']
            or not isinstance(value.get('cp'),int) or isinstance(value['cp'],bool) or value['cp']<=0):
        return None
    return value['species']+':'+str(value['cp'])


def collect(entries, identities, raw_identities, timeline, source_events, alignment=None):
    from visible_vocabulary import species_key
    from creator_form_captions import frame_time
    grouped=[]
    for entry in sorted((e for e in entries if number(e.get('t'))),key=lambda e:e['t']):
        at=frame_time(entry['t'],alignment)
        if not number(at) or at<0:continue
        key=species_key(entry['species'])
        if grouped and grouped[-1]['key']==key and 0<=at-grouped[-1]['last']<=1.5:
            grouped[-1]['last']=at;continue
        grouped.append(dict(t=at,last=at,key=key,species=entry['species']))
    events=[];candidates=[]
    for entry in grouped:
        at=entry['t'];choices=[]
        for side in ('mine','theirs'):
            after=[r for r in identities if at-.75<=r['t']<=at+1.5 and r.get('values',{}).get(side)
                   and species_key(r['values'][side]['species'])==entry['key']
                   and number(r['values'][side].get('first_visible_seconds'))
                   and r['values'][side]['first_visible_seconds']>=at-1.5]
            if not after:continue
            runs={}
            for sample in after:
                value=sample['values'][side]
                runs.setdefault((identity(value),value['first_visible_seconds']),sample)
            if len(runs)!=1:continue
            row=next(iter(runs.values()));value=row['values'][side];current=identity(value)
            seen,first=value.get('confirmed_seconds'),value.get('first_visible_seconds')
            if (not current or not number(seen) or not number(first) or not 0<=row['t']-seen<=.75
                    or not at-1.5<=first<=row['t'] or first>seen):continue
            before=[r for r in identities if first-2<=r['t']<first and r.get('values',{}).get(side)]
            if not before:continue
            old_row=before[-1];old=old_row['values'][side];previous=identity(old)
            old_seen=old.get('confirmed_seconds')
            if (not previous or previous==current or not number(old_seen)
                    or not 0<=old_row['t']-old_seen<=.75 or first-old_seen>2):continue
            confirmed=max(at,seen)
            # Require a real source observation for the returned header, not a
            # future confirmation hidden inside a row with an earlier timestamp.
            if seen>row['t'] or confirmed>at+1.5:continue
            contrary=any((found:=sample.get(side)) and identity(found)!=current
                         for sample in raw_identities if first<=sample['t']<=confirmed)
            if contrary:continue
            # A charge camera may conceal stat changes before the header is
            # finally confirmed. Such a late entry must not reset history now.
            releases=[t for charge in timeline.get('charged',[]) for t in charge.get('announcement_clip_seconds',[])
                      if first<=t<=confirmed]
            notices=[e for e in source_events if e.get('kind') in ('stat_change','stat_notice','form')
                     and first<=e.get('t',-1)<=confirmed]
            if releases or notices:continue
            point=alignment.get(round(at,6),{}) if alignment else {}
            if alignment is not None and not point:continue
            choices.append(dict(kind='stage_reset',status='confirmed',side=side,pokemon=value['species'],cp=value['cp'],
                identity=current,last_pre_entry_header_identity=previous,t=at,confirmed_at_seconds=confirmed,
                first_new_header_seconds=first,last_pre_entry_header_seconds=old_seen,
                source_pts=point.get('source_pts'),source_time_base=point.get('source_time_base'),
                header_source_pts=value.get('source_pts'),header_source_time_base=value.get('source_time_base'),
                ordinary_modifiers_cleared=True,form_baseline_must_be_resolved=True,
                method='literal_entry_and_changed_confirmed_header',
                rule_source='owner_confirmed_switch_out_resets_stages',initial_state_assumed=False,
                exit_identity_status='unresolved',pre_entry_header_role='identity_context',
                occurrence_semantics='first_literal_entry_caption_observed'))
        if len(choices)==1:
            event=choices[0]
            # Repeated text/header observations cannot reset a later buff twice.
            if not any(e['side']==event['side'] and e['identity']==event['identity']
                       and e['first_new_header_seconds']==event['first_new_header_seconds'] for e in events):events.append(event)
        else:
            candidates.append(dict(kind='stage_reset_candidate',t=at,status='unattributed',
                reason='Literal entry lacks one unique changed physical species/CP header',
                possible_sides=len(choices)))
    return dict(schema='source-stage-resets-v3',events=events,candidates=candidates,
                initial_stages_assumed=False,accuracy_verified=False)


def derive(raw,timeline,source_events):
    import hashlib,json
    from pathlib import Path
    from creator_health import rows
    from creator_identity import entry_announcements,confirmed_identities
    samples=rows(raw/'native-identities-3hz.jsonl.gz')
    entries=entry_announcements(raw)
    identities=confirmed_identities(samples,entries)
    path=raw.parent/'frame_alignment.jsonl.gz'
    alignment={round(r['clip_seconds'],6):r for r in rows(path)}
    result=collect(entries,identities,samples,timeline,source_events,alignment)
    result['provenance']=dict(code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        input_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                      (raw/'text.jsonl.gz',raw/'native-identities-3hz.jsonl.gz',path)},
        timeline_sha256=hashlib.sha256(json.dumps(timeline,sort_keys=True,separators=(',',':')).encode()).hexdigest())
    result['provenance']['source_events_sha256']=hashlib.sha256(
        json.dumps(source_events,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    result['provenance']['identity_code_sha256']=hashlib.sha256(
        Path(__file__).with_name('creator_identity.py').read_bytes()).hexdigest()
    result['provenance']['native_stage_data_sha256']=native_stage_data()[1]
    return result


class StageResetEvidence:
    def __init__(self,events=(),gamemaster=None):
        from fractions import Fraction
        import hashlib,json
        if gamemaster is None:self.gamemaster,self.gamemaster_sha256=native_stage_data()
        else:
            self.gamemaster=gamemaster
            self.gamemaster_sha256=hashlib.sha256(json.dumps(gamemaster,sort_keys=True).encode()).hexdigest()
        self.events=[];self.cursor=0
        for event in events:
            observed,confirmed=event.get('t'),event.get('confirmed_at_seconds')
            current=identity(dict(species=event.get('pokemon'),cp=event.get('cp')))
            previous=event.get('last_pre_entry_header_identity')
            before,first=event.get('last_pre_entry_header_seconds'),event.get('first_new_header_seconds')
            valid_previous=False
            if isinstance(previous,str) and ':' in previous:
                species,cp=previous.rsplit(':',1)
                valid_previous=bool(species and cp.isdecimal() and int(cp)>0
                                    and identity(dict(species=species,cp=int(cp)))==previous)
            valid_sources=True
            for prefix in ('','header_'):
                pts,base=event.get(prefix+'source_pts'),event.get(prefix+'source_time_base')
                try:valid_sources&=isinstance(pts,int) and not isinstance(pts,bool) and pts>=0 and isinstance(base,str) and Fraction(base)>0
                except (TypeError,ValueError,ZeroDivisionError):valid_sources=False
            if (event.get('kind')=='stage_reset' and event.get('status')=='confirmed'
                    and event.get('side') in ('mine','theirs') and current and current==event.get('identity')
                    and valid_previous and previous!=current
                    and number(observed) and number(confirmed) and 0<=observed<=confirmed
                    and number(before) and number(first) and 0<=before<first<=confirmed<=observed+1.5
                    and valid_sources
                    and event.get('ordinary_modifiers_cleared') is True
                    and event.get('form_baseline_must_be_resolved') is True
                    and 'attack_stage' not in event and 'defense_stage' not in event
                    and event.get('method')=='literal_entry_and_changed_confirmed_header'
                    and event.get('rule_source')=='owner_confirmed_switch_out_resets_stages'):
                self.events.append(copy.deepcopy(event))
        self.events.sort(key=lambda e:e['confirmed_at_seconds'])

    def advance(self,at,sides):
        applied=[]
        while self.cursor<len(self.events) and self.events[self.cursor]['confirmed_at_seconds']<=at:
            event=self.events[self.cursor];self.cursor+=1
            if at-event['confirmed_at_seconds']>.25:continue
            side='mine' if event['side']=='mine' else 'opponent'
            team=sides[side];mon=team['pokemon'].get(event['identity'])
            if (mon is None or mon['species'].get('value')!=event['pokemon'] or mon['cp'].get('value')!=event['cp']
                    or mon.get('fainted',{}).get('value') is True):continue
            if team.get('active')!=event['identity']:
                # A delayed entry proof cannot overwrite a later bench history.
                continue
            def reset(target,target_identity,method):
                options=native_stage_options(target,target_identity,event['t'],self.gamemaster)
                for name,values in options.items():
                    certain=len(values)==1
                    target[name]=dict(value=values[0] if certain else None,status='inferred' if certain else 'unknown',
                        observed_at_seconds=event['t'],confirmed_at_seconds=max(at,event['confirmed_at_seconds']),
                        method=method,rule_source=event['rule_source'],identity=target_identity,
                        form_baseline_candidates=values,native_stage_data_sha256=self.gamemaster_sha256,
                        form_baseline_rule='ordinary_modifiers_reset_to_form_native_stages',accuracy_verified=False)
                    if not certain:target[name]['reason']='Source form does not establish one native stage baseline'
                    applied.append((side,target_identity,name))
            reset(mon,event['identity'],event['method'])
            # Every known non-active, non-fainted teammate is on the bench.
            # Restore native baselines, not a blanket zero (Busted Mimikyu
            # retains its native Defense penalty). No exit actor is guessed.
            for bench_identity,outgoing in team['pokemon'].items():
                if bench_identity==event['identity'] or outgoing.get('fainted',{}).get('value') is True:continue
                reset(outgoing,bench_identity,'known_bench_native_stages_after_confirmed_entry')
                for name in ('attack_stage','defense_stage'):
                    outgoing[name].update(source_entry_identity=event['identity'],exit_identity_status='unresolved')
        return applied
