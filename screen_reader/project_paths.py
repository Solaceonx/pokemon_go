"""Use the repository's shared game data, with standalone-bundle support."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def game_data_path():
    candidates = [ROOT.parent / "data/gamemaster.json", ROOT / "tracker_bundle/data/gamemaster.json"]
    return next((path for path in candidates if path.is_file()), candidates[0])
