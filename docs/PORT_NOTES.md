# PvPoke single-matchup AI port

Implemented in `pogo/pvpoke_ai.py`, using only the Python standard library and
existing simulator modules. This is the default single-matchup `simulate`
policy, not `TrainingAI.js`, team selection, or switching. PvPoke credit and the
MIT permission/warranty notice are included at the top of the module.

## Source

PvPoke commit **c15fb6f7e8613169740d904d6f96baa1824de480**, supplied locally in
`/tmp/pvpoke-src/` (also recorded in that directory's `COMMIT` file):

- `battle/actions/ActionLogic.js`
- `battle/Battle.js`
- `pokemon/Pokemon.js`
- `battle/DamageCalculator.js`

All four files were read. No network access was used. The Python implementation
has no runtime dependency on these files, JavaScript, or the extracted bundle.

## Function mapping

| PvPoke source | Python implementation |
| --- | --- |
| `ActionLogic.decideAction`, survival search, emergency moves, lethal moves, timing, long-matchup shortcut, baiting and final move selection | `PvpokeAI.decideAction` |
| `decideAction`'s dynamic-programming knockout search | `PvpokeAI._plan`, `_insert`, `_debuffs`, `BattleState` |
| `ActionLogic.wouldShield`'s default boolean decision | `PvpokeAI.wouldShield` |
| `Battle.getTurnAction`, simulate-mode action mapping | `PvpokeAI.act` (no charged action becomes `FAST`) |
| `Battle.useMove`'s default shield decision | `PvpokeAI.shield` (`sees_move = True`) |
| `Pokemon` defaults and move properties | `_Pokemon.__init__`, `_Move.__init__` |
| `Pokemon.initializeMove` and `Pokemon.resetMoves`' selected-move ordering, fastest move and best move | `_Pokemon.resetMoves` |
| `Pokemon.getBoostMove` | `_Pokemon.getBoostMove` |
| `Pokemon.applyStatBuffs` for hypothetical search/shield evaluation | Clamped changes to private Mon copies in `_damage` and `wouldShield` |
| `DamageCalculator.damage` | `_damage` delegates to existing `pogo.battle.damage` |

The defaults are selective baiting (`baitShields = 1`), `farmEnergy = False`,
and `optimizeMoveTiming = True`. CMP uses `build.cmp_atk`, without the shadow
bonus. Opponent cooldown is `view.foe_busy * 500`. Original charged-move slots
are retained separately from the AI's reordered active moves.

## Preserved behavior and adaptations

- The survival search retains the upstream depth-first queue behavior and CMP
  adjustments. The knockout search retains its 500-state cutoff, insertion
  order, different tie ordering for ready versus future moves, buff clamping,
  farm-down candidates, self-debuff stacking, and dominance/tie rules.
- Upstream's nonexistent `BattleState.hp`, `.shields`, and `.opponentShields`
  properties are not silently corrected: their comparisons do not prune the
  queue, and a farm-down state gets an absent shield value. The stale
  function-scoped `newEnergy` in the empty-queue insertion is also retained
  (initially represented by NaN).
- Upstream explicitly sets `changeTTKChance = 0`. Thus only the guaranteed
  path reaches a terminal state. Unreachable probabilistic plan branches,
  `needsBoost` alternatives, logging, unused calculations, and `turnsToKO`
  bookkeeping were omitted. The latter only affects selection between those
  disabled probabilistic plans, so no separate PvPoke turn counter is needed.
- Shielding normally starts at `True`; `wouldShield` is consulted for the
  specific buff/debuff exceptions in `Battle.useMove`. It is not a blanket
  replacement for that wrapper. PvPoke deducts charged-move energy before
  shielding, so `shield` adjusts the supplied pre-cost `foe_energy` first.
  `wouldShield`'s unusual hypothetical buff-recipient rule is preserved.
- DPE and active-move ordering are initialized for the matchup and remain
  separate from mutable cached damage. PvPoke refreshes cached damage when a
  move is used. This interface has no mandatory move-resolution callback
  (and the acceptance Recorder forwards only `act`, `shield`, and `replace`),
  so fast damage is reconstructed at decision boundaries and our chosen
  charged move's damage is cached when selected. Explicit damage updates in
  the AI/shield logic are retained. This is a boundary adaptation, not an
  exact reproduction of every upstream cache write: unusual simultaneous
  charged moves that change stats before the second resolves, or snapshots
  taken immediately after a buff before another fast move lands, remain
  unverified beyond the reference coverage. Each player has private metadata.
- Form-changing Pokémon are unsupported by the existing engine, so the
  Mimikyu, Aegislash, and Cramorant branches are omitted. Special move tags,
  alternative damage methods, and Mega mechanics not represented by `Move`
  or `Build` are likewise outside this adapter's coverage. The engine and
  data were not expanded.
- Move flags are derived from the existing `Move` buff fields. Randomized AI,
  randomized shield weights, and emulate/sandbox modes are outside scope.
  The existing engine uses random chance effects, whereas PvPoke's default
  simulation uses a deterministic application meter. The AI's guaranteed-buff
  search is ported; battles with chance effects are not claimed exact. None
  of the reference moves has a chance-based effect.
- `replace` returns the first available bench slot only to satisfy the player
  interface. It is not a port of team-play behavior.

## Acceptance and tests

Using `/Users/marco/Developer/pokemon_go/.venv/bin/python`:

```text
scripts/check_pvpoke_ai.py -v
108 of 108 battles identical to PvPoke; same winner in 108

scripts/check_pvpoke.py
108 of 108 PvPoke battles reproduced exactly

-m unittest discover tests
Ran 26 tests in 0.501s
OK
```

The acceptance criterion compares final health/energy and both ordered damage
traces. The checker explicitly permits harmless trailing fast inputs that do
not land. **No battle still differs under that criterion.** The supplied
revision therefore introduces no observed reference discrepancy; there is no
remaining mismatch to attribute to a different PvPoke revision. This does not
establish which revision the website used to generate the references.

The first implementation scored 105/108. Refreshing fast damage resolved
Vigoroth Shadow versus Snorlax (one shield) and Snorlax Shadow versus Tinkaton
(zero shields). Refreshing the selected charged move's cache resolved Furret
versus Tinkaton (two shields). These were adapter errors involving cached
post-buff damage, not evidence of a revision difference.

As an additional translation check, a temporary offline JavaScriptCore harness
ran the supplied `ActionLogic.decideAction` against the same adapted snapshots
for all 1,013 energy-ready decisions encountered in the 108 battles: **zero
choice differences**. That harness used the engine's damage inputs; it was a
control-flow comparison, not an independent full PvPoke battle simulation.

`tests/test_pvpoke_ai.py` adds the acceptance regression and verifies that
planning and shielding leave live battle health, energy, shields, and stat
stages unchanged. All 24 pre-existing tests still pass. No engine, acceptance
script, game-data, or phone files were changed. No playing-strength improvement
was measured, and team AI remains a later stage.
