from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.stattools import acf, adfuller, pacf


@dataclass(slots=True)
class ADFResult:
    statistic: float
    pvalue: float
    used_lag: int
    n_obs: int
    critical_values: dict[str, float]


def clean_numeric(values: Iterable[float]) -> pd.Series:
    series = pd.Series(values, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    return series.reset_index(drop=True)


def run_adf(values: Iterable[float], autolag: str = "AIC") -> ADFResult:
    series = clean_numeric(values)
    if len(series) < 20:
        raise ValueError("ADF requires at least 20 observations")
    statistic, pvalue, used_lag, n_obs, critical_values, _ = adfuller(series.to_numpy(), autolag=autolag)
    return ADFResult(
        statistic=float(statistic),
        pvalue=float(pvalue),
        used_lag=int(used_lag),
        n_obs=int(n_obs),
        critical_values={key: float(value) for key, value in critical_values.items()},
    )


def rolling_adf(values: Iterable[float], window: int) -> pd.DataFrame:
    series = clean_numeric(values)
    rows = []
    if len(series) < window:
        result = run_adf(series)
        return pd.DataFrame(
            [
                {
                    "start": 0,
                    "end": len(series),
                    "statistic": result.statistic,
                    "pvalue": result.pvalue,
                    "used_lag": result.used_lag,
                    "n_obs": result.n_obs,
                }
            ]
        )
    for start in range(0, len(series) - window + 1):
        end = start + window
        try:
            result = run_adf(series.iloc[start:end])
            rows.append(
                {
                    "start": start,
                    "end": end,
                    "statistic": result.statistic,
                    "pvalue": result.pvalue,
                    "used_lag": result.used_lag,
                    "n_obs": result.n_obs,
                }
            )
        except ValueError:
            continue
    return pd.DataFrame(rows)


def acf_pacf_table(values: Iterable[float], nlags: int = 48) -> pd.DataFrame:
    series = clean_numeric(values)
    max_lags = min(nlags, max(1, len(series) // 2 - 1))
    acf_values = acf(series.to_numpy(), nlags=max_lags, fft=True)
    pacf_values = pacf(series.to_numpy(), nlags=max_lags, method="ywm")
    return pd.DataFrame({"lag": range(max_lags + 1), "acf": acf_values, "pacf": pacf_values})


def ar1_half_life_hours(values: Iterable[float], step_hours: float = 1.0) -> float:
    series = clean_numeric(values)
    if len(series) < 10:
        raise ValueError("At least ten observations are required")
    prev = series.iloc[:-1].to_numpy()
    nxt = series.iloc[1:].to_numpy()
    design = np.column_stack([np.ones_like(prev), prev])
    _, phi = np.linalg.lstsq(design, nxt, rcond=None)[0]
    if not np.isfinite(phi) or phi <= 0 or phi >= 1:
        return float("inf")
    return float(-np.log(2.0) / np.log(phi) * step_hours)


def residual_summary(residuals: Iterable[float]) -> dict[str, float]:
    series = clean_numeric(residuals)
    if len(series) < 8:
        raise ValueError("At least eight residuals are required")
    jb_stat, jb_pvalue = stats.jarque_bera(series.to_numpy())
    return {
        "mean": float(series.mean()),
        "std": float(series.std(ddof=1)),
        "skew": float(stats.skew(series.to_numpy(), bias=False)),
        "excess_kurtosis": float(stats.kurtosis(series.to_numpy(), fisher=True, bias=False)),
        "jarque_bera_stat": float(jb_stat),
        "jarque_bera_pvalue": float(jb_pvalue),
    }
