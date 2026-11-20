# Mechanics used by the footage tracker

Checked 2026-11-20. Runtime uses the checked-in GameMaster and its recorded byte hash, not web requests. Research documented here does not establish that a particular effect happened in a particular frame.

## Switching and form-native stages

Ordinary move modifiers clear on switching. The remaining baseline can depend on the form: Busted Mimikyu has native stages `[0, -1]`, retains its form across switches, and must not be reset to `[0, 0]`. Repeated returns must not accumulate another native penalty.

This is explicit in [PvPoke's GameMaster](https://github.com/pvpoke/pvpoke/blob/master/src/data/gamemaster.json), under `mimikyu_busted.nativeStatBuffs` and `formChange.resetOnSwitch`, and in its [reset/form implementation](https://github.com/pvpoke/pvpoke/blob/master/src/js/pokemon/Pokemon.js), which reapplies native stages after resetting ordinary buffs. The local battle engine already follows this rule in `leave_field`; the screen ledger's earlier blanket neutral inference was too broad.

The tracker therefore resolves native stages from source-confirmed form evidence and the checked-in data. If possible forms disagree, the affected stage stays unknown. A future form confirmation cannot supply an earlier entry's form. First headers in clipped footage do not establish a switch.

## Stat-message wording

The extracted [client English resources](https://github.com/PokeMiners/pogo_assets/blob/master/Texts/Latest%20APK/English.txt) distinguish `combat_buff_lvl1/2/3` and `combat_debuff_lvl1/2/3`: ordinary rose/fell wording, sharply/harshly wording, and drastically/severely wording. The owner also confirmed that unmodified rose/fell is a single-stage message.

The reader records the message category and single/double-step interpretation; the largest category retains three/four-step ambiguity. This is separate from applying an actual new change. A banner can redisplay a form-native effect, and legacy samples lack spatial ownership. No message alone is blindly added to either Pokémon's stage, and repeat banners do not stack effects.

Current limits: transient notices can be missed at the legacy sampling rate; exact targets, intervening ordinary effects and continuous stage history are not certified. Source entry identity checks are not exact-stage accuracy checks.
