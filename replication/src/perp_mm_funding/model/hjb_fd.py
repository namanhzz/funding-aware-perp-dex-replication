from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:  # pragma: no cover - fallback is exercised only without optional numba.
    from numba import njit
except Exception:  # pragma: no cover
    njit = None


def _maybe_njit(*args, **kwargs):
    if njit is None:
        def decorator(func):
            return func

        return decorator
    return njit(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class HJBFDSolverParams:
    horizon_hours: float
    q_min: float
    q_max: float
    f_min: float
    f_max: float
    n_f: int
    n_t: int
    kappa: float
    theta_bar: float
    sigma_f: float
    fill_intensity: float
    intensity_k: float
    terminal_penalty: float
    running_penalty: float
    min_delta: float = 0.0
    q_step: float = 1.0
    enforce_cfl: bool = True


@dataclass(frozen=True, slots=True)
class HJBFDSolution:
    """Finite-difference value table for the reduced inventory/funding HJB."""

    t_grid: np.ndarray
    q_grid: np.ndarray
    f_grid: np.ndarray
    values: np.ndarray
    intensity_k: float
    min_delta: float = 0.0
    time_step: float = 0.0
    max_time_step: float = np.inf
    max_transition_rate: float = 0.0

    def theta(self, t_hours: float, q: int, f: float) -> float:
        q_idx = _q_index(self.q_grid, q)
        return float(_theta_interp_q_idx(self.t_grid, self.f_grid, self.values, t_hours, q_idx, f))

    def optimal_deltas(self, t_hours: float, q: float, f: float) -> tuple[float, float]:
        if self.intensity_k <= 0.0:
            raise ValueError("intensity_k must be positive")
        q = _snap_q(self.q_grid, q)
        q_idx = _q_index(self.q_grid, q)
        return _optimal_deltas_q_idx(
            self.t_grid,
            self.q_grid,
            self.f_grid,
            self.values,
            self.intensity_k,
            self.min_delta,
            t_hours,
            q_idx,
            f,
        )


def solve_hjb_fd(params: HJBFDSolverParams) -> HJBFDSolution:
    """Solve a monotone explicit finite-difference HJB on q/f grids.

    The reduced value function is theta(t, q, f) under the ansatz
    v=x+qS+theta. Funding follows an OU diffusion on the f grid, inventory
    jumps are discrete, and quote deltas are recovered from neighboring
    inventory value differences. The OU generator is represented as a
    birth-death chain on the truncated funding grid, so the explicit update is
    monotone when the CFL bound is respected.
    """

    _validate_params(params)
    t_grid = np.linspace(0.0, params.horizon_hours, params.n_t)
    q_grid = _inventory_grid(params.q_min, params.q_max, params.q_step)
    f_grid = np.linspace(params.f_min, params.f_max, params.n_f)
    values = np.zeros((params.n_t, len(q_grid), params.n_f), dtype=float)
    values[-1, :, :] = -params.terminal_penalty * q_grid[:, None] ** 2

    dt = t_grid[1] - t_grid[0]
    df = f_grid[1] - f_grid[0]
    max_transition_rate = _max_transition_rate(f_grid, df, params)
    max_time_step = _max_time_step(max_transition_rate)
    if params.enforce_cfl and dt > max_time_step * (1.0 + 1e-12):
        required_n_t = int(np.ceil(params.horizon_hours / max_time_step)) + 1
        raise ValueError(
            "n_t too low for monotone explicit HJB scheme: "
            f"dt={dt:.6g} exceeds CFL max_dt={max_time_step:.6g}; "
            f"use n_t >= {required_n_t}"
        )

    for t_idx in range(params.n_t - 2, -1, -1):
        next_values = values[t_idx + 1]
        generator = _ou_birth_death_generator(next_values, f_grid, df, params)
        source = generator - q_grid[:, None] * f_grid[None, :] - params.running_penalty * q_grid[:, None] ** 2
        source += _arrival_hamiltonian(next_values, params)
        values[t_idx] = next_values + dt * source

    return HJBFDSolution(
        t_grid=t_grid,
        q_grid=q_grid,
        f_grid=f_grid,
        values=values,
        intensity_k=params.intensity_k,
        min_delta=params.min_delta,
        time_step=dt,
        max_time_step=max_time_step,
        max_transition_rate=max_transition_rate,
    )


def monotone_cfl_bound(params: HJBFDSolverParams) -> float:
    """Return the largest explicit time step allowed by the monotone scheme."""

    _validate_params(params)
    f_grid = np.linspace(params.f_min, params.f_max, params.n_f)
    df = f_grid[1] - f_grid[0]
    return _max_time_step(_max_transition_rate(f_grid, df, params))


def _arrival_hamiltonian(theta: np.ndarray, params: HJBFDSolverParams) -> np.ndarray:
    hamiltonian = np.zeros_like(theta)
    for q_idx in range(theta.shape[0]):
        theta_now = theta[q_idx]
        if q_idx > 0:
            ask_jump = theta[q_idx - 1] - theta_now
            hamiltonian[q_idx] += _quote_hamiltonian(ask_jump, params)
        if q_idx < theta.shape[0] - 1:
            bid_jump = theta[q_idx + 1] - theta_now
            hamiltonian[q_idx] += _quote_hamiltonian(bid_jump, params)
    return hamiltonian


def _quote_hamiltonian(value_jump: np.ndarray, params: HJBFDSolverParams) -> np.ndarray:
    # ``delta`` is a price offset per unit while ``value_jump`` is the total
    # continuation-value change from trading one quote lot.  They are directly
    # comparable only when the lot size is one.  Keep the Hamiltonian in cash
    # units for arbitrary physical quote sizes.
    marginal_value = value_jump / params.q_step
    delta = np.maximum(params.min_delta, 1.0 / params.intensity_k - marginal_value)
    payoff = delta * params.q_step + value_jump
    return params.fill_intensity * np.exp(-params.intensity_k * delta) * payoff


def _ou_birth_death_generator(
    theta: np.ndarray,
    f_grid: np.ndarray,
    df: float,
    params: HJBFDSolverParams,
) -> np.ndarray:
    up_rate, down_rate = _ou_birth_death_rates(f_grid, df, params)
    generator = np.zeros_like(theta)
    generator[:, :-1] += up_rate[:-1][None, :] * (theta[:, 1:] - theta[:, :-1])
    generator[:, 1:] += down_rate[1:][None, :] * (theta[:, :-1] - theta[:, 1:])
    return generator


def _ou_birth_death_rates(
    f_grid: np.ndarray,
    df: float,
    params: HJBFDSolverParams,
) -> tuple[np.ndarray, np.ndarray]:
    drift = params.kappa * (params.theta_bar - f_grid)
    diffusion_rate = 0.5 * params.sigma_f**2 / (df**2)
    up_rate = diffusion_rate + np.maximum(drift, 0.0) / df
    down_rate = diffusion_rate + np.maximum(-drift, 0.0) / df

    # The truncated funding domain is represented as a finite-state chain:
    # transitions that would leave the grid are suppressed at the boundaries.
    down_rate[0] = 0.0
    up_rate[-1] = 0.0
    return up_rate, down_rate


def _max_transition_rate(f_grid: np.ndarray, df: float, params: HJBFDSolverParams) -> float:
    up_rate, down_rate = _ou_birth_death_rates(f_grid, df, params)
    ou_exit_rate = np.max(up_rate + down_rate)
    arrival_rate = 2.0 * params.fill_intensity * np.exp(-params.intensity_k * params.min_delta)
    return float(ou_exit_rate + arrival_rate)


def _max_time_step(max_transition_rate: float) -> float:
    if max_transition_rate <= 0.0:
        return float("inf")
    return 1.0 / max_transition_rate


def _inventory_grid(q_min: float, q_max: float, q_step: float) -> np.ndarray:
    n_steps = int(round((q_max - q_min) / q_step))
    grid = q_min + q_step * np.arange(n_steps + 1, dtype=float)
    if not np.isclose(grid[-1], q_max):
        raise ValueError("q_max must lie on the q_step grid from q_min")
    return grid


def _q_step(q_grid: np.ndarray) -> float:
    if len(q_grid) < 2:
        raise ValueError("q_grid must contain at least two inventory states")
    return float(q_grid[1] - q_grid[0])


def _snap_q(q_grid: np.ndarray, q: float) -> float:
    clipped = min(max(float(q), float(q_grid[0])), float(q_grid[-1]))
    idx = int(np.argmin(np.abs(q_grid - clipped)))
    return float(q_grid[idx])


def _q_index(q_grid: np.ndarray, q: float) -> int:
    matches = np.flatnonzero(np.isclose(q_grid, q, rtol=1e-9, atol=1e-9))
    if len(matches) == 0:
        raise ValueError(f"q={q} is outside the inventory grid")
    return int(matches[0])


@_maybe_njit(cache=True)
def _grid_interval(grid: np.ndarray, x: float) -> tuple[int, int, float]:
    if x <= grid[0]:
        return 0, 0, 0.0
    last = len(grid) - 1
    if x >= grid[last]:
        return last, last, 0.0

    hi = int(np.searchsorted(grid, x))
    lo = hi - 1
    denom = grid[hi] - grid[lo]
    if denom <= 0.0:
        return lo, hi, 0.0
    weight = (x - grid[lo]) / denom
    return lo, hi, weight


@_maybe_njit(cache=True)
def _theta_interp_q_idx(
    t_grid: np.ndarray,
    f_grid: np.ndarray,
    values: np.ndarray,
    t_hours: float,
    q_idx: int,
    f: float,
) -> float:
    t0, t1, wt = _grid_interval(t_grid, t_hours)
    f0, f1, wf = _grid_interval(f_grid, f)

    v00 = values[t0, q_idx, f0]
    if t0 == t1 and f0 == f1:
        return float(v00)
    v01 = values[t0, q_idx, f1]
    v0 = v00 + wf * (v01 - v00)
    if t0 == t1:
        return float(v0)

    v10 = values[t1, q_idx, f0]
    v11 = values[t1, q_idx, f1]
    v1 = v10 + wf * (v11 - v10)
    return float(v0 + wt * (v1 - v0))


@_maybe_njit(cache=True)
def _optimal_deltas_q_idx(
    t_grid: np.ndarray,
    q_grid: np.ndarray,
    f_grid: np.ndarray,
    values: np.ndarray,
    intensity_k: float,
    min_delta: float,
    t_hours: float,
    q_idx: int,
    f: float,
) -> tuple[float, float]:
    theta_now = _theta_interp_q_idx(t_grid, f_grid, values, t_hours, q_idx, f)
    bid_delta = np.inf
    ask_delta = np.inf
    base_delta = 1.0 / intensity_k
    q_step = q_grid[1] - q_grid[0]

    if q_idx > 0:
        ask_jump = _theta_interp_q_idx(t_grid, f_grid, values, t_hours, q_idx - 1, f) - theta_now
        ask_delta = base_delta - ask_jump / q_step
        if ask_delta < min_delta:
            ask_delta = min_delta
    if q_idx < values.shape[1] - 1:
        bid_jump = _theta_interp_q_idx(t_grid, f_grid, values, t_hours, q_idx + 1, f) - theta_now
        bid_delta = base_delta - bid_jump / q_step
        if bid_delta < min_delta:
            bid_delta = min_delta
    return float(bid_delta), float(ask_delta)


def _validate_params(params: HJBFDSolverParams) -> None:
    if params.horizon_hours <= 0.0:
        raise ValueError("horizon_hours must be positive")
    if params.q_min >= params.q_max:
        raise ValueError("q_min must be less than q_max")
    if params.q_step <= 0.0:
        raise ValueError("q_step must be positive")
    if not np.isclose(round((params.q_max - params.q_min) / params.q_step), (params.q_max - params.q_min) / params.q_step):
        raise ValueError("q_step must evenly divide q_max - q_min")
    if params.f_min >= params.f_max:
        raise ValueError("f_min must be less than f_max")
    if params.n_f < 3:
        raise ValueError("n_f must be at least 3")
    if params.n_t < 2:
        raise ValueError("n_t must be at least 2")
    if params.sigma_f < 0.0:
        raise ValueError("sigma_f must be non-negative")
    if params.fill_intensity < 0.0:
        raise ValueError("fill_intensity must be non-negative")
    if params.intensity_k <= 0.0:
        raise ValueError("intensity_k must be positive")
    if params.terminal_penalty < 0.0:
        raise ValueError("terminal_penalty must be non-negative")
    if params.running_penalty < 0.0:
        raise ValueError("running_penalty must be non-negative")
    if params.min_delta < 0.0:
        raise ValueError("min_delta must be non-negative")
