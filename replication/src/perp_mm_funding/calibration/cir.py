from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


@dataclass(slots=True)
class ShiftedCIRFit:
    shift: float
    kappa: float
    theta: float
    sigma: float
    warning: str | None = None

    def as_dict(self) -> dict[str, float | str | None]:
        return {
            "shift": self.shift,
            "kappa": self.kappa,
            "theta": self.theta,
            "sigma": self.sigma,
            "warning": self.warning,
        }


def fit_shifted_cir_moments(values: Iterable[float], dt_hours: float = 1.0, eps: float = 1e-9) -> ShiftedCIRFit:
    x_raw = np.asarray(list(values), dtype=float)
    x_raw = x_raw[np.isfinite(x_raw)]
    if len(x_raw) < 10:
        raise ValueError("At least ten observations are required")

    minimum = float(np.min(x_raw))
    shift = 0.0 if minimum > 0 else -minimum + eps
    x = x_raw + shift
    prev = x[:-1]
    nxt = x[1:]
    design = np.column_stack([np.ones_like(prev), prev])
    intercept, phi = np.linalg.lstsq(design, nxt, rcond=None)[0]
    phi = float(np.clip(phi, 1e-6, 0.999999))
    kappa = float(-np.log(phi) / dt_hours)
    theta = float(intercept / (1.0 - phi))
    resid = nxt - (intercept + phi * prev)
    scaled_var = np.mean((resid**2) / np.maximum(prev, eps))
    sigma = float(np.sqrt(max(scaled_var / dt_hours, eps)))
    warning = None
    if shift > 0:
        warning = "Funding can be negative; this is a shifted-CIR robustness diagnostic, not a literal CIR fit."
    return ShiftedCIRFit(shift=shift, kappa=kappa, theta=theta, sigma=sigma, warning=warning)

