"""Checks on the stats, the damage formula and the turn rules.

    python3 -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import STYLES, Masher, Planner, fasts_to_wait, solve_2x2  # noqa: E402
from pogo.battle import CHARGED, FAST, SWITCH, SWITCH_TURNS, Battle, Mon, damage  # noqa: E402
from pogo.gamedata import GameData, effectiveness  # noqa: E402

GD = GameData()


class Script:
    """Plays a fixed list of actions, then fast moves. Shields as told."""

    def __init__(self, actions=(), shield=False):
        self.actions = list(actions)
        self.use_shield = shield

    def act(self, view):
        return self.actions.pop(0) if self.actions else FAST

    def shield(self, view, foe_energy):
        return self.use_shield

    def replace(self, view):
        return view.me.bench()[0]


def azumarill():
    return GD.build("azumarill", ["BUBBLE", "ICE_BEAM", "PLAY_ROUGH"])


def medicham():
    return GD.build("medicham", ["COUNTER", "ICE_PUNCH", "PSYCHIC"])


class Stats(unittest.TestCase):
    def test_stats_match_pvpoke(self):
        checked = 0
        for entry in GD.rankings():
            sid = entry["speciesId"]
            if not GD.supported(sid) or any(m not in GD.moves for m in entry["moveset"]):
                continue
            b, want = GD.build(sid, entry["moveset"]), entry["stats"]
            shadow = b.atk != b.cmp_atk
            self.assertAlmostEqual(b.cmp_atk, want["atk"], delta=0.11, msg=sid)
            self.assertAlmostEqual(b.defense / (0.83333331 if shadow else 1), want["def"], delta=0.11, msg=sid)
            self.assertEqual(b.hp, want["hp"], sid)
            self.assertLessEqual(b.cp, 1500, sid)
            checked += 1
        self.assertGreater(checked, 1000)

    def test_known_cp(self):
        mewtwo = GD.build("mewtwo", ["CONFUSION", "PSYSTRIKE"], level=40, ivs=(15, 15, 15))
        self.assertEqual(mewtwo.cp, 4178)

    def test_type_chart(self):
        self.assertAlmostEqual(effectiveness("fire", ("grass", "steel")), 2.56, places=5)
        self.assertAlmostEqual(effectiveness("ground", ("flying",)), 0.390625)
        self.assertAlmostEqual(effectiveness("fighting", ("ghost", "dark")), 0.625, places=5)
        self.assertEqual(effectiveness("normal", ("water",)), 1.0)

    def test_damage_formula(self):
        az, me = Mon(azumarill()), Mon(medicham())
        play_rough = az.build.charged[1]
        raw = 0.5 * play_rough.power * 1.2 * 1.6 * 1.3 * az.build.atk / me.build.defense  # STAB, super effective
        self.assertEqual(damage(az, play_rough, me), int(raw) + 1)
        me.def_stage = -4  # defence halved
        self.assertEqual(damage(az, play_rough, me), int(raw * 2) + 1)
        az.atk_stage = 4  # attack doubled
        self.assertEqual(damage(az, play_rough, me), int(raw * 4) + 1)


class Turns(unittest.TestCase):
    def test_fast_move_lands_on_its_last_turn(self):
        b = Battle([azumarill()], [medicham()], Script(), Script())
        az, me = b.sides[0].mon, b.sides[1].mon
        b.step()  # Bubble is on turn 1 of 3, Counter on 1 of 2
        self.assertEqual((az.energy, me.energy, az.hp, me.hp), (0, 0, az.build.hp, me.build.hp))
        b.step()
        self.assertEqual((az.energy, me.energy), (0, 6))
        self.assertLess(az.hp, az.build.hp)
        b.step()
        self.assertEqual(az.energy, 11)
        self.assertLess(me.hp, me.build.hp)

    def test_charged_move_and_shield(self):
        az = Mon(azumarill(), energy=100)
        b = Battle([az], [medicham()], Script([CHARGED[0]]), Script(shield=True))
        b.step()
        self.assertEqual(az.energy, 100 - az.build.charged[0].energy)
        self.assertEqual(b.sides[1].shields, 1)
        self.assertEqual(b.sides[1].mon.hp, b.sides[1].mon.build.hp - 1)

    def test_energy_is_capped(self):
        az = Mon(azumarill(), energy=95)
        b = Battle([az], [medicham()], Script(), Script())
        for _ in range(3):
            b.step()
        self.assertEqual(az.energy, 100)

    def test_higher_attack_throws_first_and_cancels_the_other(self):
        az, me = Mon(azumarill(), hp=1, energy=100), Mon(medicham(), hp=1, energy=100)
        self.assertGreater(me.build.cmp_atk, az.build.cmp_atk)
        b = Battle([az], [me], Script([CHARGED[0]]), Script([CHARGED[0]]))
        self.assertEqual(b.run(), 1)
        self.assertEqual(me.hp, 1)
        self.assertEqual(az.energy, 100)  # never got its move off

    def test_knocked_out_pokemon_does_not_land_its_fast_move(self):
        az, me = Mon(azumarill(), energy=100), Mon(medicham(), hp=1)
        b = Battle([az], [me], Script([CHARGED[0]]), Script())
        b.step()  # Medicham starts Counter as Ice Beam knocks it out
        self.assertEqual(az.hp, az.build.hp)
        self.assertEqual(az.energy, 100 - az.build.charged[0].energy)
        self.assertEqual(b.winner, 0)

    def test_fast_move_in_progress_lands_after_a_charged_move(self):
        az, me = Mon(azumarill()), Mon(medicham(), energy=100)
        b = Battle([az], [me], Script(), Script([CHARGED[0]]))
        b.step()  # Bubble has two turns to go when Ice Punch is thrown
        self.assertEqual(az.energy, 11)
        self.assertEqual(b.sides[0].busy, 0)

    def test_switching(self):
        az = Mon(azumarill())
        az.atk_stage = -2
        b = Battle([az, medicham()], [medicham()], Script([SWITCH[1]]), Script())
        b.step()
        side = b.sides[0]
        self.assertEqual(side.mon.build.species_id, "medicham")
        self.assertEqual(az.atk_stage, 0)
        self.assertEqual(side.switch_wait, SWITCH_TURNS - 1)
        self.assertNotIn(SWITCH[0], b.views[0].legal())
        self.assertEqual(len(b.views[1].foe_shown), 2)

    def test_stat_changes_apply_through_shields_and_stop_at_four(self):
        me = Mon(GD.build("medicham", ["COUNTER", "POWER_UP_PUNCH", "PSYCHIC"]), energy=100)
        b = Battle([me], [azumarill()], Script([CHARGED[0], CHARGED[0]]), Script(shield=True))
        b.step()
        b.step()
        self.assertEqual(me.atk_stage, 2)
        me.atk_stage = 4
        me.energy = 100
        b.agents[0].actions = [CHARGED[0]]
        b.step()
        self.assertEqual(me.atk_stage, 4)

    def test_illegal_action_is_rejected(self):
        b = Battle([azumarill()], [medicham()], Script([CHARGED[0]]), Script())
        with self.assertRaises(ValueError):
            b.step()


class Timing(unittest.TestCase):
    def test_waits_for_the_last_turn_of_their_fast_move(self):
        self.assertEqual(fasts_to_wait(1, 3, 0), 2)  # they are just starting a 3-turn move
        self.assertEqual(fasts_to_wait(1, 3, 2), 1)
        self.assertEqual(fasts_to_wait(1, 3, 1), 0)  # their move lands this turn anyway
        self.assertEqual(fasts_to_wait(2, 3, 0), 1)
        self.assertEqual(fasts_to_wait(2, 2, 0), 0)  # same length never lines up, so do not wait
        self.assertEqual(fasts_to_wait(3, 1, 0), 0)  # a 1-turn move cannot gain free turns

    def test_good_timing_costs_the_opponent_a_fast_move(self):
        gained = {}
        for label, lead_in in (("early", [CHARGED[0]]), ("on time", [FAST, FAST, CHARGED[0]])):
            alt = Mon(GD.build("altaria", ["DRAGON_BREATH", "SKY_ATTACK"]), energy=100)  # 1-turn fast move
            az = Mon(azumarill())  # Bubble takes 3 turns
            b = Battle([alt], [az], Script(lead_in), Script(shield=True))
            for _ in lead_in:
                b.step()
            gained[label] = (az.energy, b.turn)
        # Thrown as Bubble starts, Bubble lands at once: 11 energy for one turn of the clock.
        self.assertEqual(gained["early"][0], 11)
        self.assertEqual(gained["on time"][0], 11)
        self.assertEqual(gained["on time"][1] - gained["early"][1], 2)


class Guessing(unittest.TestCase):
    def test_solve_2x2(self):
        self.assertAlmostEqual(solve_2x2(1, -1, -1, 1), 0.5)  # matching pennies
        self.assertEqual(solve_2x2(3, 2, 1, 0), 1.0)  # the first row is better whatever happens
        self.assertEqual(solve_2x2(0, 1, 2, 3), 0.0)
        p = solve_2x2(0, 1, 0.5, 0.2)
        self.assertAlmostEqual(p * 0 + (1 - p) * 0.5, p * 1 + (1 - p) * 0.2)  # the column player gains nothing either way

    def test_baiter_builds_energy_for_the_dearer_move(self):
        gator = Mon(GD.default("feraligatr"), energy=40)  # Hydro Cannon is ready, Ice Beam is not
        b = Battle([gator, azumarill()], [Mon(GD.default("altaria")), medicham()], Script(), Script(shield=True))

        def baiter():
            return Planner(bait="farm", shields="threshold", farm=False)

        self.assertEqual(baiter().act(b.views[0]), FAST)
        self.assertEqual(Planner(bait="cheap", farm=False).act(b.views[0]), CHARGED[0])
        gator.energy = 60
        b.sides[1].busy = 1  # Dragon Breath lands this turn, so the timing is already right
        self.assertEqual(baiter().act(b.views[0]), CHARGED[0])  # Hydro Cannon, with Ice Beam in hand
        b.sides[1].shields = 0
        self.assertEqual(baiter().act(b.views[0]), CHARGED[1])  # shields down: Ice Beam


class Reference(unittest.TestCase):
    def test_reproduces_pvpoke_battles_hit_for_hit(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import check_pvpoke
        ids, moves, lines = check_pvpoke.load()
        self.assertGreater(len(lines), 100)
        for line in lines:
            self.assertIsNone(check_pvpoke.check(GD, ids, moves, line))


class Tactics(unittest.TestCase):
    def test_farms_energy_in_a_matchup_it_dominates(self):
        alt = Mon(GD.default("altaria"), energy=60)
        b = Battle([alt, GD.default("melmetal")], [GD.default("torterra"), GD.default("jellicent")], Script(), Script())
        b.sides[1].busy = 1  # so that timing is not the reason to wait
        self.assertEqual(Planner(switches=False).act(b.views[0]), FAST)
        self.assertIn(Planner(farm=False, switches=False).act(b.views[0]), CHARGED)
        alt.energy = 100
        self.assertIn(Planner(switches=False).act(b.views[0]), CHARGED)  # full, so holding gains nothing

    def test_saves_a_spent_pokemon_and_brings_it_back_to_take_a_charged_move(self):
        az = Mon(azumarill(), hp=12)
        foe = Mon(GD.default("melmetal"))
        b = Battle([az, medicham(), GD.default("altaria")], [foe, GD.default("jellicent")], Script(), Script())
        self.assertIn(Planner().act(b.views[0]), SWITCH[1:])  # get it out before it goes down for nothing
        self.assertEqual(Planner(sac=False).act(b.views[0]), FAST)
        b.sides[0].active = 1  # Medicham is now in front, and faints
        b.sides[0].team[1].hp = 0
        foe.energy = 100
        self.assertEqual(Planner().replace(b.views[0]), 0)  # Melmetal has a move ready: let Azumarill take it
        foe.energy = 0
        self.assertEqual(Planner().replace(b.views[0]), 2)  # nothing ready: keep Azumarill in reserve


    def test_holds_a_ready_move_until_the_opponent_is_about_to_get_one(self):
        az = Mon(azumarill(), energy=60)  # both charged moves ready
        foe = Mon(GD.default("jellicent"))
        b = Battle([az, medicham()], [foe, GD.default("altaria")], Script(), Script())
        self.assertIn(Planner(switches=False, seed=1).act(b.views[0]), CHARGED)
        patient = Planner(switches=False, seed=1, hold=True, hold_cost=0.5)
        self.assertEqual(patient.act(b.views[0]), FAST)  # they are far from a move: keep building energy
        foe.energy = min(m.energy for m in foe.build.charged)
        self.assertIn(patient.act(b.views[0]), CHARGED)  # they have one now: no more waiting
        foe.energy = 0
        self.assertIn(Planner(switches=False, seed=1, hold=True, hold_cost=0.0).act(b.views[0]), CHARGED)  # any damage is too much


class Tracking(unittest.TestCase):
    def test_tracker_follows_a_battle_from_the_screen_alone(self):
        import random
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import check_tracker
        pool = [GD.default(b.species_id) for b in GD.meta(20)]
        rng = random.Random(1)
        tally = check_tracker.Tally()
        for seed in range(12):
            teams = rng.sample(pool, 3), rng.sample(pool, 3)
            agents = (check_tracker.ViaTracker(Planner(seed=seed)), Planner(seed=seed))
            check_tracker.play(GD, teams, agents, seed, check_tracker.CAMERAS["perfect"], tally, rng)
        self.assertGreater(tally.exact / tally.n, 0.95)  # their hidden energy, counted from my health bar
        self.assertGreater(tally.busy_right / tally.n, 0.95)
        self.assertEqual(tally.wrong_active, 0)


    def test_tracker_works_out_an_unusual_fast_move_from_the_health_bar(self):
        import random
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import check_tracker
        pool = [GD.default(b.species_id) for b in GD.meta(30)]
        rng = random.Random(2)
        right = wrong = 0
        for seed in range(12):
            mine, theirs = rng.sample(pool, 3), []
            for b in rng.sample(pool, 3):  # give each of theirs a fast move other than the usual one, where it has one
                others = [f for f in GD.species[b.species_id]["fastMoves"] if f in GD.moves and f != b.fast.id]
                theirs.append(GD.build(b.species_id, [others[0], *(m.id for m in b.charged)]) if others else b)
            agents = (check_tracker.ViaTracker(Planner(seed=seed)), Planner(seed=seed))
            check_tracker.play(GD, (mine, theirs), agents, seed, check_tracker.CAMERAS["perfect"], check_tracker.Tally(), rng)
            for truth in theirs:
                foe = agents[0].tracker.foes.get(truth.species_id)
                if foe and foe.fast_from == "inferred":
                    right += foe.mon.build.fast.id == truth.fast.id
                    wrong += foe.mon.build.fast.id != truth.fast.id
        self.assertGreater(right, 15)
        self.assertLessEqual(wrong, 1)


    def test_words_on_screen_rule_out_a_fast_move(self):
        from pogo.tracker import Observation, Tracker
        t = Tracker(GD, [GD.default("melmetal")])
        for k in range(14):  # my Thunder Shock is not very effective on Stunfisk; nothing says super effective
            t.update(Observation(t=0.5 * k, my_species="melmetal", foe_species="stunfisk", my_hp=1.0, foe_hp=1.0,
                                 effects=["weak"]))
        foe = t.foes["stunfisk"]
        self.assertIn("MUD_SHOT", foe.ruled_out)  # ground on steel would have said so
        self.assertEqual((foe.mon.build.fast.id, foe.fast_from), ("THUNDER_SHOCK", "inferred"))


class Learning(unittest.TestCase):
    def test_learner_without_a_policy_plays_as_the_planner(self):
        from pogo.learner import Learner
        pool = GD.meta(12)
        for seed in range(4):
            teams = pool[seed:seed + 3], pool[seed + 5:seed + 8]
            log = []
            a = Battle(*teams, Learner(log=log, seed=seed), Masher(), seed=seed)
            b = Battle(*teams, Planner(seed=seed), Masher(), seed=seed)
            self.assertEqual((a.run(), a.turn), (b.run(), b.turn))
            self.assertTrue(all(len(x) == 45 for _, x, _, _ in log))

    def test_policy_learns_to_imitate(self):
        import numpy as np
        from pogo.learner import Policy
        rng = np.random.default_rng(0)
        x = rng.normal(size=(600, 45))
        action = (x[:, 0] > 0).astype(int)  # the right choice depends on the first input only
        mask = np.ones((600, 2), dtype=bool)
        policy = Policy(seed=0)
        for _ in range(300):
            policy.step("shield", x, mask, action, np.ones(600), rate=1e-2)
        p, _ = policy.probabilities("shield", x, mask)
        self.assertGreater((p.argmax(axis=1) == action).mean(), 0.95)
        masked, _ = policy.probabilities("throw", x[:5], np.array([[True, False, True]] * 5))
        self.assertTrue((masked[:, 1] == 0).all())


class Games(unittest.TestCase):
    def test_full_battles_finish(self):
        pool = GD.meta(12)
        for make in (Planner, *STYLES.values()):
            for seed in range(5):
                battle = Battle(pool[seed:seed + 3], pool[seed + 4:seed + 7], make(), Masher(), seed=seed)
                self.assertIn(battle.run(), (0, 1, -1))
                self.assertTrue(battle.sides[0].left() == 0 or battle.sides[1].left() == 0 or battle.turn >= 480)


if __name__ == "__main__":
    unittest.main()
