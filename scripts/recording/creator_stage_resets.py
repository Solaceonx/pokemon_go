"""Infer neutral stages only from a literal entry and a changed physical header.

The owner confirms that switching out clears attack/defense changes. An old or
first header alone is not an observed switch. No starting stages are supplied
for clipped footage, and a late header cannot erase an intervening effect.
"""
import copy
import math


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
            notices=[e for e in source_events if e.get('kind') in ('stat_change','stat_notice')
                     and first<=e.get('t',-1)<=confirmed]
            if releases or notices:continue
            point=alignment.get(round(at,6),{}) if alignment else {}
            if alignment is not None and not point:continue
            choices.append(dict(kind='stage_reset',status='confirmed',side=side,pokemon=value['species'],cp=value['cp'],
                identity=current,last_pre_entry_header_identity=previous,t=at,confirmed_at_seconds=confirmed,
                first_new_header_seconds=first,last_pre_entry_header_seconds=old_seen,
                source_pts=point.get('source_pts'),source_time_base=point.get('source_time_base'),
                header_source_pts=value.get('source_pts'),header_source_time_base=value.get('source_time_base'),
                attack_stage=0,defense_stage=0,method='literal_entry_and_changed_confirmed_header',
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
    return dict(schema='source-stage-resets-v2',events=events,candidates=candidates,
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
    return result


class StageResetEvidence:
    def __init__(self,events=()):
        from fractions import Fraction
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
                    and all(type(event.get(name)) is int and event[name]==0 for name in ('attack_stage','defense_stage'))
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
            for name in ('attack_stage','defense_stage'):
                mon[name]=dict(value=0,status='inferred',observed_at_seconds=event['t'],
                    confirmed_at_seconds=max(at,event['confirmed_at_seconds']),method=event['method'],
                    rule_source=event['rule_source'],identity=event['identity'],accuracy_verified=False)
                applied.append((side,event['identity'],name))
            # Every known non-active, non-fainted teammate is on the bench.
            # Neutrality follows from the owner's reset rule, without claiming
            # which one was the direct predecessor of this entry.
            for bench_identity,outgoing in team['pokemon'].items():
                if bench_identity==event['identity'] or outgoing.get('fainted',{}).get('value') is True:continue
                for name in ('attack_stage','defense_stage'):
                    outgoing[name]=dict(value=0,status='inferred',observed_at_seconds=event['t'],
                        confirmed_at_seconds=max(at,event['confirmed_at_seconds']),method='known_bench_stages_neutral_after_confirmed_entry',
                        rule_source=event['rule_source'],identity=bench_identity,
                        source_entry_identity=event['identity'],exit_identity_status='unresolved',accuracy_verified=False)
                    applied.append((side,bench_identity,name))
        return applied
