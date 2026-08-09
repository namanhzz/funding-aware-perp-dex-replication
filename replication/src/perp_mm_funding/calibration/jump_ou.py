from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import logsumexp

from perp_mm_funding.calibration.ou import OUFit, fit_ou_mle, ou_log_likelihood


@dataclass(slots=True)
class OUJumpDiagnostic:
    threshold_z: float
    jump_count: int
    total_transitions: int
    jump_fraction: float
    jump_intensity_per_hour: float
    jump_mean: float
    jump_std: float
    non_jump_residual_std: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "threshold_z": self.threshold_z,
            "jump_count": self.jump_count,
            "total_transitions": self.total_transitions,
            "jump_fraction": self.jump_fraction,
            "jump_intensity_per_hour": self.jump_intensity_per_hour,
            "jump_mean": self.jump_mean,
            "jump_std": self.jump_std,
            "non_jump_residual_std": self.non_jump_residual_std,
        }


@dataclass(slots=True)
class OUJumpFit:
    kappa: float
    theta: float
    sigma: float
    jump_intensity_per_hour: float
    jump_mean: float
    jump_sigma: float
    log_likelihood: float
    ou_log_likelihood: float
    likelihood_improvement: float
    aic: float
    bic: float
    posterior_jump_count: float
    n_obs: int
    dt_mean_hours: float
    converged: bool

    def as_dict(self) -> dict[str, float | int | bool]:
        return {
            "kappa": self.kappa,
            "theta": self.theta,
            "sigma": self.sigma,
            "jump_intensity_per_hour": self.jump_intensity_per_hour,
            "jump_mean": self.jump_mean,
            "jump_sigma": self.jump_sigma,
            "log_likelihood": self.log_likelihood,
            "ou_log_likelihood": self.ou_log_likelihood,
            "likelihood_improvement": self.likelihood_improvement,
            "aic": self.aic,
            "bic": self.bic,
            "posterior_jump_count": self.posterior_jump_count,
            "n_obs": self.n_obs,
            "dt_mean_hours": self.dt_mean_hours,
            "converged": self.converged,
        }


def threshold_ou_jump_diagnostic(fit: OUFit, threshold_z: float = 3.0) -> OUJumpDiagnostic:
    """Estimate first-pass OU+jump diagnostics from large standardized residuals.

    This threshold diagnostic is a calibration gate. The MLE below is the
    likelihood-based follow-up used for paper-grade parameter reporting.
    """

    z = np.asarray(fit.standardized_residuals, dtype=float)
    residuals = np.asarray(fit.residuals, dtype=float)
    mask = np.abs(z) >= threshold_z
    jumps = residuals[mask]
    non_jumps = residuals[~mask]
    duration_hours = max(fit.dt_mean_hours * len(residuals), fit.dt_mean_hours)
    jump_count = int(mask.sum())
    return OUJumpDiagnostic(
        threshold_z=float(threshold_z),
        jump_count=jump_count,
        total_transitions=int(len(residuals)),
        jump_fraction=float(jump_count / max(len(residuals), 1)),
        jump_intensity_per_hour=float(jump_count / duration_hours),
        jump_mean=float(np.mean(jumps)) if len(jumps) else 0.0,
        jump_std=float(np.std(jumps, ddof=1)) if len(jumps) > 1 else 0.0,
        non_jump_residual_std=float(np.std(non_jumps, ddof=1)) if len(non_jumps) > 1 else 0.0,
    )


def _clean_observations(values: Iterable[float], times: Iterable[object] | None = None) -> tuple[np.ndarray, pd.Series | None]:
    raw_values = pd.Series(list(values), dtype="float64")
    mask = np.isfinite(raw_values.to_numpy())
    clean_values = raw_values.loc[mask].to_numpy(dtype=float)
    if times is None:
        return clean_values, None
    raw_times = pd.to_datetime(pd.Series(list(times)), utc=True)
    if len(raw_times) != len(raw_values):
        raise ValueError("times length must match values length")
    return clean_values, raw_times.loc[mask].reset_index(drop=True)


def _time_deltas_hours(times: pd.Series | None, n_obs: int) -> np.ndarray:
    if times is None:
        return np.ones(n_obs - 1, dtype=float)
    deltas = times.diff().dt.total_seconds().to_numpy()[1:] / 3600.0
    if np.any(~np.isfinite(deltas)) or np.any(deltas <= 0):
        raise ValueError("times must be strictly increasing")
    return deltas


def _normal_logpdf(values: np.ndarray, mean: np.ndarray, variance: np.ndarray) -> np.ndarray:
    return -0.5 * (np.log(2.0 * np.pi * variance) + ((values - mean) ** 2) / variance)


def ou_jump_log_likelihood(
    values: Iterable[float],
    kappa: float,
    theta: float,
    sigma: float,
    jump_intensity_per_hour: float,
    jump_mean: float,
    jump_sigma: float,
    times: Iterable[object] | None = None,
) -> float:
    x, clean_times = _clean_observations(values, times)
    if len(x) < 3:
        raise ValueError("At least three observations are required")
    if kappa <= 0 or sigma <= 0 or jump_intensity_per_hour < 0 or jump_sigma <= 0:
        return -np.inf
    dt = _time_deltas_hours(clean_times, len(x))
    prev = x[:-1]
    nxt = x[1:]
    phi = np.exp(-kappa * dt)
    ou_mean = theta + phi * (prev - theta)
    ou_variance = (sigma**2) * (1.0 - phi**2) / (2.0 * kappa)
    if np.any(ou_variance <= 0) or np.any(~np.isfinite(ou_variance)):
        return -np.inf

    jump_probability = np.clip(1.0 - np.exp(-jump_intensity_per_hour * dt), 1e-12, 1.0 - 1e-12)
    no_jump_log_weight = np.log1p(-jump_probability)
    jump_log_weight = np.log(jump_probability)
    no_jump_log_density = _normal_logpdf(nxt, ou_mean, ou_variance)
    jump_log_density = _normal_logpdf(nxt, ou_mean + jump_mean, ou_variance + jump_sigma**2)
    terms = logsumexp(
        np.vstack([no_jump_log_weight + no_jump_log_density, jump_log_weight + jump_log_density]),
        axis=0,
    )
    return float(np.sum(terms))


