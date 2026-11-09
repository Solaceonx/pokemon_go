"""Build a standalone local evidence browser with existing video references, no video copies."""
import argparse
import base64
import json
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--evidence',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--media-root',type=Path)
    args=ap.parse_args()
    index=json.loads((args.evidence/'index.json').read_text(encoding='utf-8'))
    videos={p.stem.removeprefix('battle-'):p for p in args.media_root.glob('*/battle-*.mp4')} if args.media_root else {}
    games=[]
    for summary in index['games']:
        stamp=summary['stamp'];folder=args.evidence/stamp
        entry={'summary':summary,'evidence':base64.b64encode((folder/'evidence.jsonl.gz').read_bytes()).decode(),
               'flags':base64.b64encode((folder/'review-flags.jsonl.gz').read_bytes()).decode()}
        pixel=folder/'pixels.jsonl.gz';receipt=folder/'pixel-summary.json'
        if pixel.exists() and receipt.exists():
            entry.update(pixels=base64.b64encode(pixel.read_bytes()).decode(),pixel_summary=json.loads(receipt.read_text()))
        video=videos.get(stamp)
        if video and isinstance(summary.get('start_epoch'),(int,float)) and video.with_suffix('.times').is_file():
            first=float(video.with_suffix('.times').read_text().splitlines()[0])
            entry.update(video=video.resolve().as_uri(),video_log_offset=first-summary['start_epoch'])
        games.append(entry)
    data={'battles':index['battles'],'looks':index['screen_looks'],'rows':index['evidence_rows'],'games':games}
    template=Path(__file__).with_name('evidence_viewer.html').read_text(encoding='utf-8')
    # JSON is data, including when used in a script element.
    html=template.replace('__EVIDENCE_DATA__',json.dumps(data,separators=(',',':')).replace('<','\\u003c'))
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(html,encoding='utf-8')
    print(json.dumps({'battles':len(games),'video_references':sum('video' in g for g in games),
                      'pixel_rereads':sum('pixels' in g for g in games),'html_bytes':args.out.stat().st_size,'embedded_video_bytes':0}))


if __name__=='__main__':main()
