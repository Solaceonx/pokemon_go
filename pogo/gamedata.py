"""Pokémon, moves and stats from PvPoke's game data, and the damage formula.

The data files live in data/ and come from github.com/pvpoke/pvpoke (MIT licence).
"""
from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

STAB = 1.2000000476837158
PVP_BONUS = 1.2999999523162842
SUPER, RESISTED, DOUBLE_RESISTED = 1.6000000238418579, 0.625, 0.390625
SHADOW_ATK, SHADOW_DEF = 1.2, 0.83333331
MAX_STAGE = 4

# attacking type: (super effective against, resisted by, no effect in the main games)
_CHART = {
    "normal": ((), ("rock", "steel"), ("ghost",)),
    "fire": (("grass", "ice", "bug", "steel"), ("fire", "water", "rock", "dragon"), ()),
    "water": (("fire", "ground", "rock"), ("water", "grass", "dragon"), ()),
    "electric": (("water", "flying"), ("electric", "grass", "dragon"), ("ground",)),
    "grass": (("water", "ground", "rock"), ("fire", "grass", "poison", "flying", "bug", "dragon", "steel"), ()),
    "ice": (("grass", "ground", "flying", "dragon"), ("fire", "water", "ice", "steel"), ()),
    "fighting": (("normal", "ice", "rock", "dark", "steel"), ("poison", "flying", "psychic", "bug", "fairy"), ("ghost",)),
    "poison": (("grass", "fairy"), ("poison", "ground", "rock", "ghost"), ("steel",)),
    "ground": (("fire", "electric", "poison", "rock", "steel"), ("grass", "bug"), ("flying",)),
    "flying": (("grass", "fighting", "bug"), ("electric", "rock", "steel"), ()),
    "psychic": (("fighting", "poison"), ("psychic", "steel"), ("dark",)),
    "bug": (("grass", "psychic", "dark"), ("fire", "fighting", "poison", "flying", "ghost", "steel", "fairy"), ()),
    "rock": (("fire", "ice", "flying", "bug"), ("fighting", "ground", "steel"), ()),
    "ghost": (("psychic", "ghost"), ("dark",), ("normal",)),
    "dragon": (("dragon",), ("steel",), ("fairy",)),
    "dark": (("psychic", "ghost"), ("fighting", "dark", "fairy"), ()),
    "steel": (("ice", "rock", "fairy"), ("fire", "water", "electric", "steel"), ()),
    "fairy": (("fighting", "dragon", "dark"), ("fire", "poison", "steel"), ()),
}


def effectiveness(move_type: str, target_types: tuple[str, ...]) -> float:
    strong, weak, none = _CHART[move_type]
    mult = 1.0
    for t in target_types:
        if t in strong:
            mult *= SUPER
        elif t in weak:
            mult *= RESISTED
        elif t in none:
            mult *= DOUBLE_RESISTED
    return mult


def stage_multiplier(stage: int) -> float:
    """Stat multiplier for a buff stage between -4 and +4."""
    return (4 + stage) / 4 if stage >= 0 else 4 / (4 - stage)


STAGE = [stage_multiplier(s) for s in range(-MAX_STAGE, MAX_STAGE + 1)]  # index with stage + MAX_STAGE


@dataclass(frozen=True)
class Move:
    id: str
    name: str
    type: str
    power: float
    energy: int  # cost of a charged move
    energy_gain: int  # energy from a fast move
    turns: int  # length of a fast move in half-second turns
    buff_chance: float = 0.0
    self_buffs: tuple[int, int] = (0, 0)  # (attack, defence) stage changes on the user
    foe_buffs: tuple[int, int] = (0, 0)
    percent_hp: bool = False  # damage is a share of the target's maximum health (Gulp Missile)
    instant: bool = False  # does not trigger the target's form effects (Gulp Missile)


def _move(m: dict) -> Move:
    self_buffs = foe_buffs = (0, 0)
    target = m.get("buffTarget")
    if target == "self":
        self_buffs = tuple(m["buffs"])
    elif target == "opponent":
        foe_buffs = tuple(m["buffs"])
    elif target == "both":
        self_buffs, foe_buffs = tuple(m["buffsSelf"]), tuple(m["buffsOpponent"])
    return Move(
        id=m["moveId"], name=m["name"], type=m["type"], power=m["power"],
        energy=m["energy"], energy_gain=m["energyGain"], turns=m.get("turns") or m["cooldown"] // 500,
        buff_chance=float(m["buffApplyChance"]) if target else 0.0,
        self_buffs=self_buffs, foe_buffs=foe_buffs,
        percent_hp=m.get("damageMethod") == "percentMaxHP", instant="instant" in (m.get("tags") or []),
    )


