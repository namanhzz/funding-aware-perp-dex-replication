from __future__ import annotations

import numpy as np


def fill_probability(lambda_base: float, intensity_k: float, delta: float, dt_hours: float) -> float:
    if lambda_base < 0 or intensity_k <= 0 or dt_hours < 0:
        raise ValueError("Invalid Poisson intensity parameters")
    intensity = lambda_base * np.exp(-intensity_k * max(delta, 0.0))
    return float(1.0 - np.exp(-intensity * dt_hours))


def simulate_fill(rng: np.random.Generator, lambda_base: float, intensity_k: float, delta: float, dt_hours: float) -> bool:
    return bool(rng.random() < fill_probability(lambda_base, intensity_k, delta, dt_hours))

