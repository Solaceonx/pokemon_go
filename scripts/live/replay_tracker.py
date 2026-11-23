"""(Scratch tool, 2026-11-23.) Replay the tracker on the observations a live battle logged (runs/live/*.jsonl), no frames needed, and score its
count of their energy at each of their named charged moves. Run from the worktree:
    python scripts/live/replay_tracker.py 20261122 [--countdown-fix] [--seen-lag N] [--restart-lag N] [--no-resync] [--quiet]
Prints, per variant: throws scored, short (top of the range below the cost), short by more than one fast move, and how
far the replayed count is from the logged one (to check the replay is faithful)."""
import argparse, glob, importlib.util, json, sys, types
from pathlib import Path
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts/live')
_stub = importlib.util.find_spec("cv2") is None
if _stub:
    sys.modules["cv2"] = types.ModuleType("cv2")
import play_android as pa  # noqa: E402
if _stub:
    del sys.modules["cv2"]
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('day')
ap.add_argument('--countdown-fix', action='store_true')
ap.add_argument('--quiet', action='store_true')
ap.add_argument('--seen-lag', type=int, default=0)
ap.add_argument('--restart-lag', type=int, default=0)
ap.add_argument('--no-resync', action='store_true')
ap.add_argument('--margin', type=int, default=0, help='fast moves added to the top of the count, as FOE_MARGIN')
ap.add_argument('--at-throw', type=float, default=None, help='score their_energy_at_throw, with the time since the last look less this many seconds as fight')
a = ap.parse_args()
gd = GameData(league=2500)
Tracker.SEEN_LAG, Tracker.RESTART_LAG, Tracker.RESYNC = a.seen_lag, a.restart_lag, not a.no_resync
margins = []
TEAMS = {'melmetal': 'data/team_owner_ul.json', 'virizion': 'data/team_owner_ul_virizion.json'}
fields = set(Observation.__dataclass_fields__)
COUNTS = ('my_left', 'foe_left', 'my_shields', 'foe_shields')


def obs_of(raw):
    """A logged observation as the player gave it: the header's counts were numpy integers, logged as text."""
    o = {x: v for x, v in raw.items() if x in fields}
    for x in COUNTS:
        if isinstance(o.get(x), str):
            o[x] = int(o[x]) if o[x].isdigit() else None
    return o
scored = short = short1 = 0
drift = []
for f in sorted(glob.glob(f'runs/live/{a.day}-*.jsonl')):
    ev = [json.loads(l) for l in open(f)]
    team = next((e for e in ev if e['kind'] == 'team'), None)
    if team is None or not any(e['kind'] == 'look' for e in ev):
        continue
    names = [m[0] for m in team['team']]
    path = next((p for k, p in TEAMS.items() if k in names), None)
    if path is None:
        continue
    tr = Tracker(gd, pa.load_team(gd, Path(path)))
    shields, thrown_at, countdown_since = 2, -99.0, None
    pending_named = None
    prompt = None
    for e in ev:
        k = e['kind']
        if k == 'throw_started':
            thrown_at = e['t']
        elif k == 'their_charged_countdown':
            countdown_since = e['t']
        elif k == 'replace':
            tr.my_fainted()
        elif k == 'their_charged_named' and e.get('counted_already'):
            pending_named = e['move']
        elif k == 'shield_prompt':
            if a.at_throw is not None and tr.foe:
                # the name read before the prompt, handed over there as the player now does (Player.foe_now)
                nxt = next((x for x in ev if x['kind'] == 'look' and x['t'] > e['t']), None)
                if nxt and nxt.get('foe') and nxt['obs'].get('foe_out_for') and nxt['t'] - nxt['obs']['foe_out_for'] < e['t'] - 0.3 \
                        and nxt['foe'][0] != tr.foe.mon.build.species_id:
                    tr.their_active_seen(e['t'], nxt['obs']['foe_species'], e['t'] - (nxt['t'] - nxt['obs']['foe_out_for']))
            lo, hi = (tr.foe.lo, tr.foe.hi) if tr.foe else (None, None)
            if tr.foe and a.at_throw is not None:
                lo, hi = tr.their_energy_at_throw(max(0.0, e['t'] - tr.t - a.at_throw))
            if tr.foe and hi is not None:
                hi = min(100, hi + a.margin * tr.foe.mon.build.fast.energy_gain)
            prompt = (e['t'], tr.foe.mon.build.species_id if tr.foe else None, lo, hi,
                      tr.foe.mon.build.fast.energy_gain if tr.foe else None)
        elif k == 'their_charged_named' and prompt and e['t'] - prompt[0] < 8 and prompt[3] is not None:
            cost = gd.moves[e['move']].energy
            scored += 1
            short += prompt[3] < cost
            short1 += prompt[3] + prompt[4] < cost
            margins.append(prompt[3] - cost)
            if a.quiet is False and prompt[3] < cost:
                print('   short:', f[-21:-6], round(e['t'], 1), prompt[1], e['move'], cost, 'we', prompt[2], prompt[3])
            prompt = None
        elif k == 'look':
            o = obs_of(e['obs'])
            if 'my_shields' in o and str(o['my_shields']).isdigit():
                shields = int(o['my_shields'])
            if a.countdown_fix and countdown_since is not None and o.get('foe_charged') and not o.get('foe_move'):
                if shields > 0 or countdown_since - thrown_at < 18.0:
                    o['foe_charged'] = False  # what countdown_is_theirs now says
            countdown_since = None
            tr.update(Observation(**o))
            if pending_named:
                tr.their_move_named(e['t'], pending_named)
                pending_named = None
            if e.get('foe') and tr.foe is not None and e['foe'][0] == tr.foe.mon.build.species_id:
                drift.append(abs(tr.foe.hi - e['foe'][2]))
n = len(drift)
margins.sort()
tag = f"{'cd-fix ' if a.countdown_fix else ''}seen{a.seen_lag} restart{a.restart_lag}{' noresync' if a.no_resync else ''}"
print(f"{tag}: median top-cost {margins[len(margins)//2]}, upper quartile {margins[3*len(margins)//4]}; their throws scored {scored}, short {short} "
      f"({short/max(1,scored):.0%}), short by more than a fast move {short1}; replay vs logged count: "
      f"same at {sum(d == 0 for d in drift)/max(1,n):.0%} of {n} looks, mean gap {sum(drift)/max(1,n):.1f}")