_uid = itertools.count()


@dataclass(eq=False)
class Build:
    """One Pokémon as brought to battle: species, level, IVs and moves, with its stats worked out."""

    species_id: str
    name: str
    types: tuple[str, ...]
    level: float
    ivs: tuple[int, int, int]
    cp: int
    atk: float  # includes the shadow bonus
    defense: float  # includes the shadow penalty
    hp: int
    cmp_atk: float  # attack used to break charged-move ties; the shadow bonus does not count
    fast: Move
    charged: tuple[Move, ...]
    uid: int = field(default_factory=lambda: next(_uid))
    _cache: dict = field(default_factory=dict, repr=False)
    # Form-changing Pokémon (Aegislash, Mimikyu, Cramorant, Morpeko; pogo.battle applies the changes): every form of
    # one Pokémon is a Build, all sharing `forms` ({form id: Build}) and the starting form's id `home`. `rule` is the
    # form's formChange entry from the game master, `native` its own stat stages (Busted Mimikyu: Defence -1), and
    # `gulp` the Gulp Missile a Gulping or Gorging Cramorant fires when a charged move hits it.
    forms: dict | None = field(default=None, repr=False)
    home: str | None = None
    rule: dict | None = field(default=None, repr=False)
    native: tuple[int, int] = (0, 0)
    gulp: Move | None = None

    def base_damage(self, move: Move, target: Build) -> float:
        """Damage before stat stages and rounding."""
        key = (move.id, target.uid)
        value = self._cache.get(key)
        if value is None:
            stab = STAB if move.type in self.types else 1.0
            value = 0.5 * move.power * stab * effectiveness(move.type, target.types) * PVP_BONUS * self.atk / target.defense
            self._cache[key] = value
        return value


def spread(weights: dict, total: float) -> dict:
    """Share `total` out in proportion to the weights, with no share above 1 (a move is in a moveset once)."""
    out, free, left = {k: 0.0 for k in weights}, {k: v for k, v in weights.items() if v > 0}, total
    while free and left > 1e-9:
        whole = sum(free.values())
        full = [k for k, v in free.items() if left * v / whole >= 1.0]
        if not full:
            out.update({k: left * v / whole for k, v in free.items()})
            break
        for k in full:
            out[k], left = 1.0, left - 1.0
            del free[k]
    return out


