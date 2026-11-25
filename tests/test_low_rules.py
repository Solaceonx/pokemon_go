"""The live player's low-health rules (play_android): wait for a knock-out when a shield covers their throw
(better_soon), and keep a low Pokémon in when it wins its matchup (save_the_low_one). 2026-11-24, 213612: Clodsire
threw resisted Stone Edge into Kingambit with Earthquake's knock-out two fast moves away and a shield left; Thievul
was switched out of Palossand, a matchup it wins."""
import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
_stub = "cv2" not in sys.modules and importlib.util.find_spec("cv2") is None
if _stub:
    sys.modules["cv2"] = types.ModuleType("cv2")
try:
    import play_android as pa  # noqa: E402
finally:
    if _stub:
        del sys.modules["cv2"]
from pogo.battle import Mon  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

GD = GameData()
NS = types.SimpleNamespace


def player():
    p = object.__new__(pa.Player)
    p.logged = []
    p.log = lambda kind, t, **kw: p.logged.append(kind)
    return p


class WaitForTheKnockOut(unittest.TestCase):
    def setUp(self):
        self.cl = GD.build("clodsire", ["POISON_STING", "STONE_EDGE", "EARTHQUAKE"])
        kg = GD.build("kingambit", ["LOW_KICK", "FOUL_PLAY", "IRON_HEAD"])
        self.p = player()
        self.p.tracker = NS(foe=NS(mon=Mon(kg, hp=102), hi=43))

    def ask(self, shields):
        view = NS(me=NS(mon=Mon(self.cl, hp=56, energy=55), shields=shields))
        return self.p.better_soon(1.0, view, self.cl, 55, [0], 56 / self.cl.hp)

    def test_waits_with_a_shield(self):
        self.assertTrue(self.ask(1))  # Earthquake knocks Kingambit out; Foul Play meanwhile costs the shield

    def test_throws_without_one(self):
        self.assertFalse(self.ask(0))


class KeepTheLowOneIn(unittest.TestCase):
    def ask(self, foe_species):
        th = GD.build("thievul", ["SUCKER_PUNCH", "NIGHT_SLASH", "PLAY_ROUGH"])
        team = [Mon(GD.build("clodsire", ["POISON_STING", "STONE_EDGE", "EARTHQUAKE"]), hp=129), Mon(th, hp=31, energy=13),
                Mon(GD.build("snorlax", ["PSYWAVE", "BODY_SLAM", "EARTHQUAKE"]), hp=0)]  # Snorlax out, as live
        foe = Mon(GD.default(foe_species))
        foe.hp = int(0.902 * foe.build.hp)
        p = player()
        p.tracker = NS(foe=NS(mon=foe))
        p.foe_sid, p.foe_since, p.saved_for, p.save_checked, p.switch_ready_at = None, 0.0, None, None, 0.0
        p.team, p.active = [m.build for m in team], 1
        p.hp_now = lambda t, view: 0.246
        view = NS(me=NS(mon=team[1], team=team, shields=2, switch_wait=0, bench=lambda: [0]), foe=foe, foe_shields=0)
        return p.save_the_low_one(1.0, view, th, 13.0), p.logged

    def test_stays_in_against_palossand(self):
        to, logged = self.ask("palossand")
        self.assertIsNone(to)
        self.assertIn("save_the_low_one_not", logged)

    def test_saved_against_machamp(self):
        to, logged = self.ask("machamp")
        self.assertIsNotNone(to)
        self.assertIn("save_the_low_one", logged)


if __name__ == "__main__":
    unittest.main()


