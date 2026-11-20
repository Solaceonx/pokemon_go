"""Retain literal stat banners without inventing their target or magnitude.

The legacy text sample has no bounds. A banner alone therefore cannot identify
its owner, and cannot establish an exact stage. It invalidates known active
stages conservatively; bench stages are unaffected.
"""
import copy
import re
from fractions import Fraction
from creator_stage_resets import number


def parse(text):
    if not isinstance(text,str):return None
    words=' '.join(text.lower().strip(' !.\t\r\n').split())
    match=re.fullmatch(r'(attack|defense) (?:(sharply|harshly|drastically|severely) )?(rose|fell)(?: (sharply|harshly|drastically|severely))?',words)
    if not match or (match[2] and match[4]):return None
    modifier=match[2] or match[4]
    direction='increase' if match[3]=='rose' else 'decrease'
    category={("increase",None):1,("decrease",None):1,
              ("increase","sharply"):2,("decrease","harshly"):2,
              ("increase","drastically"):3,("decrease","severely"):3}.get((direction,modifier))
    if category is None:return None
    sign=1 if direction=='increase' else -1
    return dict(stat=match[1]+'_stage',direction=direction,wording_modifier=modifier,
                message_change_step_candidates=[sign*category] if category<3 else sorted([sign*3,sign*4]),
                wording_resource_id='combat_'+('buff' if sign==1 else 'debuff')+'_lvl'+str(category),
                stage_delta=None,change_application='unresolved; a banner can redisplay a form-native effect')


def collect(text_rows,alignment):
    events=[];last={}
    for row in sorted((r for r in text_rows if number(r.get('t'))),key=lambda r:r['t']):
        point=alignment.get(round(row['t'],6))
        if not point:continue
        at=point['clip_seconds']
        for _,text in row.get('text',[]):
            notice=parse(text)
            if notice is None:continue
            key=(notice['stat'],notice['direction'],notice['wording_modifier'])
            previous=last.get(key);last[key]=at
            if previous is not None and 0<=at-previous<=1.5:continue
            events.append(dict(kind='stat_notice',t=at,confirmed_at_seconds=at,
                source_pts=point['source_pts'],source_time_base=point['source_time_base'],
                status='observed',side=None,target_identity=None,**notice,
                method='literal_stat_banner_without_spatial_owner',
                occurrence_semantics='first_sampled_literal_banner',accuracy_verified=False))
    return dict(schema='literal-stat-notices-v2',events=events,side_attribution_established=False,
                exact_stages_established=False,accuracy_verified=False)


def derive(raw):
    import hashlib
    from pathlib import Path
    from creator_health import rows
    alignment_path=raw.parent/'frame_alignment.jsonl.gz'
    result=collect(rows(raw/'text.jsonl.gz'),{round(r['clip_seconds'],6):r for r in rows(alignment_path)})
    result['provenance']=dict(code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        input_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (raw/'text.jsonl.gz',alignment_path)})
    return result


class StatNoticeEvidence:
    def __init__(self,events=()):
        self.events=[];self.cursor=0
        for event in events:
            at,confirmed=event.get('t'),event.get('confirmed_at_seconds')
            pts=event.get('source_pts');base=event.get('source_time_base')
            try:valid=isinstance(base,str) and Fraction(base)>0
            except (ValueError,ZeroDivisionError):valid=False
            if (event.get('kind')=='stat_notice' and event.get('status')=='observed'
                    and event.get('stat') in ('attack_stage','defense_stage')
                    and event.get('direction') in ('increase','decrease')
                    and event.get('side') is None and event.get('target_identity') is None
                    and event.get('stage_delta') is None
                    and event.get('method')=='literal_stat_banner_without_spatial_owner'
                    and number(at) and at>=0 and confirmed==at
                    and type(pts) is int and pts>=0 and valid):
                self.events.append(copy.deepcopy(event))
        self.events.sort(key=lambda e:e['confirmed_at_seconds'])

    def advance(self,at,sides):
        changed=[]
        while self.cursor<len(self.events) and self.events[self.cursor]['confirmed_at_seconds']<=at:
            event=self.events[self.cursor];self.cursor+=1
            if at-event['confirmed_at_seconds']>.25:continue
            for side,team in sides.items():
                identity=team.get('active');mon=team['pokemon'].get(identity)
                if mon is None or mon.get('fainted',{}).get('value') is True:continue
                mon[event['stat']]=dict(value=None,status='unknown',
                    reason='Literal stat banner has unresolved target and magnitude',
                    observed_at_seconds=event['t'],confirmed_at_seconds=at,
                    notice_direction=event['direction'],notice_target_unresolved=True,
                    method=event['method'],accuracy_verified=False)
                changed.append((side,identity,event['stat']))
        return changed
