# Port of PvPoke (https://github.com/pvpoke/pvpoke), MIT licensed.
# Upstream revision: c15fb6f7e8613169740d904d6f96baa1824de480.
# Copyright (c) PvPoke contributors.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""PvPoke's default simulate-mode, single-matchup AI (not TrainingAI).

The camelCase names deliberately follow ActionLogic.js and Pokemon.js.
Move metadata is private to the AI; hypothetical buffs never mutate the engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, inf
from types import SimpleNamespace

from .battle import CHARGED, FAST, Mon, damage


class _Move:
    def __init__(self, move):
        self.original = move
        self.moveId = move.id
        self.name = move.name
        self.energy = move.energy
        self.energyGain = move.energy_gain
        self.turns = move.turns
        self.cooldown = move.turns * 500
        self.buffApplyChance = move.buff_chance
        self.buffTarget = ('both' if any(move.self_buffs) and any(move.foe_buffs)
                           else 'self' if any(move.self_buffs) else 'opponent')
        self.buffs = (move.self_buffs if self.buffTarget == 'self' else move.foe_buffs) if move.buff_chance else None
        self.selfAttackDebuffing = move.self_buffs[0] < 0
        self.selfDefenseDebuffing = move.self_buffs[1] < 0
        self.selfDebuffing = self.selfAttackDebuffing or self.selfDefenseDebuffing
        self.selfBuffing = any(v > 0 for v in move.self_buffs) or any(v < 0 for v in move.foe_buffs)
        self.damage = 0
        self.dpe = 0.0


class _Pokemon:
    def __init__(self, mon):
        self.mon = mon.copy()
        self.stats = SimpleNamespace(atk=mon.build.cmp_atk, hp=mon.build.hp)
        self.speciesName = mon.build.name
        self.speciesId = mon.build.species_id
        self.fastMove = _Move(mon.build.fast)
        self.chargedMoves = [_Move(m) for m in mon.build.charged]
        self.baitShields = 1
        self.farmEnergy = False
        self.optimizeMoveTiming = True
        self.turnsToKO = -1

    def sync(self, mon, shields, cooldown):
        self.mon = mon.copy()
        self.hp, self.energy = mon.hp, mon.energy
        self.shields, self.cooldown = shields, cooldown

    def getBoostMove(self):
        boostMove = None
        for move in self.chargedMoves:
            if move.buffs and move.buffApplyChance >= .5 and not move.selfDebuffing:
                boostMove = move
        return boostMove

    def resetMoves(self, opponent):
        # Pokemon.initializeMove, then resetMoves' ordering and best-DPE rules.
        for move in [self.fastMove] + self.chargedMoves:
            move.damage = _damage(self, opponent, move)
            if move.energy:
                move.dpe = move.damage / move.energy
                buffEffect = 0
                if move.buffs:
                    if move.buffTarget == 'self' and move.buffs[0] > 0:
                        buffEffect = move.buffs[0] * 80 / move.energy
                    elif move.buffTarget == 'opponent' and move.buffs[1] < 0:
                        buffEffect = abs(move.buffs[1]) * 80 / move.energy
                if buffEffect > 0:
                    move.dpe *= (4 + buffEffect * move.buffApplyChance) / 4
        moves = self.activeChargedMoves = sorted(self.chargedMoves, key=lambda m: m.energy)
        self.fastestChargedMove = moves[0] if moves else None
        for i in range(1, len(moves)):
            if moves[i].energy == moves[0].energy and not moves[i].selfDebuffing:
                if moves[i].buffs or moves[i].damage > moves[0].damage:
                    moves.append(moves.pop(0))
            if (moves[i].energy == moves[0].energy and moves[0].buffs and moves[i].buffs
                    and not moves[i].selfDebuffing and moves[i].buffApplyChance > moves[0].buffApplyChance):
                moves.append(moves.pop(0))
            if moves[0].moveId == 'FOCUS_BLAST' and moves[i].moveId == 'ZAP_CANNON':
                if moves[i].dpe - moves[0].dpe > -.3:
                    moves[0].buffs, moves[0].buffTarget, moves[0].selfDebuffing = (0, 0), 'self', True
                else:
                    moves[0].buffs, moves[0].buffTarget, moves[0].selfDebuffing = None, None, False
            if moves[i].energy - moves[0].energy <= 10 and not moves[i].selfDebuffing:
                if moves[i].selfBuffing and moves[0].dpe - moves[i].dpe < .3:
                    moves.append(moves.pop(0))
            if (moves[i].energy - moves[0].energy <= 10 and moves[0].selfAttackDebuffing
                    and not moves[i].selfDebuffing):
                moves.append(moves.pop(0))
            if (moves[i].energy - moves[0].energy <= 10 and moves[0].selfDebuffing
                    and moves[0].energy > 50 and not moves[i].selfDebuffing):
                moves.append(moves.pop(0))
            if moves[i].energy - moves[0].energy <= 5 and moves[i].selfBuffing:
                moves.append(moves.pop(0))
        self.bestChargedMove = moves[0] if moves else None
        if not moves:
            return
        self.bestChargedMove.dpe = self.bestChargedMove.damage / self.bestChargedMove.energy
        for move in moves:
            move.dpe = move.damage / move.energy
            best = self.bestChargedMove
            if ((move.dpe - best.dpe > .03 and move.moveId != 'SUPER_POWER') or move.dpe - best.dpe > .3):
                if not best.selfBuffing or move.dpe - best.dpe > .3:
                    self.bestChargedMove = move
            best = self.bestChargedMove
            if (abs(move.dpe - best.dpe) < .03 and best.buffs and move.buffs
                    and move.buffApplyChance > best.buffApplyChance and not move.selfDebuffing):
                self.bestChargedMove = move
            if move.moveId == 'OBSTRUCT':
                self.bestChargedMove = move
        if (moves[0].moveId == 'OBSTRUCT' and moves[0].energy - self.bestChargedMove.energy <= 5
                and moves[0].dpe / self.bestChargedMove.dpe > .2):
            self.bestChargedMove = moves[0]


