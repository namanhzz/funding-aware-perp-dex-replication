from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity - running_max
    return float(drawdown.min())


def sharpe_ratio(returns: pd.Series, periods_per_year: float) -> float:
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 2:
        return float("nan")
    std = returns.std(ddof=1)
    if std == 0 or not np.isfinite(std):
        return float("nan")
    return float(np.sqrt(periods_per_year) * returns.mean() / std)


def summarize_backtest(events: pd.DataFrame) -> dict[str, float]:
    if events.empty:
        raise ValueError("events frame is empty")
    equity = events["equity"]
    pnl = equity.diff().fillna(0.0)
    hourly = events.set_index("time")["equity"].diff().resample("1h").sum().dropna()
    days = max((events["time"].max() - events["time"].min()).total_seconds() / 86_400.0, 1.0)
    quotes = max(float(len(events) * 2), 1.0)
    fills = float(events["bid_fill"].sum() + events["ask_fill"].sum())
    turnover = float(events["turnover"].sum()) if "turnover" in events else float("nan")
    trading_fees = float(events["trading_fee"].sum()) if "trading_fee" in events else 0.0
    execution_cost = float(events["execution_cost"].sum()) if "execution_cost" in events else 0.0
    net_pnl = float(equity.iloc[-1] - equity.iloc[0])
    return {
        "sharpe_hourly": sharpe_ratio(hourly, periods_per_year=24.0 * 365.0),
        "mean_pnl_per_day": float((equity.iloc[-1] - equity.iloc[0]) / days),
        "max_drawdown": max_drawdown(equity),
        "inventory_rms": float(np.sqrt(np.mean(events["inventory"].to_numpy() ** 2))),
        "realized_funding_cost": float(events["funding_payment"].sum()),
        "realized_trading_fees": trading_fees,
        "realized_execution_cost": execution_cost,
        "turnover": turnover,
        "fill_count": fills,
        "net_pnl_bps_turnover": float(1e4 * net_pnl / turnover) if turnover > 0.0 else float("nan"),
        "fill_rate": fills / quotes,
        "worst_single_hour": float(hourly.min()) if len(hourly) else float(pnl.min()),
        "final_equity": float(equity.iloc[-1]),
    }
