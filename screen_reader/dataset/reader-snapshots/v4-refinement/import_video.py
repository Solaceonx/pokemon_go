"""Simple interactive launcher for the resumable video-to-battles pipeline."""
from pathlib import Path
from import_source import canonical_source
from button_reader import ROOT
import json


def refine_imported_battles(result, profile):
    from refine_saved_readings import refine
    return [refine(ROOT / "battles" / exported["id"], profile)
            for exported in result.get("exports", [])]


def main():
    print("Import a battle video. Existing originals and valid analysis are reused.")
    url = input("Paste a YouTube video or Twitch VOD link: ").strip()
    platform, identity, url = canonical_source(url)
    references = json.loads((ROOT / "reference_manifest.json").read_text(encoding="utf-8"))["references"]
    reference = next((r for r in references if r["id"] == identity), None)
    profile = ROOT / reference["profile"] if reference else None
    if profile is None:
        print("Choose the matching recording layout. Unfamiliar layouts need calibration.")
        print("1: Reis iPhone layout   2: Henry Android layout")
        choice = input("Enter 1, 2, or the path to a calibrated layout file: ").strip()
        profile = {"1": ROOT / "profiles/reis-great.json", "2": ROOT / "profiles/henry-great.json"}.get(choice, Path(choice))
        if not profile.is_file():
            raise ValueError("The selected layout file does not exist")
    from run_video_pipeline import run_pipeline
    result = run_pipeline(url, profile=profile, download=True, stage="track")
    refine_imported_battles(result, profile)
    from build_lazy_viewer import build
    build()
    print(f"Finished. Found {result['candidate_count']} battle candidates; unreadable values remain unknown.")
    from launch_viewer import main as open_viewer
    open_viewer()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        print("Import could not finish:", error)
        raise SystemExit(1)
