# Request: publish the readings of the reserved two-screen sample

**Done (2026-10-11).** The readings are published and the frozen test was run: `docs/reserved_state_evaluation.md`. Kept as a record; the reserved clips stay reserved.

The ten reserved official battles (20 clips, sources `2897166800` and `2897312743`) are cut
but not read, and only their list and checksums are in the repository. They are the test
the tracker needs: its timing settings were fitted on the three earlier two-screen matches
and have not been checked on anything else.

The settings under test are frozen on `main` at the commit that adds this file. Please do
not change `scripts/recording/assemble.py`, `pogo/tracker.py` or `scripts/track.py` before
the readings are pushed, and do not tune anything on these clips.

## What to do on the PC that has the clips

1. Merge `main` into your branch.
2. Read the 20 clips exactly as the first 23 were read (`vod_track.py`, same 15 frames and
   3 text looks a second) and publish each as `games/twitch/<clip>/` with at least
   `raw/readings-refined.jsonl.gz`, `raw/text.jsonl.gz`, `raw/read.json` and `source.json`
   (with `match_id`, `view_id`, `incomplete_start`, `incomplete_end`). The tracked files may
   be published too; they are not needed for the test.
3. Push. Video stays out of the repository as before.

## The test, which anyone can then run without the videos

```bash
python3 scripts/recording/retrack_public.py out-fitted --told
python3 scripts/recording/retrack_public.py out-before --told --swapped-theirs -1.0 --enter 0.2 --start 0.7 --resume-lead 0.5 --waits faint --header-waits no
for d in out-before out-fitted; do
  python3 scripts/recording/paired_energy.py --all $d --source 2897166800 --source 2897312743 | tail -3
  python3 scripts/recording/paired_state.py  --all $d --source 2897166800 --source 2897312743
done
```

`out-before` is the timing as it was before the fit; `out-fitted` is today's. On the three
matches the fit was made on, the opponent's energy went from within two fast moves in 76% of
moments to 88%, and its average error from 12.8 to 9.4. The question is whether that holds
on the new ten. Report both sets of numbers as they come out, whichever way they point.
