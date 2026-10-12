"""Use the other camera of the SAME match to recover an obscured move name.

Only existing charged events are enriched; no teammates, hits or shields are copied.
Every copied name records its peer clip and original source timestamp.
"""
import json
import shutil
from pathlib import Path

from vod_media import write_json


def reconcile(folder, game):
    meta = json.loads((folder / "battle.json").read_text(encoding="utf-8"))
    timeline = json.loads((game / "timeline.json").read_text(encoding="utf-8"))
    shutil.copyfile(game / "timeline.json", game / "assembly-original-timeline.json")
    if meta.get("view_id") not in ("left", "right"):
        return []
    peers = []
    for path in folder.parent.glob("tw-*/battle.json"):
        peer = json.loads(path.read_text(encoding="utf-8"))
        original = path.parent / "tracker/assembly-original-timeline.json"
        if path.parent != folder and peer.get("match_id") == meta.get("match_id") and peer.get("source_sha256") == meta.get("source_sha256") and original.exists():
            peers.append((path.parent, peer, json.loads(original.read_text(encoding="utf-8"))))
    changes = []
    looks = [json.loads(line) for line in (game / "observations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    for q in timeline["charged"]:
        if q["move"]:
            continue
        absolute = meta["source_start_seconds"] + timeline["clip_origin_seconds"] + q["t"]
        possible = []
        for peer_folder, peer, other in peers:
            for oq in other["charged"]:
                ot = peer["source_start_seconds"] + other["clip_origin_seconds"] + oq["t"]
                if oq["move"] and oq["side"] != q["side"] and abs(ot - absolute) <= 1.5:
                    possible.append((oq["move"], peer_folder.name, ot))
        if not possible or len({m for m, _, _ in possible}) != 1:
            continue
        move, peer_id, peer_time = possible[0]
        key = "my_charged" if q["side"] == "mine" else "foe_move"
        charged_key = "my_charged" if q["side"] == "mine" else "foe_charged"
        matches = [o for o in looks if o.get(charged_key) is not None and o.get(charged_key) is not False
                   and q["t"] + 5 <= o["t"] <= q["t"] + 14]
        if len(matches) != 1:
            continue
        q["move"] = move
        q["move_evidence"] = {"method": "same_match_other_perspective", "peer_id": peer_id,
                              "peer_source_seconds": peer_time, "source_seconds": absolute,
                              "accuracy_verified": False}
        matches[0][key] = move
        changes.append(q["move_evidence"] | {"move": move})
    if changes:
        write_json(game / "timeline.json", timeline)
        (game / "observations.jsonl").write_text("".join(json.dumps(o, separators=(",", ":")) + "\n" for o in looks), encoding="utf-8")
    write_json(game / "paired-evidence.json", {"match_id": meta.get("match_id"), "changes": changes,
                                              "split_unit": "original_source_video"})
    return changes
