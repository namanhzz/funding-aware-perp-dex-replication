from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize


@dataclass(slots=True)
class OUFit:
    kappa: float
    theta: float
    sigma: float
    log_likelihood: float
    half_life_hours: float
    n_obs: int
    dt_mean_hours: float
    residuals: np.ndarray
    standardized_residuals: np.ndarray

    def as_dict(self) -> dict[str, float | int]:
        return {
            "kappa": self.kappa,
            "theta": self.theta,
            "sigma": self.sigma,
            "log_likelihood": self.log_likelihood,
            "half_life_hours": self.half_life_hours,
            "n_obs": self.n_obs,
            "dt_mean_hours": self.dt_mean_hours,
        }


def _clean_series(values: Iterable[float]) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    return array[np.isfinite(array)]


def _clean_observations(values: Iterable[float], times: Iterable[object] | None = None) -> tuple[np.ndarray, list[object] | None]:
    raw_values = pd.Series(list(values), dtype="float64")
    mask = np.isfinite(raw_values.to_numpy())
    clean_values = raw_values.loc[mask].to_numpy(dtype=float)
    if times is None:
        return clean_values, None
    raw_times = pd.Series(list(times))
    if len(raw_times) != len(raw_values):
        raise ValueError("times length must match values length")
    clean_times = raw_times.loc[mask].tolist()
    return clean_values, clean_times


def _time_deltas_hours(times: Iterable[object] | None, n_obs: int) -> np.ndarray:
    if times is None:
        return np.ones(n_obs - 1, dtype=float)
    index = pd.to_datetime(pd.Series(list(times)), utc=True)
    if len(index) != n_obs:
        raise ValueError("times length must match values length")
    deltas = index.diff().dt.total_seconds().to_numpy()[1:] / 3600.0
    if np.any(~np.isfinite(deltas)) or np.any(deltas <= 0):
        raise ValueError("times must be strictly increasing")
    return deltas


def ou_log_likelihood(values: Iterable[float], kappa: float, theta: float, sigma: float, times: Iterable[object] | None = None) -> float:
    x, clean_times = _clean_observations(values, times)
    if len(x) < 3:
        raise ValueError("At least three observations are required")
    if kappa <= 0 or sigma <= 0:
        return -np.inf
    dt = _time_deltas_hours(clean_times, len(x))
    prev = x[:-1]
    nxt = x[1:]
    phi = np.exp(-kappa * dt)
    mean = theta + phi * (prev - theta)
    variance = (sigma**2) * (1.0 - phi**2) / (2.0 * kappa)
    if np.any(variance <= 0) or np.any(~np.isfinite(variance)):
        return -np.inf
    log_terms = -0.5 * (np.log(2.0 * np.pi * variance) + ((nxt - mean) ** 2) / variance)
    return float(np.sum(log_terms))


def _ols_start(x: np.ndarray, dt: np.ndarray) -> tuple[float, float, float]:
    prev = x[:-1]
    nxt = x[1:]
    design = np.column_stack([np.ones_like(prev), prev])
    intercept, phi = np.linalg.lstsq(design, nxt, rcond=None)[0]
    phi = float(np.clip(phi, 1e-5, 0.99999))
    dt_mean = float(np.mean(dt))
    kappa = max(-np.log(phi) / dt_mean, 1e-6)
    theta = float(intercept / (1.0 - phi))
    resid = nxt - (intercept + phi * prev)
    eps_var = float(np.var(resid, ddof=1))
    sigma = np.sqrt(max(eps_var * 2.0 * kappa / (1.0 - phi**2), 1e-18))
    return kappa, theta, float(sigma)


def fit_ou_mle(values: Iterable[float], times: Iterable[object] | None = None) -> OUFit:
    x, clean_times = _clean_observations(values, times)
    if len(x) < 10:
        raise ValueError("At least ten observations are required for OU calibration")
    dt = _time_deltas_hours(clean_times, len(x))
    kappa0, theta0, sigma0 = _ols_start(x, dt)

    def unpack(params: np.ndarray) -> tuple[float, float, float]:
        log_kappa, theta, log_sigma = params
        return float(np.exp(log_kappa)), float(theta), float(np.exp(log_sigma))

    def objective(params: np.ndarray) -> float:
        kappa, theta, sigma = unpack(params)
        return -ou_log_likelihood(x, kappa, theta, sigma, times=clean_times)

    result = minimize(
        objective,
        x0=np.array([np.log(kappa0), theta0, np.log(sigma0)]),
        method="Nelder-Mead",
        options={"maxiter": 5_000, "xatol": 1e-12, "fatol": 1e-8},
    )
    if not result.success:
        result = minimize(
            objective,
            x0=np.array([np.log(kappa0), theta0, np.log(sigma0)]),
            method="BFGS",
            options={"maxiter": 2_000},
        )
    kappa, theta, sigma = unpack(result.x)

    prev = x[:-1]
    nxt = x[1:]
    phi = np.exp(-kappa * dt)
    mean = theta + phi * (prev - theta)
    variance = (sigma**2) * (1.0 - phi**2) / (2.0 * kappa)
    residuals = nxt - mean
    standardized = residuals / np.sqrt(variance)
    half_life = float(np.log(2.0) / kappa)
    ll = ou_log_likelihood(x, kappa, theta, sigma, times=clean_times)
    return OUFit(
        kappa=float(kappa),
        theta=float(theta),
        sigma=float(sigma),
        log_likelihood=float(ll),
        half_life_hours=half_life,
        n_obs=len(x),
        dt_mean_hours=float(np.mean(dt)),
        residuals=residuals,
        standardized_residuals=standardized,
    )