def _damage(attacker, defender, move, attackBuff=0):
    user = attacker.mon.copy()
    user.atk_stage = max(-4, min(4, user.atk_stage + attackBuff))
    return damage(user, move.original, defender.mon)


@dataclass
class BattleState:
    energy: float
    oppHealth: float
    turn: int
    oppShields: int | None
    moves: list
    buffs: int
    chance: float = 1


def _insert(queue, state, after_equal=True):
    # Keep JS splice ordering, including its different treatment of ties.
    i = 0
    while i < len(queue) and (queue[i].turn <= state.turn if after_equal else queue[i].turn < state.turn):
        i += 1
    queue.insert(i, state)


def _debuffs(moves):
    result = 0
    for move in moves:
        if move.selfDebuffing:
            result += 1
        if move.buffApplyChance == 1 and move.buffTarget == 'self' and sum(move.buffs) > 0:
            result -= 1
    return result


class PvpokeAI:
    sees_move = True

    def __init__(self):
        self._pair = None

    def _pokemon(self, view):
        key = (id(view.me.mon), id(view.foe))
        if self._pair != key:
            self._pair = key
            self._poke, self._opponent = _Pokemon(view.me.mon), _Pokemon(view.foe)
            self._poke.resetMoves(self._opponent)
            self._opponent.resetMoves(self._poke)
        self._poke.sync(view.me.mon, view.me.shields, 0)
        self._opponent.sync(view.foe, view.foe_shields, view.foe_busy * 500)
        # Battle.useMove refreshes fast damage as attacks land. Reconstruct it
        # at the decision boundary; DPE and move ordering remain initialized.
        self._poke.fastMove.damage = _damage(self._poke, self._opponent, self._poke.fastMove)
        self._opponent.fastMove.damage = _damage(self._opponent, self._poke, self._opponent.fastMove)
        return self._poke, self._opponent

    def act(self, view):
        poke, opponent = self._pokemon(view)
        move = self.decideAction(poke, opponent)
        if move is not None:
            # Preserve the useMove damage cache for subsequent decisions.
            move.damage = _damage(poke, opponent, move)
        return FAST if move is None else CHARGED[poke.chargedMoves.index(move)]

    def replace(self, view):
        return view.me.bench()[0]

    @staticmethod
    def wouldShield(attacker, defender, move):
        # ActionLogic.wouldShield: preserve its unusual choice of buff recipient.
        move.damage = _damage(attacker, defender, move)
        postMoveHP = defender.hp - move.damage
        moveBuffs = move.buffs or (0, 0)
        target = attacker if moveBuffs[0] > 0 else defender
        currentBuffs = target.mon.atk_stage, target.mon.def_stage
        target.mon.atk_stage = max(-4, min(4, currentBuffs[0] + moveBuffs[0]))
        target.mon.def_stage = max(-4, min(4, currentBuffs[1] + moveBuffs[1]))
        fastDamage = _damage(attacker, defender, attacker.fastMove)
        fastAttacks = ceil((move.energy - max(attacker.energy - move.energy, 0)) / attacker.fastMove.energyGain) + 1
        cycleDamage = (fastAttacks * fastDamage + 1) * defender.shields
        useShield = postMoveHP <= cycleDamage
        target.mon.atk_stage, target.mon.def_stage = currentBuffs
        fastDPT = fastDamage / attacker.fastMove.turns
        for chargedMove in attacker.chargedMoves:
            if attacker.energy + chargedMove.energy >= chargedMove.energy:
                chargedDamage = _damage(attacker, defender, chargedMove)
                if chargedDamage >= defender.hp / 1.4 and fastDPT > 1.5:
                    useShield = True
                if chargedDamage >= defender.hp - cycleDamage:
                    useShield = True
        if move.selfAttackDebuffing and move.damage / defender.hp > .55:
            useShield = True
        if attacker.baitShields == 2:
            useShield = True
        return useShield

    def shield(self, view, foe_energy, move):
        defender, attacker = self._pokemon(view)
        found = next((m for m in attacker.chargedMoves if m.moveId == move.id), None)
        if found is None:  # a form change gave the move another id (Morpeko's Aura Wheel): take the same slot
            k = next((i for i, m in enumerate(view.foe.build.charged) if m is move or m.id == move.id), 0)
            found = attacker.chargedMoves[min(k, len(attacker.chargedMoves) - 1)]
        move = found
        # Battle.js subtracts the cost BEFORE wouldShield; the engine calls us before.
        attacker.energy = foe_energy - move.energy
        shieldDecision = self.wouldShield(attacker, defender, move)
        useShield = True
        if move.buffs and move.selfBuffing:
            if ((move.buffTarget == 'self' and move.buffs[0] > 0)
                    or (move.buffTarget == 'opponent' and move.buffs[1] < 0)
                    or (move.buffTarget == 'both' and (move.original.self_buffs[0] > 0 or move.original.foe_buffs[1] < 0))):
                useShield = shieldDecision
        if defender.bestChargedMove and defender.bestChargedMove.selfDefenseDebuffing:
            if attacker.shields > 0:
                useShield = shieldDecision
            elif attacker.bestChargedMove:
                fastToNextCharged = ceil((defender.bestChargedMove.energy - defender.energy) / defender.fastMove.energyGain)
                turnsToNextCharged = fastToNextCharged * defender.fastMove.turns
                cycleDamage = fastToNextCharged * defender.fastMove.damage + defender.bestChargedMove.damage
                attackerTurnsToNextCharged = ceil((attacker.activeChargedMoves[0].energy - attacker.energy) / attacker.fastMove.energyGain) * attacker.fastMove.turns
                if attacker.stats.atk > defender.stats.atk:
                    attackerTurnsToNextCharged -= 1
                if turnsToNextCharged >= attackerTurnsToNextCharged and attacker.hp <= cycleDamage:
                    useShield = shieldDecision
        return useShield

    def decideAction(self, poke, opponent):
        winsCMP = poke.stats.atk >= opponent.stats.atk
        fastDamage = _damage(poke, opponent, poke.fastMove)
        oppFastDamage = _damage(opponent, poke, opponent.fastMove)
        moves = poke.activeChargedMoves
        if not moves or poke.energy < poke.fastestChargedMove.energy or poke.farmEnergy:
            return None
        chargedMoveReady = [0 if poke.energy >= m.energy else ceil((m.energy - poke.energy) / poke.fastMove.energyGain) * poke.fastMove.turns for m in moves]
        hasNonDebuff = any(not m.selfDebuffing for m in moves)
        turnsToLive = inf
        if opponent.cooldown:
            queue = [(poke.hp - oppFastDamage, opponent.energy + opponent.fastMove.energyGain, opponent.cooldown / 500, poke.shields)]
        else:
            queue = [(poke.hp, opponent.energy, 0, poke.shields)]
        while queue:
            hp, opEnergy, turn, shields = queue.pop(0)
            if hp > oppFastDamage and turn > poke.fastMove.turns + (0 if winsCMP else 1):
                continue
            if shields:
                if opponent.fastestChargedMove and opEnergy >= opponent.fastestChargedMove.energy:
                    queue.insert(0, (hp - 1, opEnergy - opponent.fastestChargedMove.energy, turn + 1, shields - 1))
            else:
                for move in opponent.activeChargedMoves:
                    if opEnergy >= move.energy:
                        moveDamage = _damage(opponent, poke, move)
                        if moveDamage >= hp:
                            turnsToLive = min(turn, turnsToLive)
                            if poke.stats.atk > opponent.stats.atk and opponent.fastMove.cooldown % poke.fastMove.cooldown == 0:
                                turnsToLive += 1
                            break
                        queue.insert(0, (hp - moveDamage, opEnergy - move.energy, turn + 1, shields))
            if hp - oppFastDamage <= 0:
                turnsToLive = min(turn + opponent.fastMove.turns, turnsToLive)
                break
            queue.insert(0, (hp - oppFastDamage, opEnergy + opponent.fastMove.energyGain, turn + opponent.fastMove.turns, shields))

        if turnsToLive != -1:
            if poke.hp <= opponent.fastMove.damage * 2 and opponent.fastMove.cooldown == 500:
                turnsToLive -= 1
            if poke.hp <= opponent.fastMove.damage and opponent.cooldown > 0 and opponent.fastMove.cooldown > 500:
                turnsToLive = opponent.cooldown / 500
                if opponent.hp > poke.fastMove.damage:
                    turnsToLive -= 1
            if poke.hp <= opponent.fastMove.damage and opponent.cooldown == 0 and opponent.fastMove.cooldown <= poke.fastMove.cooldown + 500:
                if opponent.hp > poke.fastMove.damage:
                    turnsToLive -= 1
            if (turnsToLive * 500 < poke.fastMove.cooldown
                    or (turnsToLive * 500 == poke.fastMove.cooldown and (not winsCMP or poke.hp <= opponent.fastMove.damage))):
                selectedMove, prevMoveDamage = None, -1
                # JS begins one past the array; undefined == 0 is false.
                for n in reversed(range(len(moves))):
                    if chargedMoveReady[n] == 0:
                        moveDamage = _damage(poke, opponent, moves[n])
                        if moveDamage > prevMoveDamage:
                            selectedMove, prevMoveDamage = moves[n], moveDamage
                        if poke.energy >= moves[n].energy * 2 and poke.stats.atk > opponent.stats.atk and moveDamage * 2 > prevMoveDamage:
                            selectedMove, prevMoveDamage = moves[n], moveDamage * 2
                return selectedMove

        if not poke.farmEnergy and opponent.shields == 0:
            for n, move in enumerate(moves):
                if poke.energy >= move.energy:
                    moveDamage = _damage(poke, opponent, move)
                    if (opponent.hp <= moveDamage and not move.selfDebuffing
                            and (n == 0 or (n == 1 and not poke.baitShields)) and opponent.hp > poke.fastMove.damage):
                        return move

        if poke.optimizeMoveTiming:
            targetCooldown = 500
            if poke.fastMove.cooldown >= 2000:
                targetCooldown = 1000
            if poke.fastMove.cooldown >= 1500 and opponent.fastMove.cooldown == 2500:
                targetCooldown = 1000
            if poke.fastMove.cooldown == 1000 and opponent.fastMove.cooldown == 2000:
                targetCooldown = 1000
            if poke.fastMove.cooldown == opponent.fastMove.cooldown:
                targetCooldown = 0
            if poke.fastMove.cooldown % opponent.fastMove.cooldown == 0 and poke.fastMove.cooldown > opponent.fastMove.cooldown:
                targetCooldown = 0
            if (opponent.cooldown == 0 or opponent.cooldown > targetCooldown) and targetCooldown > 0:
                optimizeTiming = True
                if poke.hp <= opponent.fastMove.damage:
                    optimizeTiming = False
                # act() only runs when our fast move has finished: no queued fasts.
                if poke.energy + poke.fastMove.energyGain > 100:
                    optimizeTiming = False
                turnsPlanned = poke.fastMove.turns + floor(poke.energy / moves[0].energy)
                if poke.stats.atk < opponent.stats.atk:
                    turnsPlanned += 1
                if turnsPlanned > turnsToLive:
                    optimizeTiming = False
                if opponent.shields == 0:
                    for move in moves:
                        move.damage = _damage(poke, opponent, move)
                        if poke.energy >= move.energy and move.damage >= opponent.hp:
                            optimizeTiming = False
                            break
                for move in opponent.activeChargedMoves:
                    fastMovesFromCharged = ceil((move.energy - opponent.energy) / opponent.fastMove.energyGain)
                    fastMovesInFastMove = floor(poke.fastMove.cooldown / opponent.fastMove.cooldown)
                    turnsFromMove = fastMovesFromCharged * opponent.fastMove.turns + 1
                    move.damage = _damage(opponent, poke, move)
                    moveDamage = move.damage + opponent.fastMove.damage * fastMovesInFastMove
                    if poke.shields > 0:
                        moveDamage = 1 + opponent.fastMove.damage * fastMovesInFastMove
                    if turnsFromMove <= poke.fastMove.turns and moveDamage >= poke.hp:
                        optimizeTiming = False
                        break
                fastMovesInFastMove = floor((poke.fastMove.cooldown + 500) / opponent.fastMove.cooldown)
                if poke.hp <= opponent.fastMove.damage * fastMovesInFastMove:
                    optimizeTiming = False
                if optimizeTiming:
                    return None

        bestChargedDamage = _damage(poke, opponent, poke.bestChargedMove)
        bestCycleDamage = bestChargedDamage + fastDamage * ceil(poke.bestChargedMove.energy / poke.fastMove.energyGain)
        minimumCycleThreshold = 2
        if (poke.bestChargedMove.selfDebuffing and poke.bestChargedMove.energy > poke.fastestChargedMove.energy
                and poke.bestChargedMove.dpe / poke.fastestChargedMove.dpe < 2):
            minimumCycleThreshold = 1.1
        if opponent.hp / bestCycleDamage > minimumCycleThreshold:
            selectedMove = poke.bestChargedMove
            if len(moves) > 1:
                for move in moves:
                    if poke.bestChargedMove.selfDebuffing and not move.selfDebuffing and selectedMove.dpe / move.dpe < 2:
                        selectedMove = move
                    if poke.baitShields and opponent.shields > 0 and not moves[0].selfDebuffing and self.wouldShield(poke, opponent, move):
                        selectedMove = moves[0]
            if poke.energy < selectedMove.energy:
                return None
            if selectedMove.selfDebuffing:
                energyToReach = poke.energy + floor((100 - poke.energy) / poke.fastMove.energyGain) * poke.fastMove.energyGain
                if poke.energy < energyToReach:
                    return None
            return selectedMove

        finalState = self._plan(poke, opponent, hasNonDebuff)
        if finalState is None:
            return None
        if not finalState.moves:
            boostMove = poke.getBoostMove()
            if not boostMove:
                return None
            finalState.moves.append(boostMove)
        debuffingMove = any(m.selfDebuffing for m in finalState.moves)
        if poke.baitShields and opponent.shields > 0 and len(moves) > 1:
            for move in moves[1:]:
                if poke.energy < move.energy and move.dpe > finalState.moves[0].dpe:
                    bait = not (move.dpe / moves[0].dpe <= 1.5 and moves[0].selfBuffing)
                    if bait:
                        return None
            for move in moves[1:]:
                dpeRatio = (move.damage / move.energy) / (finalState.moves[0].damage / finalState.moves[0].energy)
                if poke.energy >= move.energy and dpeRatio > 1.5:
                    if not self.wouldShield(poke, opponent, move):
                        finalState.moves[0] = move
        # needsBoost stays false in upstream; non-guaranteed branches are disabled.
        if not poke.baitShields or (opponent.shields == 0 and not debuffingMove):
            finalState.moves.sort(key=lambda m: -_damage(poke, opponent, m))
        selectedMove = finalState.moves[0]
        if len(moves) > 1:
            first = moves[0]
            if opponent.shields > 0 and first.energy <= selectedMove.energy and first.dpe > selectedMove.dpe and not first.selfDebuffing:
                selectedMove = first
            if (opponent.shields == 0 and selectedMove.selfDebuffing and selectedMove.energy > 50
                    and poke.hp / poke.stats.hp > .5 and selectedMove.damage / opponent.hp < .8):
                selectedMove = first
            if first.energy == selectedMove.energy and first.dpe > selectedMove.dpe and not first.selfDebuffing:
                selectedMove = first
            if first.energy - 10 <= selectedMove.energy and first.dpe > selectedMove.dpe and selectedMove.selfDebuffing and not first.selfDebuffing:
                selectedMove = first
            if first.energy - selectedMove.energy <= 5 and first.dpe > selectedMove.dpe and first.selfBuffing:
                selectedMove = first
            if poke.baitShields and opponent.shields > 0:
                for move in moves[1:]:
                    if poke.energy >= move.energy and move.dpe > selectedMove.dpe:
                        if selectedMove.selfDebuffing and not move.selfDebuffing:
                            selectedMove = move
            if opponent.shields == 0 and selectedMove.selfDebuffing:
                for move in moves[1:]:
                    if move.dpe > selectedMove.dpe and not move.selfDebuffing:
                        selectedMove = move
            if opponent.shields > 0:
                for move in moves[1:]:
                    if first.selfDebuffing and not move.selfDebuffing:
                        if poke.baitShields or opponent.hp - first.damage > 10:
                            if move.energy - first.energy <= 10 and move.dpe / first.dpe > .7:
                                selectedMove = move
        if selectedMove.selfDebuffing and poke.shields == 0 and poke.energy < 100 and opponent.bestChargedMove:
            if opponent.energy >= opponent.bestChargedMove.energy and not self.wouldShield(opponent, poke, opponent.bestChargedMove) and not moves[0].selfBuffing:
                return None
        if selectedMove.selfDebuffing:
            targetEnergy = floor(100 / selectedMove.energy) * selectedMove.energy
            if poke.energy < targetEnergy:
                moveDamage = _damage(poke, opponent, selectedMove)
                if ((opponent.hp > moveDamage or opponent.shields != 0)
                        and (poke.hp > opponent.fastMove.damage * 2 or opponent.fastMove.cooldown - poke.fastMove.cooldown > 500)):
                    return None
            elif poke.baitShields and opponent.shields > 0 and moves[0].energy - selectedMove.energy <= 10 and not moves[0].selfDebuffing:
                if moves[0].selfBuffing or self.wouldShield(poke, opponent, selectedMove):
                    selectedMove = moves[0]
        return selectedMove if poke.energy >= selectedMove.energy else None

    @staticmethod
    def _plan(poke, opponent, hasNonDebuff):
        """The DP portion of decideAction, with JS queue ordering and quirks."""
        DPQueue = [BattleState(poke.energy, opponent.hp, 0, opponent.shields, [], 0)]
        stateCount = 0
        # JS var newEnergy is function scoped and can initially be undefined.
        newEnergy = float('nan')
        while DPQueue:
            if stateCount >= 500:
                return None
            stateCount += 1
            currState = DPQueue.pop(0)
            currState.buffs = max(-4, min(4, currState.buffs))
            if currState.oppHealth <= 0:
                # changeTTKChance is forced to zero, hence always chance == 1.
                return currState
            for move in poke.activeChargedMoves:
                ready = 0 if currState.energy >= move.energy else ceil((move.energy - currState.energy) / poke.fastMove.energyGain) * poke.fastMove.turns
                moveDamage = _damage(poke, opponent, move, currState.buffs)
                fastSimulatedDamage = _damage(poke, opponent, poke.fastMove, currState.buffs)
                if hasNonDebuff and poke.speciesName == 'Melmetal' and opponent.speciesName == 'Cresselia':
                    if move.selfDebuffing and move.buffs[1] < 1 and opponent.hp > moveDamage * (1 + 4 / (4 - move.buffs[0])):
                        continue
                movesToFarmDown = ceil(currState.oppHealth / fastSimulatedDamage)
                # Upstream uses nonexistent opponentShields (not oppShields).
                # It also tests nonexistent hp/shields for queue dominance;
                # those JS comparisons are false and must not prune states.
                _insert(DPQueue, BattleState(currState.energy + poke.fastMove.energyGain * movesToFarmDown,
                        0, currState.turn + movesToFarmDown * poke.fastMove.turns, None, currState.moves, currState.buffs))
                attackMult = currState.buffs
                if move.buffApplyChance == 1:
                    if move.buffTarget == 'self':
                        attackMult += move.buffs[0]
                    if move.buffTarget == 'opponent':
                        attackMult -= move.buffs[1]
                newShields = max(0, currState.oppShields - 1)
                usedMoves = currState.moves + [move]
                if ready == 0:
                    newOppHealth = currState.oppHealth - (1 if currState.oppShields > 0 else moveDamage)
                    i, insertElement = 0, True
                    while i < len(DPQueue) and DPQueue[i].turn == currState.turn + 1:
                        other = DPQueue[i]
                        if other.oppHealth == newOppHealth and other.buffs == attackMult:
                            if other.energy == currState.energy - move.energy:
                                if _debuffs(other.moves) > _debuffs(usedMoves):
                                    DPQueue.pop(i)
                                    continue
                            insertElement = False
                        i += 1
                    if insertElement:
                        # Preserve the stale newEnergy in JS's empty-queue branch.
                        energy = currState.energy - move.energy if DPQueue else newEnergy
                        _insert(DPQueue, BattleState(energy, newOppHealth, currState.turn + 1, newShields, usedMoves, attackMult))
                else:
                    newEnergy = currState.energy - move.energy + poke.fastMove.energyGain * (ready / poke.fastMove.turns)
                    newOppHealth = currState.oppHealth - fastSimulatedDamage * (ready / poke.fastMove.turns) - (1 if currState.oppShields > 0 else moveDamage)
                    _insert(DPQueue, BattleState(newEnergy, newOppHealth, currState.turn + ready + 1, newShields, usedMoves, attackMult), False)
                if move.selfDebuffing and move.buffs[0] < 0 and move.energy * 2 <= 100:
                    newTurn = ceil((move.energy * 2 - currState.energy) / poke.fastMove.energyGain) * poke.fastMove.turns
                    newEnergy = floor(newTurn / poke.fastMove.turns) * poke.fastMove.energyGain + currState.energy - move.energy
                    if ready != 0 or newTurn != 0:
                        newOppHealth = currState.oppHealth - fastSimulatedDamage * (newTurn / poke.fastMove.turns) - (1 if currState.oppShields > 0 else moveDamage)
                        newTurn += currState.turn + 1
                        _insert(DPQueue, BattleState(newEnergy, newOppHealth, newTurn, newShields, usedMoves, attackMult), ready == 0)
        return None