class GameData:
    def __init__(self, folder: Path = DATA):
        gm = json.loads((folder / "gamemaster.json").read_text())
        self.species = {p["speciesId"]: p for p in gm["pokemon"]}
        self.moves = {m["moveId"]: _move(m) for m in gm["moves"] if "damageMethod" not in m}
        self.special_moves = {m["moveId"]: _move(m) for m in gm["moves"] if "damageMethod" in m}  # Gulp Missile
        self._cpm = json.loads((folder / "cpm.json").read_text())["cpm"]
        self._folder = folder
        self._rankings: dict[int, list] = {}
        self._defaults: dict = {}
        self._odds: dict = {}

    def move_odds(self, species_id: str, league: int = 1500) -> dict:
        """What an opponent's Pokémon of this species is likely to have, before anything is seen.

        {"fast": {move id: chance it is their fast move},
         "charged": {move id: chance it is one of their two charged moves}}

        The weights are how often PvPoke's simulations prefer each move, a stand-in until we have counts from
        real battles. A species PvPoke gives no numbers for gets its recommended moves at three times the rest."""
        key = (species_id, league)
        if key not in self._odds:
            entry = next((e for e in self.rankings(league) if e["speciesId"] == species_id), None)
            uses = {x["moveId"]: float(x.get("uses") or 0) for g in ("fastMoves", "chargedMoves")
                    for x in (entry["moves"][g] if entry else [])}
            usual = set(entry["moveset"]) if entry else set()
            out = {}
            for kind, slots in (("fast", 1.0), ("charged", 2.0)):
                ids = [m for m in self.species[species_id][kind + "Moves"] if m in self.moves]
                weights = {m: uses.get(m, 0.0) for m in ids}
                if sum(weights.values()) <= 0:
                    weights = {m: 3.0 if m in usual else 1.0 for m in ids}
                out[kind] = spread(weights, min(slots, len(ids)))
            self._odds[key] = out
        return self._odds[key]

    def cpm(self, level: float) -> float:
        return self._cpm[round((level - 1) * 2)]

    def rankings(self, league: int = 1500) -> list[dict]:
        if league not in self._rankings:
            self._rankings[league] = json.loads((self._folder / f"rankings-{league}.json").read_text())
        return self._rankings[league]

    def supported(self, species_id: str) -> bool:
        """Form-changing Pokémon (Aegislash, Mimikyu, Cramorant, Morpeko) are played by the engine when built with
        allow_forms (reproduced against PvPoke: tests/data/pvpoke_forms.txt), but are kept out of the pools that
        simulations draw from (meta()), which every trained model and measurement so far has used."""
        return "formChange" not in self.species[species_id]

    def build(self, species_id: str, moveset: list[str], league: int = 1500,
              level: float | None = None, ivs: tuple[int, int, int] | None = None, allow_forms: bool = True) -> Build:
        """A Pokémon with the given [fast, charged, charged] moves, at PvPoke's default level and IVs for the league.

        allow_forms builds a form-changing Pokémon with all its forms, which the battle changes between as PvPoke's
        simulator does.
        """
        p = self.species[species_id]
        if not allow_forms and not self.supported(species_id):
            raise ValueError(f"{species_id} changes form in battle; build it with allow_forms=True")
        if level is None or ivs is None:
            level, *ivs = p["defaultIVs"][f"cp{league}"]
        home = self._plain(species_id, moveset, level, ivs)
        family = self._family(species_id)
        if len(family) > 1:
            self._attach_forms(home, family, moveset, league)
        return home

    # form-changing Pokémon

    def _family(self, species_id: str) -> list[str]:
        """Every form a Pokémon can take in battle, starting from this one."""
        out, todo = [], [species_id]
        while todo:
            sid = todo.pop(0)
            if sid in out or sid not in self.species:
                continue
            out.append(sid)
            rule = self.species[sid].get("formChange") or {}
            for key in ("alternativeFormId", "defaultFormId"):
                alt = rule.get(key)
                if alt == "variable":  # Cramorant: Gulping or Gorging, by health
                    todo += [f"{species_id}_gulping", f"{species_id}_gorging"]
                elif alt:
                    todo.append(alt)
        return out

    def _attach_forms(self, home: Build, family: list[str], moveset: list[str], league: int) -> None:
        """Builds for the other forms, as PvPoke's Pokemon.changeForm and getFormStats make them."""
        swap = {"AEGISLASH_CHARGE_PSYCHO_CUT": "PSYCHO_CUT", "AEGISLASH_CHARGE_AIR_SLASH": "AIR_SLASH",
                "AURA_WHEEL_ELECTRIC": "AURA_WHEEL_DARK"}
        swap.update({v: k for k, v in list(swap.items())})
        forms = {home.species_id: home}
        home_rule = self.species[home.species_id].get("formChange")
        for sid in family:
            if sid == home.species_id:
                continue
            p = self.species[sid]
            allowed = set(p.get("fastMoves", [])) | set(p.get("chargedMoves", []))
            moves = [m if m in allowed else swap.get(m, m) for m in moveset]
            level = home.level
            if {home.species_id, sid} == {"aegislash_shield", "aegislash_blade"} and league in (1500, 2500):
                if sid == "aegislash_blade":
                    level = math.ceil(home.level * 0.5) + 1 if league == 1500 else math.ceil(home.level * 0.75)
                else:
                    level = home.level / 0.5 + 2 if league == 1500 else round(home.level / 0.75)
                while level > 1 and self.cp_at(sid, level, home.ivs) > league:
                    level -= 1
            form = self._plain(sid, moves, level, home.ivs)
            form.hp = home.hp  # PvPoke keeps the health of the starting form
            forms[sid] = form
        for sid, form in forms.items():
            p = self.species[sid]
            form.forms, form.home = forms, home.species_id
            form.rule = p.get("formChange") or home_rule  # a form without its own rule keeps the one it came from
            form.native = tuple(p.get("nativeStatBuffs") or (0, 0))
            if sid.endswith("_gulping"):
                form.gulp = self.special_moves.get("GULP_MISSILE_ARROKUDA")
            elif sid.endswith("_gorging"):
                form.gulp = self.special_moves.get("GULP_MISSILE_PIKACHU")

    def _plain(self, species_id: str, moveset: list[str], level: float, ivs) -> Build:
        p = self.species[species_id]
        a, d, s = ivs
        base = p["baseStats"]
        c = self.cpm(level)
        shadow = "shadow" in p.get("tags", [])
        raw_atk = (base["atk"] + a) * c
        raw_def = (base["def"] + d) * c
        cp = max(10, int((base["atk"] + a) * math.sqrt(base["def"] + d) * math.sqrt(base["hp"] + s) * c * c / 10))
        return Build(
            species_id=species_id, name=p["speciesName"],
            types=tuple(t for t in p["types"] if t != "none"),
            level=level, ivs=(a, d, s), cp=cp,
            atk=raw_atk * (SHADOW_ATK if shadow else 1.0),
            defense=raw_def * (SHADOW_DEF if shadow else 1.0),
            hp=max(int((base["hp"] + s) * c), 10),
            cmp_atk=raw_atk,
            fast=self.moves[moveset[0]],
            charged=tuple(self.moves[m] for m in moveset[1:]),
        )

    def default(self, species_id: str, league: int = 1500, allow_forms: bool = True) -> Build:
        """A Pokémon with PvPoke's recommended moveset and default level and IVs."""
        key = (species_id, league, allow_forms)
        if key not in self._defaults:
            entry = next((e for e in self.rankings(league) if e["speciesId"] == species_id), None)
            if entry is None:
                raise KeyError(f"{species_id} is not in the {league} rankings")
            moves = [m for m in entry["moveset"] if m in self.moves]  # a form's special move may not be in the list
            self._defaults[key] = self.build(species_id, moves, league, allow_forms=allow_forms)
        return self._defaults[key]

    def cp_at(self, species_id: str, level: float, ivs: tuple[int, int, int]) -> int:
        base = self.species[species_id]["baseStats"]
        a, d, s = ivs
        c = self.cpm(level)
        return max(10, int((base["atk"] + a) * math.sqrt(base["def"] + d) * math.sqrt(base["hp"] + s) * c * c / 10))

    def level_for(self, species_id: str, ivs: tuple[int, int, int], league: int = 1500, max_level: float = 50.0) -> float | None:
        """The highest level, in half steps, at which these IVs stay within the league's CP cap."""
        best = None
        for i in range(int((max_level - 1) * 2) + 1):
            level = 1 + i / 2
            if self.cp_at(species_id, level, ivs) > league:
                break
            best = level
        return best

    def spreads(self, species_id: str, league: int = 1500, max_level: float = 50.0) -> list[dict]:
        """Every IV combination at its best level for the league, best stat product first.

        Stat product (attack x defence x HP) is the usual measure of a spread; rank 1 is the highest.
        """
        base = self.species[species_id]["baseStats"]
        out = []
        for a in range(16):
            for d in range(16):
                for s in range(16):
                    level = self.level_for(species_id, (a, d, s), league, max_level)
                    if level is None:
                        continue
                    c = self.cpm(level)
                    atk, de, hp = (base["atk"] + a) * c, (base["def"] + d) * c, max(int((base["hp"] + s) * c), 10)
                    out.append({"ivs": (a, d, s), "level": level, "atk": atk, "def": de, "hp": hp,
                                "product": atk * de * hp, "cp": self.cp_at(species_id, level, (a, d, s))})
        out.sort(key=lambda e: -e["product"])
        for rank, entry in enumerate(out, start=1):
            entry["rank"] = rank
        return out

    def with_ivs(self, build: Build, ivs: tuple[int, int, int], league: int = 1500) -> Build:
        """The same Pokémon and moves with different IVs, at the best level those IVs allow."""
        level = self.level_for(build.species_id, ivs, league)
        return self.build(build.species_id, [build.fast.id, *(m.id for m in build.charged)], league, level=level, ivs=ivs)

    def meta(self, n: int = 50, league: int = 1500, forms: bool = False) -> list[Build]:
        """The n highest-ranked Pokémon in the league, each with its recommended moveset. Form-changing Pokémon are
        left out unless forms=True: every model and measurement so far used pools without them."""
        out = []
        for entry in self.rankings(league):
            if forms or self.supported(entry["speciesId"]):
                out.append(self.build(entry["speciesId"], entry["moveset"], league))
                if len(out) == n:
                    break
        return out
