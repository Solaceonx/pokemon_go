# Data

`gamemaster.json` and `rankings-1500.json` are copied from PvPoke
(https://github.com/pvpoke/pvpoke). `cpm.json` is the level multiplier table taken from its
source. `tests/data/pvpoke_duels.txt` records battles played by PvPoke's simulator.
PvPoke is MIT-licensed; its licence is in `PVPOKE_LICENSE`.

`teams.json` and `matchups.json` are produced by `scripts/teams.py`.

`teams_v2.json` is the separate mixture produced by
`scripts/self_consistent_teams.py`. Its explicit `weight` fields define how often
teams are drawn; `seen` retains real sighting counts. `teams_v2.report.json` holds
the untouched counter audit, and `roster_teams_v2.json` compares the owner's
line-ups against the old and new lists on paired battles. See
[`docs/team_mixture.md`](../docs/team_mixture.md) for methods, limits and rerun commands.
The 2026-10-12 reduced run failed the under-55% counter check; this is an
experimental list, not a validated replacement for the original field.
