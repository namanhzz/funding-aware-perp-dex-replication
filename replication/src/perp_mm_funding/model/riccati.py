from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp


@dataclass(slots=True)
class RiccatiParams:
    horizon_hours: float
    kappa: float
    theta_bar: float
    sigma_f: float
    terminal_penalty: float
    running_penalty: float


@dataclass(slots=True)
class QuadraticCoefficients:
    t_grid: np.ndarray
    values: np.ndarray

    def at(self, t_hours: float) -> np.ndarray:
        if t_hours <= self.t_grid[0]:
            return self.values[:, 0].copy()
        if t_hours >= self.t_grid[-1]:
            return self.values[:, -1].copy()
        return np.array([np.interp(t_hours, self.t_grid, row) for row in self.values])

    def theta(self, t_hours: float, q: float, f: float) -> float:
        a0, a1, a2, a3, a4, a5 = self.at(t_hours)
        return float(a0 + a1 * f + a2 * f**2 + a3 * q**2 + a4 * q * f + a5 * q)


def _coefficient_rhs(_t: float, y: np.ndarray, params: RiccatiParams) -> np.ndarray:
    a0, a1, a2, _a3, a4, _a5 = y
    return np.array(
        [
            -(params.kappa * params.theta_bar * a1 + params.sigma_f**2 * a2),
            params.kappa * a1 - 2.0 * params.kappa * params.theta_bar * a2,
            2.0 * params.kappa * a2,
            params.running_penalty,
            params.kappa * a4 + 1.0,
            -params.kappa * params.theta_bar * a4,
        ],
        dtype=float,
    )


def solve_lq_funding_coefficients(params: RiccatiParams, n_grid: int = 500) -> QuadraticCoefficients:
    """Solve the quadratic funding-inventory value term.

    This is the linear-quadratic core implied by the funding cost and inventory
    penalties. Arrival Hamiltonian terms are applied by the quote layer. The
    mandatory q*f coupling is captured by coefficient a4.
    """

    terminal = np.array([0.0, 0.0, 0.0, -params.terminal_penalty, 0.0, 0.0], dtype=float)
    solution = solve_ivp(
        fun=lambda t, y: _coefficient_rhs(t, y, params),
        t_span=(params.horizon_hours, 0.0),
        y0=terminal,
        dense_output=True,
        rtol=1e-9,
        atol=1e-11,
    )
    if not solution.success:
        raise RuntimeError(f"Riccati solve failed: {solution.message}")
    t_grid = np.linspace(0.0, params.horizon_hours, n_grid)
    values = solution.sol(t_grid)
    return QuadraticCoefficients(t_grid=t_grid, values=values)

