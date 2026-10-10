"""Create reference-only battle profiles from manually selected creator frames."""
import json
from button_reader import ROOT, Image, np
from local_ocr import LocalOCR, compact


REFERENCES = [
    {"id": "reis-great", "video": "qSaL7jM9NbA", "viewport": [712, 0, 496, 1080], "marker_y": 133,
     "name_y": [96, 123], "charge_samples": [65, 115, 155],
     "phases": [(35, "shield_prompt", "ATTACKINCOMINGUSEAPROTECTSHIELD"),
                (55, "choose_next", "SWITCHINANEWPOKEMON"), (45, "my_charged_minigame", "GETREADY"),
                (85, "my_charged_minigame", "NICE"), (160, "my_charged_minigame", "GREAT")],
     "team_moves": {"Raichu": ["Volt Tackle", "Trailblaze"], "Thievul": ["Icy Wind", "Night Slash"], "Corsola": ["Power Gem", "Night Shade"]},
     "moves": ["Volt Tackle", "Trailblaze", "Icy Wind", "Night Slash", "Power Gem", "Night Shade"]},
    {"id": "henry-great", "video": "8O7kDtNZs6Y", "viewport": [706, 0, 508, 1080], "marker_y": 104,
     "name_y": [70, 98], "charge_samples": [80, 130, 170],
     "phases": [(75, "shield_prompt", "ATTACKINCOMINGUSEAPROTECTSHIELD"),
                (90, "opponent_charged_warning", "ATTACKINCOMING"),
                (65, "my_charged_minigame", "GETREADY"), (100, "my_charged_minigame", "NICE"),
                (140, "my_charged_minigame", "GREAT"), (145, "opponent_charged_resolution", "NOPROTECTSHIELDSREMAINING")],
     "team_moves": {"Hydreigon": ["Brutal Swing", "Fly"], "Araquanid": ["Mirror Coat", "Water Pulse"], "Lanturn": ["Surf", "Thunderbolt"]},
     "moves": ["Brutal Swing", "Fly", "Mirror Coat", "Water Pulse", "Surf", "Thunderbolt"]},
]


def main():
    ocr = LocalOCR()
    for reference in REFERENCES:
        directory = ROOT / "profiles" / reference["id"]
        directory.mkdir(exist_ok=True)
        templates = []
        selected = sorted(set(reference["charge_samples"] + [entry[0] for entry in reference["phases"]]))
        for second in selected:
            image = Image.open(ROOT / "samples" / reference["video"] / f"{second}.png")
            x, y, w, h = reference["viewport"]
            phone = image.crop((x, y, x+w, y+h)).resize((508, 1080))
            records = ocr.read(np.asarray(phone))
            for record in records:
                key = compact(record["text"])
                selection = None
                for t, phase, cue in reference["phases"]:
                    if second == t and key == cue:
                        selection = {"kind": "phase", "phase": phase, "cue": record["text"]}
                if second in reference["charge_samples"] and record["bounds"][1] > 880:
                    for move in reference["moves"]:
                        if key == compact(move):
                            selection = {"kind": "charge", "move": move,
                                         "slot": 0 if sum(record["bounds"][::2])/2 < 254 else 1}
                if selection is None:
                    continue
                x0, y0, x1, y1 = record["bounds"]
                region = [max(0, x0-2), max(0, y0-2), min(508, x1+3), min(1080, y1+3)]
                filename = f"{selection['kind']}-{second}-{len(templates)}.png"
                phone.crop(region).save(directory / filename)
                templates.append({**selection, "file": f"{reference['id']}/{filename}", "bounds": region,
                                  "search": [max(0, x0-30), max(0, y0-55), min(508, x1+30), min(1080, y1+55)],
                                  "calibration_seconds": second})
        profile = {"id": reference["id"]+"-v2", "video_id": reference["video"],
                   "viewport": reference["viewport"], "width": 508, "height": 1080,
                   "marker_y": reference["marker_y"], "name_y": reference["name_y"],
                   "charge_centers": [[156, 964], [351, 964]], "hp_width": 144,
                   "health_regions": {"mine": [5, 250, 225, 785], "opponent": [230, 240, 505, 610]},
                   "known_moves": reference["moves"],
                   "team_moves": reference["team_moves"],
                   "species_lexicon": ["Hydreigon", "Araquanid", "Lanturn", "Melmetal", "Stunfisk", "Thievul", "Raichu", "Corsola", "Charjabug", "Vigoroth", "Florges", "Electrode", "Mantine", "Ninetales"],
                   "templates": templates, "timing_validated": False}
        (ROOT / "profiles" / (reference["id"]+".json")).write_text(json.dumps(profile, indent=2), encoding="utf-8")
        print(json.dumps({"profile": profile["id"], "templates": len(templates)}), flush=True)


if __name__ == "__main__":
    main()