def fit_ou_jump_mle(
    values: Iterable[float],
    times: Iterable[object] | None = None,
    threshold_z: float = 3.0,
    base_fit: OUFit | None = None,
) -> OUJumpFit:
    """Fit an OU plus Bernoulli-normal jump transition model.

    Transition approximation:

    X_{t+dt} | X_t ~ (1-p_dt) N(m_dt, v_dt)
                 + p_dt N(m_dt + mu_J, v_dt + sigma_J^2),

    where p_dt = 1 - exp(-lambda_J dt). This is a small-dt one-jump
    approximation rather than a full multi-jump compound-Poisson expansion.
    It is a defensible likelihood-based upgrade from threshold jump counting.
    """

    x, clean_times = _clean_observations(values, times)
    if len(x) < 20:
        raise ValueError("At least twenty observations are required for OU+jump calibration")
    clean_times_arg = clean_times.tolist() if clean_times is not None else None
    ou_fit = base_fit or fit_ou_mle(x, clean_times_arg)
    diagnostic = threshold_ou_jump_diagnostic(ou_fit, threshold_z=threshold_z)

    jump_sigma0 = max(diagnostic.jump_std, ou_fit.sigma * np.sqrt(max(ou_fit.dt_mean_hours, 1e-9)), 1e-8)
    jump_intensity0 = max(diagnostic.jump_intensity_per_hour, 1e-6)
    jump_mean0 = diagnostic.jump_mean

    x_scale = max(float(np.std(x, ddof=1)), 1e-8)
    theta_lower = float(np.min(x) - 5.0 * x_scale)
    theta_upper = float(np.max(x) + 5.0 * x_scale)
    jump_bound = 10.0 * x_scale

    initial = np.array(
        [
            np.log(max(ou_fit.kappa, 1e-8)),
            ou_fit.theta,
            np.log(max(ou_fit.sigma, 1e-12)),
            np.log(jump_intensity0),
            jump_mean0,
            np.log(jump_sigma0),
        ],
        dtype=float,
    )
    bounds = [
        (np.log(1e-5), np.log(20.0)),
        (theta_lower, theta_upper),
        (np.log(1e-12), np.log(max(1.0, 100.0 * x_scale))),
        (np.log(1e-8), np.log(2.0)),
        (-jump_bound, jump_bound),
        (np.log(1e-12), np.log(max(1.0, 100.0 * x_scale))),
    ]

    def unpack(params: np.ndarray) -> tuple[float, float, float, float, float, float]:
        return (
            float(np.exp(params[0])),
            float(params[1]),
            float(np.exp(params[2])),
            float(np.exp(params[3])),
            float(params[4]),
            float(np.exp(params[5])),
        )

    def objective(params: np.ndarray) -> float:
        return -ou_jump_log_likelihood(x, *unpack(params), times=clean_times_arg)

    result = minimize(
        objective,
        x0=initial,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 2_000, "ftol": 1e-9},
    )
    params = result.x if result.success else initial
    kappa, theta, sigma, jump_intensity, jump_mean, jump_sigma = unpack(params)
    ll = ou_jump_log_likelihood(x, kappa, theta, sigma, jump_intensity, jump_mean, jump_sigma, times=clean_times_arg)
    ou_ll = ou_log_likelihood(x, ou_fit.kappa, ou_fit.theta, ou_fit.sigma, times=clean_times_arg)

    dt = _time_deltas_hours(clean_times, len(x))
    prev = x[:-1]
    nxt = x[1:]
    phi = np.exp(-kappa * dt)
    ou_mean = theta + phi * (prev - theta)
    ou_variance = (sigma**2) * (1.0 - phi**2) / (2.0 * kappa)
    jump_probability = np.clip(1.0 - np.exp(-jump_intensity * dt), 1e-12, 1.0 - 1e-12)
    no_jump_log_weight = np.log1p(-jump_probability)
    jump_log_weight = np.log(jump_probability)
    no_jump_log_density = _normal_logpdf(nxt, ou_mean, ou_variance)
    jump_log_density = _normal_logpdf(nxt, ou_mean + jump_mean, ou_variance + jump_sigma**2)
    mixture_terms = logsumexp(
        np.vstack([no_jump_log_weight + no_jump_log_density, jump_log_weight + jump_log_density]),
        axis=0,
    )
    posterior_jump_probability = np.exp(jump_log_weight + jump_log_density - mixture_terms)
    n_params = 6
    n_transitions = len(x) - 1
    return OUJumpFit(
        kappa=kappa,
        theta=theta,
        sigma=sigma,
        jump_intensity_per_hour=jump_intensity,
        jump_mean=jump_mean,
        jump_sigma=jump_sigma,
        log_likelihood=float(ll),
        ou_log_likelihood=float(ou_ll),
        likelihood_improvement=float(ll - ou_ll),
        aic=float(2 * n_params - 2 * ll),
        bic=float(np.log(n_transitions) * n_params - 2 * ll),
        posterior_jump_count=float(np.sum(posterior_jump_probability)),
        n_obs=int(len(x)),
        dt_mean_hours=float(np.mean(dt)),
        converged=bool(result.success),
    )
