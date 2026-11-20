"""Build a reproducible creator-footage queue from completed channel listings.

Listings are yt-dlp flat-playlist JSON, stored locally. A title is not proof of
content, league, skill, or uniqueness. Actual cut/track receipts update the queue.
No arbitrary video titles or in-game trainer names are written to the public CSV.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re

CHANNELS={
 'reis2occasion':{'twitch':'https://www.twitch.tv/reis2occasion/videos?filter=archives&sort=time','youtube':'https://www.youtube.com/@Reis2TheOccasion/videos'},
 'homeslicehenry':{'twitch':'https://www.twitch.tv/homeslicehenry/videos?filter=archives&sort=time','youtube':'https://www.youtube.com/@HomeSliceHenry/videos'},
 'itsaxn':{'twitch':'https://www.twitch.tv/itsaxn/videos?filter=archives&sort=time','youtube':'https://www.youtube.com/@ItsAXN/videos'}}
NON_BATTLE=re.compile(r'\btier\s*list|\b(team|teams|meta)\s+(guide|discussion|preview)|\bnews\b|\bpatch\s*notes|\bcard\s*(opening|pack)|\btc[g]?\b|\bhow to (catch|evolve)|\b(q\s*&\s*a|podcast)\b',re.I)


def classify(entry,platform):
    if entry.get('is_live') or entry.get('live_status') in ('is_live','is_upcoming'):
        return 'excluded','not_completed'
    title=entry.get('title') or ''
    duration=entry.get('duration')
    if duration is not None and duration<60:return 'excluded','short_teaser'
    if NON_BATTLE.search(title):return 'excluded','title_indicates_non_battle_content'
    return 'candidate','requires_frame_review'


def league_from_title(title):
    if re.search(r'\bmaster\b',title,re.I):return 'Master League'
    if re.search(r'\bultra\b|\bUL\b',title,re.I):return 'Ultra League'
    if re.search(r'\bgreat\b|\bGL\b',title,re.I):return 'Great League'
    if re.search(r'\b(halloween|color|colour|sunshine|psychic|catch|retro|fossil)\s*cup\b',title,re.I):return 'Great League (cup; title evidence only)'
    if re.search(r'\blittle\b',title,re.I):return 'Little Cup'
    return 'unknown'


def catalog(folder):
    queue=[];receipts=[]
    for channel,urls in CHANNELS.items():
        for platform,url in urls.items():
            path=folder/f'{channel}-{platform}.json'
            if not path.is_file():raise ValueError(f'Missing completed listing: {path.name}')
            listing=json.loads(path.read_text(encoding='utf-8'));entries=[e for e in listing.get('entries',[]) if e]
            counts=Counter()
            for entry in entries:
                sid=str(entry.get('id') or '').removeprefix('v') if platform=='twitch' else str(entry.get('id') or '')
                if not sid:continue
                status,reason=classify(entry,platform);counts[status]+=1
                if status=='excluded':continue
                date=entry.get('upload_date') or ''
                if re.fullmatch(r'\d{8}',date):date=f'{date[:4]}-{date[4:6]}-{date[6:]}'
                queue.append({'platform':platform,'source_id':sid,
                    'url':f'https://www.twitch.tv/videos/{sid}' if platform=='twitch' else f'https://www.youtube.com/watch?v={sid}',
                    'channel':channel,'date':date,'league':league_from_title(entry.get('title') or ''),
                    'role':'creator_footage','content_status':'candidate_requires_frame_review',
                    'league_evidence':'title_only_unverified','duplicate_of':'','intake_status':'queued',
                    'duration_seconds':entry.get('duration'),'listing_index':len(queue),
                    'priority':0 if platform=='twitch' else 1})
            receipts.append({'channel':channel,'platform':platform,'listing_url':url,
                             'channel_id':listing.get('channel_id'),'listed_entries':len(entries),'classifications':dict(counts)})
    # Oldest Twitch archives first; YouTube stays in listing order until duplicates
    # can be matched against tracked VOD battle signatures.
    queue.sort(key=lambda e:(e['priority'],int(e['source_id']) if e['platform']=='twitch' and e['source_id'].isdigit() else e['listing_index']))
    return queue,receipts


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--catalog-root',type=Path,required=True)
    ap.add_argument('--queue',type=Path,required=True);ap.add_argument('--csv',type=Path,default=Path('data/video_sources.csv'))
    ap.add_argument('--receipt',type=Path,required=True);a=ap.parse_args();queue,receipts=catalog(a.catalog_root)
    if a.queue.exists():
        old=json.loads(a.queue.read_text(encoding='utf-8'));lookup={(r['platform'],r['source_id']):r for r in old}
        for r in queue:
            previous=lookup.get((r['platform'],r['source_id']))
            if previous:
                r.update({k:v for k,v in previous.items() if k not in ('listing_index','priority')})
    a.queue.parent.mkdir(parents=True,exist_ok=True);a.queue.write_text(json.dumps(queue,indent=2)+'\n',encoding='utf-8')
    with a.csv.open(newline='',encoding='utf-8') as stream:
        reader=csv.DictReader(stream);fields=list(reader.fieldnames);existing=list(reader)
    for name in ['content_status','league_evidence','duplicate_of','intake_status']:
        if name not in fields:fields.append(name)
    ids={(r['platform'],r['source_id']) for r in existing}
    for q in queue:
        if (q['platform'],q['source_id']) in ids:continue
        existing.append({**{k:q.get(k,'') for k in fields},'layout':'auto_pending_review',
                         'rank_evidence':'Channel listing; individual rank and battle content not independently verified'})
    with a.csv.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(existing)
    result={'schema':'creator-source-catalog-v1','date':'2026-11-09','listings':receipts,
            'candidate_sources':len(queue),'candidate_hours':round(sum(r['duration_seconds'] or 0 for r in queue)/3600,2),
            'candidate_content_verified':False,'duplicate_detection_complete':False}
    a.receipt.parent.mkdir(parents=True,exist_ok=True);a.receipt.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
