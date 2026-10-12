# Screen reader and battle viewer

The offline screen reader lives in [`screen_reader/`](../screen_reader/README.md).
It imports a single YouTube video or Twitch VOD, proposes battle boundaries,
extracts phone-view clips, saves time-aligned observations and opens a local viewer
with a playback-driven values table. It requires a matching calibrated layout.
Twitch intake is implemented but has not been checked against a specific VOD.

The reader distinguishes screen observations from inferred scene continuity and
tracker hypotheses. Hidden or ambiguous fields remain unknown. Health is a visible
fraction range; integer HP requires a verified maximum. Energy, switch-clock
measurement and complete charged-animation recognition are unfinished.

The local development library contains 18 battles and 56,704 decoded frames. The
split groups whole source recordings: nine Reis development clips and nine Henry
exposed regression clips. Both sources were inspected during development, so Henry
is not an untouched accuracy benchmark. Complete human-labelled battles and a new
untouched source are still needed. See `screen_reader/dataset/baseline-summary.json`
and the dataset guide for the historical checks and provenance limits.

Git contains source, profiles, selected phone-crop regression images, labels,
metadata and preserved reader inputs. Recordings, generated battle logs, downloaded
tools and the generated HTML stay local. The reader uses the existing shared
`data/gamemaster.json`; it does not change the simulator or decision logic.

Reviewed observations can be exported using `screen_reader/export_tracker.py` to
the contract in `docs/agent_instructions.md`. Battle action start, species forms
and charged events need explicit review before exporting. Automated raw readings
are not assumed to be valid tracker input.
