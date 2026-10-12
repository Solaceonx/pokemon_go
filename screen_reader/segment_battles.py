"""Propose battle boundaries from sampled video frames, independently of labels.

The detector uses calibrated phone viewports, large countdown numerals and visible
HUD resets. It does not guess battle time zero, removed footage, or exact results.
Reviewed fixture boundaries are read only by the separate evaluation command.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import math
import re
import time
from pathlib import Path

from button_reader import ROOT, cv2, np
from local_ocr import LocalOCR
import av

VERSION = "countdown-hud-reset-v1"


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def recognize(ocr, rgb):
    result, _ = ocr.engine(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), use_det=False, use_cls=False)
    if not result:
        return "", 0.0
    return str(result[0][0]).strip(), float(result[0][1])


def countdown_cue(rgb, ocr):
    roi = rgb[350:730, 65:445]
    low = roi.min(axis=2)
    white = ((low > 225) & ((roi.max(axis=2)-low) < 25)).astype("uint8") * 255
    _, _, stats, _ = cv2.connectedComponentsWithStats(white)
    for x, y, width, height, area in stats[1:]:
        if not (115 <= height <= 280 and 30 <= width <= 230 and area >= 1800):
            continue
        patch = 255-white[y:y+height, x:x+width]
        patch = cv2.copyMakeBorder(patch, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        text, score = recognize(ocr, cv2.cvtColor(patch, cv2.COLOR_GRAY2RGB))
        if text in {"1", "2", "3"} and score >= .92:
            return {"digit": int(text), "confidence": round(score, 5),
                    "bounds": [int(x+65), int(y+350), int(x+65+width), int(y+350+height)]}
    return None


def hud_markers(rgb, marker_y):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    def red(x):
        p = hsv[max(0,marker_y-12):marker_y+13, max(0,x-8):x+9]
        m = ((p[:,:,0] < 12) | (p[:,:,0] > 170)) & (p[:,:,1] > 120) & (p[:,:,2] > 140)
        return bool(m.sum() >= 12)
    def shield(x):
        p = hsv[max(0,marker_y-10):marker_y+11, x-6:x+7]
        colored = (p[:,:,0] >= 115) & (p[:,:,0] <= 170) & (p[:,:,1] > 55)
        bright = colored & (p[:,:,2] > 165)
        if bright.sum() >= 16:
            return True
        if colored.sum() >= 16:
            return False
        return None
    party = [sum(red(x) for x in group) for group in [[26,54,82],[427,455,482]]]
    shield_states = [shield(x) for x in [118,143,365,389]]
    return party, sum(shield_states) if None not in shield_states else None


def sample_features(rgb, profile, ocr):
    y0,y1 = profile["name_y"]
    cp = []
    for x in [130,300]:
        text, confidence = recognize(ocr, rgb[max(0,y0-9):y1+3, x:x+86])
        match = re.fullmatch(r"CP\s*(\d{2,5})", text, re.I)
        cp.append(int(match[1]) if match and confidence >= .80 else None)
    hud = None not in cp
    party, shields = hud_markers(rgb, profile["marker_y"]) if hud else (None,None)
    digit = countdown_cue(rgb, ocr)
    # Result and VS text do not use the same geometry as the HUD. Only run the
    # slower text detector when the battle header is absent, at a modest cadence.
    return {"hud":hud, "cp":cp, "party":party, "shields_total":shields, "countdown":digit}


def scan_video(video, profile, *, interval=.5, limit=None, output=None):
    if interval <= 0:
        raise ValueError("Sample interval must be positive")
    video = Path(video)
    ocr = LocalOCR()
    samples = []
    last = -math.inf
    last_context_ocr = -math.inf
    begin = time.monotonic()
    next_progress = 60
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 4
        duration = float(container.duration / av.time_base) if container.duration else None
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            timestamp = float(frame.pts * frame.time_base)
            if limit is not None and timestamp >= limit:
                break
            if timestamp-last < interval-1e-7:
                continue
            last = timestamp
            x,y,width,height = profile["viewport"]
            if min(x,y) < 0 or min(width,height) <= 0 or x+width > frame.width or y+height > frame.height:
                raise ValueError("Viewport lies outside the video frame")
            rgb = np.asarray(frame.to_image().crop((x,y,x+width,y+height)).resize((508,1080)))
            row = {"t": round(timestamp,6), "source_pts":frame.pts,
                   "source_time_base":str(frame.time_base), **sample_features(rgb,profile,ocr)}
            if not row["hud"] and timestamp-last_context_ocr >= 1.5 and not row["countdown"]:
                last_context_ocr = timestamp
                records = ocr.read(rgb[160:850])
                text = " ".join(r["text"] for r in records)
                normalized = re.sub(r"[^A-Z]", "", text.upper())
                row["context_text"] = text
                row["battle_starting"] = "BATTLESTARTING" in normalized
                row["result"] = next((name for key,name in [("YOUWIN","win"),("GOODEFFORT","loss"),("YOULOSE","loss"),("DRAW","draw")] if key in normalized),None)
            samples.append(row)
            if timestamp >= next_progress:
                print(json.dumps({"scanned_seconds":round(timestamp,1),"samples":len(samples),
                                  "elapsed_seconds":round(time.monotonic()-begin,1)}), flush=True)
                next_progress += 60
    facts = {"schema":"battle-segmentation-samples-v1", "detector":VERSION,
             "video":str(video.resolve()), "source_sha256":file_sha256(video),
             "profile":profile, "sample_interval_seconds":interval,
             "duration_seconds":duration, "limited_to_seconds":limit, "samples":samples}
    if output:
        path = Path(output); path.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(path,"wt",encoding="utf-8") as stream:
            json.dump(facts,stream,separators=(",",":"),ensure_ascii=False)
    return facts


def propose_segments(facts, source_id):
    samples = facts["samples"]
    if not samples:
        return []
    interval = max(facts["sample_interval_seconds"], max((b["t"]-a["t"] for a,b in zip(samples,samples[1:])),default=0))
    duration = facts.get("limited_to_seconds") or facts.get("duration_seconds") or samples[-1]["t"]+interval
    # Strong cues are grouped over 6 seconds; a countdown lasts several frames
    # and should yield one candidate. Marker resets corroborate starts omitted
    # by an edited source, and never use species changes alone as a new battle.
    cues=[]
    digit_groups=[]
    for i,row in enumerate(samples):
        if not row.get("countdown"):
            continue
        cue={"t":row["t"],"kind":"countdown", "sample_index":i,"detail":row["countdown"]}
        if digit_groups and cue["t"]-digit_groups[-1][-1]["t"] <= 2.5:
            digit_groups[-1].append(cue)
        else:
            digit_groups.append([cue])
    # White attack streaks occasionally resemble "1". A countdown requires
    # a short descending sequence of distinct numerals, never a lone glyph.
    for group in digit_groups:
        for i,first in enumerate(group):
            if first["detail"]["digit"] < 2:
                continue
            sequence=[cue for cue in group[i:] if cue["t"]-first["t"] <= 3]
            digits=[cue["detail"]["digit"] for cue in sequence]
            if len(set(digits))>=2 and digits == sorted(digits,reverse=True):
                cues.extend(sequence)
                break
    previous_hud=None
    seen_hud=False
    min_party=6; min_shields=4
    low_party_streak=0; low_shield_streak=0
    for i,row in enumerate(samples):
        if row["hud"]:
            party=sum(row["party"]) if row.get("party") else None
            shields=row.get("shields_total")
            if not seen_hud:
                cues.append({"t":row["t"],"kind":"first_visible_hud","sample_index":i})
                seen_hud=True
            elif party == 6 and shields == 4 and (min_party <= 4 or min_shields <= 2):
                # Confirm a full reset on the next header frame too.
                next_rows=samples[i+1:i+4]
                confirmed=any(r["hud"] and r.get("party") == [3,3] and r.get("shields_total") == 4 for r in next_rows)
                if confirmed:
                    cues.append({"t":row["t"],"kind":"party_and_shields_reset","sample_index":i,
                                 "previous_min_party":min_party,"previous_min_shields":min_shields})
                    min_party=6;min_shields=4
            low_party_streak=low_party_streak+1 if party is not None and party < min_party else 0
            low_shield_streak=low_shield_streak+1 if shields is not None and shields < min_shields else 0
            if low_party_streak >= 2:
                min_party=party
            if low_shield_streak >= 2:
                min_shields=shields
            previous_hud=row
    clusters=[]
    for cue in sorted(cues,key=lambda c:c["t"]):
        if clusters and cue["t"]-clusters[-1][-1]["t"] <= 6:
            clusters[-1].append(cue)
        else:
            clusters.append([cue])
    starts=[]
    for cluster in clusters:
        earliest=cluster[0]["t"]
        # Match the first action HUD after the cue. A large central numeral on
        # its own is left as an unaccepted cue if no subsequent header appears.
        active=next((r for r in samples if earliest <= r["t"] <= cluster[-1]["t"]+6 and r["hud"]),None)
        if active is None:
            continue
        # Include the most recent VS/Battle starting screen, otherwise a brief
        # entrance gap. Prefix is bounded so a long lobby cannot enter the clip.
        active_index=next(i for i,r in enumerate(samples) if r is active)
        before=samples[max(0,active_index-round(14/interval)):active_index]
        vs=[r for r in before if r.get("battle_starting")]
        last_prior_hud=next((r for r in reversed(before) if r["hud"]),None)
        if vs:
            start=vs[0]["t"]
            boundary="battle_starting_context"
        elif last_prior_hud is not None and active["t"]-last_prior_hud["t"] <= 4:
            start=last_prior_hud["t"]+interval
            boundary="entry_gap_or_edit"
        else:
            supporting_digit=next((r for r in reversed(before) if r.get("countdown",{} ) and
                                   r["countdown"]["digit"]==3 and 0 <= earliest-r["t"] <= 4),None)
            start=max(0,supporting_digit["t"]-2.5 if supporting_digit else earliest-1.5)
            boundary="countdown_context" if any(c["kind"]=="countdown" for c in cluster) else "first_hud_context"
        starts.append({"start":round(start,6),"first_hud_seconds":active["t"],"cues":cluster,
                       "start_method":boundary,"sampling_resolution_seconds":interval,
                       "start_uncertainty_seconds":max(interval,1.5 if vs else active["t"]-start),
                       "confidence":"high" if any(c["kind"]=="countdown" for c in cluster) else "medium"})
    output=[]
    for n,start in enumerate(starts):
        ceiling=starts[n+1]["start"] if n+1<len(starts) else duration
        interval_samples=[r for r in samples if start["first_hud_seconds"] <= r["t"] < ceiling]
        active=[r for r in interval_samples if r["hud"]]
        results=[r for r in interval_samples if r.get("result")]
        if results:
            end=min(ceiling,results[-1]["t"]+interval)
            end_method="visible_result"
        elif active:
            last_active=active[-1]["t"]
            menus=[]
            for row in interval_samples:
                if row["t"] < last_active:
                    continue
                text=row.get("context_text","")
                key=re.sub(r"[^A-Z]","",text.upper())
                stardust_only=bool(re.fullmatch(r"\d{1,3},\d{3}(?:,\d{3})?",text.strip()))
                if stardust_only or any(cue in key for cue in ["CHOOSEYOURLEAGUE","FINDINGOPPONENT","BASICREWARDS","GOBATTLELEAGUE"]):
                    menus.append(row)
            if menus:
                end=min(ceiling,menus[0]["t"])
                end_method="first_post_battle_menu"
            elif n+1<len(starts):
                end=ceiling
                end_method="next_battle_entry_edit_or_gap"
            else:
                end=min(ceiling,last_active+5)
                end_method="last_hud_plus_unverified_resolution_context"
        else:
            continue
        if end-start["start"] < 15:
            continue
        output.append({"id":f"{source_id}-auto-{len(output)+1:02d}","source_id":source_id,
                       "name":f"Battle candidate {len(output)+1:02d}", **start,
                       "end":round(end,6),"end_method":end_method,
                       "end_uncertainty_seconds":max(interval,1.5 if end_method in {"visible_result","first_post_battle_menu"} else 5),
                       "review_required":True,"timing_validated":False,
                       "completeness":"result_visible" if results else "result_unseen_or_edited",
                       "notes":["Candidate discovered from video cues; exact action start and internal edits require review."]})
    return output


def evaluate_segments(predicted, reviewed, source_id):
    expected=[r for r in reviewed if r["source_id"]==source_id]
    candidates=[r for r in predicted if r["source_id"]==source_id]
    unused=set(range(len(candidates)));matches=[];missed=[]
    for truth in expected:
        overlaps=[]
        for i in unused:
            cand=candidates[i]
            overlap=max(0,min(truth["end"],cand["end"])-max(truth["start"],cand["start"]))
            union=max(truth["end"],cand["end"])-min(truth["start"],cand["start"])
            overlaps.append((overlap/union if union else 0,i,overlap))
        score,i,overlap=max(overlaps,default=(0,None,0))
        if score < .5:
            missed.append(truth["id"]);continue
        unused.remove(i);cand=candidates[i]
        matches.append({"reviewed_id":truth["id"],"candidate_id":cand["id"],
                        "intersection_over_union":round(score,5),
                        "start_error_seconds":round(cand["start"]-truth["start"],6),
                        "end_error_seconds":round(cand["end"]-truth["end"],6),
                        "reviewed_interval_coverage":round(overlap/(truth["end"]-truth["start"]),5)})
    return {"source_id":source_id,"reviewed_battles":len(expected),"proposed_battles":len(candidates),
            "matched":len(matches),"missed":missed,"unmatched_candidates":[candidates[i]["id"] for i in sorted(unused)],
            "matches":matches,"ground_truth_limit":"Reviewed context boundaries are approximate, and these sources were previously exposed; this is regression evaluation."}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video",type=Path)
    parser.add_argument("--profile",type=Path)
    parser.add_argument("--source-id",required=True)
    parser.add_argument("--interval",type=float,default=.5)
    parser.add_argument("--limit",type=float)
    parser.add_argument("--samples",type=Path,required=True,help="Compressed cache; reused unless --rescan")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--rescan",action="store_true")
    parser.add_argument("--reviewed",type=Path,help="Evaluate after discovery; never read by the detector")
    args=parser.parse_args()
    if args.samples.exists() and not args.rescan:
        with gzip.open(args.samples,"rt",encoding="utf-8") as stream:
            facts=json.load(stream)
        if facts.get("detector") != VERSION:
            raise ValueError("Sample cache detector version differs; use --rescan")
        if args.video and file_sha256(args.video) != facts["source_sha256"]:
            raise ValueError("Sample cache belongs to different video bytes; use a different cache or --rescan")
        if args.profile and json.loads(args.profile.read_text(encoding="utf-8")) != facts["profile"]:
            raise ValueError("Sample cache belongs to a different layout profile; use --rescan")
    else:
        if not args.video or not args.profile:
            parser.error("A fresh scan needs --video and --profile")
        profile=json.loads(args.profile.read_text(encoding="utf-8"))
        facts=scan_video(args.video,profile,interval=args.interval,limit=args.limit,output=args.samples)
    result={"schema":"battle-boundary-candidates-v1","detector":VERSION,"source_id":args.source_id,
            "source_video":facts["video"],"source_sha256":facts["source_sha256"],
            "detector_sha256":file_sha256(Path(__file__)),
            "sample_interval_seconds":facts["sample_interval_seconds"],
            "segments":propose_segments(facts,args.source_id),"review_required":True}
    if args.reviewed:
        reviewed=json.loads(args.reviewed.read_text(encoding="utf-8"))["segments"]
        result["evaluation"]=evaluate_segments(result["segments"],reviewed,args.source_id)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(args.output),"segments":len(result["segments"]),"evaluation":result.get("evaluation")}),flush=True)


if __name__ == "__main__":
    main()
