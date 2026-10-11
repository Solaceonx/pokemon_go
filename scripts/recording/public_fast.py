"""Fit player fast-move candidates to energy rises within uninterrupted fights.

This is offline inference, never a team sheet. Ambiguous candidates remain listed.
"""
import bisect
import json
import statistics


def score_candidates(windows, candidates):
    scores = {}
    for mid, gain, turns in candidates:
        rate = 2 * gain / turns
        # A missed boundary hit or gliding fill can shift a window by one move.
        scores[mid] = round(statistics.median(abs(delta - duration * rate) / max(duration, 1)
                                              for duration, delta in windows), 4)
    ranked = sorted(scores, key=lambda k: scores[k])
    selected = None
    if len(windows) >= 3 and ranked and scores[ranked[0]] < 2.0:
        margin = scores[ranked[1]] - scores[ranked[0]] if len(ranked) > 1 else 100
        if margin > .45:
            selected = ranked[0]
    return {"selected": selected, "scores_energy_per_second": scores,
            "windows": len(windows), "status": "inferred" if selected else "ambiguous",
            "accuracy_verified": False}


def prepare_team(game, gd):
    load = lambda name: json.loads((game / name).read_text(encoding="utf-8"))
    team, timeline = load("team.json"), load("timeline.json")
    looks = [json.loads(line) for line in (game / "observations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    field = timeline["field"]["mine"]
    by_name = {p["speciesName"]: sid for sid, p in gd.species.items()}
    reports = {}
    for pokemon in team["pokemon"]:
        name = pokemon["species"]
        sid = by_name.get(name)
        if sid is None:
            continue
        legal = [gd.moves[mid] for mid in gd.species[sid]["fastMoves"] if mid in gd.moves]
        windows = []
        for a, b in timeline["buttons_on"]:
            samples = [o for o in looks if a + .3 <= o["t"] <= b - .2
                       and o.get("my_species") == name and o.get("my_energy") is not None
                       and 3 <= o["my_energy"] <= 88]
            for i in range(0, len(samples) - 3, 3):
                first = samples[i]
                last = next((o for o in samples[i + 1:] if o["t"] - first["t"] >= 3), None)
                if last is None or last["t"] - first["t"] > 5:
                    continue
                # A switch out-and-back inside a window invalidates its rhythm.
                if any(first["t"] < f["t"] <= last["t"] for f in field):
                    continue
                duration, delta = last["t"] - first["t"], last["my_energy"] - first["my_energy"]
                if delta >= 4 and delta <= duration * 12 + 5:
                    windows.append((duration, delta))
        fit = score_candidates(windows, [(m.id, m.energy_gain, m.turns) for m in legal]) if windows else {
            "selected": None, "status": "insufficient_evidence", "windows": 0, "scores_energy_per_second": {}, "accuracy_verified": False}
        reports[name] = fit
        if fit["selected"]:
            # Charged moves still begin as model defaults and are learned when
            # thrown. False keeps the tracker from treating this as a team sheet.
            pokemon["model_fast"] = fit["selected"]
            pokemon["model_fast_source"] = "inferred_from_button_energy_rises"
    (game / "team.json").write_text(json.dumps(team, indent=2) + "\n", encoding="utf-8")
    (game / "player-fast-inference.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    return reports