class ShieldToWin(unittest.TestCase):
    """223454: Thievul on 41 HP, two shields, against Trevenant on 16 of 131 with Seed Bomb paid for."""

    def setUp(self):
        self.th = GD.build("thievul", ["SUCKER_PUNCH", "NIGHT_SLASH", "PLAY_ROUGH"])
        self.tr = GD.build("trevenant", ["SHADOW_CLAW", "SEED_BOMB", "SHADOW_BALL"])

    def test_shields_a_knock_out_it_then_wins(self):
        m = pa.shield_saves_the_matchup(Mon(self.th, hp=41, energy=32), Mon(self.tr, hp=16), 60, 2, 1)
        self.assertIsNotNone(m)

    def test_not_a_hit_it_survives(self):
        # 9.0 s: Thievul on 108, Seed Bomb 45: no knock-out, the engine's call stands
        self.assertIsNone(pa.shield_saves_the_matchup(Mon(self.th, hp=108, energy=26), Mon(self.tr, hp=79), 48, 2, 2))

    def test_no_shield_no_call(self):
        self.assertIsNone(pa.shield_saves_the_matchup(Mon(self.th, hp=41, energy=32), Mon(self.tr, hp=16), 60, 0, 1))


class HoldForBetter(unittest.TestCase):
    """000629, 147.6 s: Vigoroth (53/145, 44 energy) threw Body Slam (27, resisted) into a shieldless Tinkaton with
    Bulldoze (69, 55 energy) 11 away."""

    def ask(self, energy=44, foe_shields=0, hp=53, me="vigoroth", moves=("SCRATCH", "BULLDOZE", "BODY_SLAM"),
            foe="tinkaton", foe_hp=110, k=1, foe_moves=None):
        b = GD.build(me, list(moves))
        p = player()
        p.team, p.active, p.decision = [b], 0, pa.CHARGED[0] + k
        foe_mon = Mon(GD.build(foe, list(foe_moves)) if foe_moves else GD.default(foe), hp=foe_hp)
        p.tracker = NS(foe=NS(mon=foe_mon, hi=42), me=NS(mon=Mon(b, hp=hp, energy=energy)))
        p.energy = lambda: energy
        p.paid_bounds = lambda: None
        p.hp_now = lambda t, view: hp / b.hp
        view = NS(me=NS(mon=Mon(b, hp=hp, energy=energy), shields=2), foe=foe_mon, foe_shields=foe_shields)
        p.hold_for_better(1.0, view)
        return p.decision, p.logged

    def test_holds_for_bulldoze(self):
        decision, logged = self.ask()
        self.assertEqual(decision, pa.FAST)
        self.assertIn("hold_for_better", logged)

    def test_throws_bulldoze_once_paid(self):
        decision, _ = self.ask(energy=56)
        self.assertEqual(decision, pa.CHARGED[0] + 0)  # Bulldoze, the left button

    def test_bait_into_shields_left_to_the_engine(self):
        decision, _ = self.ask(foe_shields=1)
        self.assertEqual(decision, pa.CHARGED[0] + 1)

    def test_snorlax_holds_for_earthquake_on_empoleon(self):
        decision, _ = self.ask(energy=40, hp=174, me="snorlax", moves=("PSYWAVE", "BODY_SLAM", "EARTHQUAKE"),
                               foe="empoleon", foe_hp=85, k=0)
        self.assertEqual(decision, pa.FAST)


class HoldForBetterLow(HoldForBetter):
    """094325, 86.8 s: Thievul (29 of 127, two shields, 42 energy) threw Night Slash (29) into a shieldless Mega
    Sableye on 43 with Play Rough (68) three Sucker Punches away; Sableye lived on 14 and won the matchup."""

    def thievul(self, hp):
        return self.ask(energy=42, hp=hp, me="thievul", moves=("SUCKER_PUNCH", "NIGHT_SLASH", "PLAY_ROUGH"),
                        foe="sableye_mega", foe_hp=43, k=0,
                        foe_moves=("SHADOW_CLAW", "FOUL_PLAY", "DAZZLING_GLEAM"))

    def test_holds_for_play_rough_when_it_lives_through_the_wait(self):
        decision, logged = self.thievul(29)
        self.assertEqual(decision, pa.FAST)
        self.assertIn("hold_for_better", logged)

    def test_throws_when_their_fast_moves_would_knock_it_out_first(self):
        decision, _ = self.thievul(4)
        self.assertEqual(decision, pa.CHARGED[0] + 0)
