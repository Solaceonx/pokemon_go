"""Sampling the energy probabilities exported by the tracker, including JSON string keys."""
from __future__ import annotations

import math
import random


def sample_energy(odds: dict, rng: random.Random) -> int:
    """Draw from relative weights (saved state rounds probabilities, so their sum need not be one)."""
    values, weights = [], []
    for value, weight in odds.items():
        energy, probability = int(value), float(weight)
        if float(value) != energy or not 0 <= energy <= 100:
            raise ValueError("energy probabilities must use integer energies from 0 to 100")
        if not math.isfinite(probability) or probability < 0:
            raise ValueError("energy probabilities must be finite and nonnegative")
        values.append(energy)
        weights.append(probability)
    if not weights or sum(weights) <= 0:
        raise ValueError("energy probabilities must have positive total weight")
    return rng.choices(values, weights)[0]
