from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from perp_mm_funding.backtest.accounting import Account
from perp_mm_funding.backtest.benchmarks import BenchmarkDeltas
from perp_mm_funding.backtest.fills import simulate_fill


QuotePolicy = Callable[[float, float, float, float], BenchmarkDeltas]


@dataclass(slots=True)
class BacktestConfig:
    initial_cash: float = 0.0
    initial_inventory: float = 0.0
    inventory_limit: float = 10.0
    lambda_base: float = 6.0
    intensity_k: float = 90.0
    quote_size: float = 1.0
    tick_size: float = 0.01
    seed: int = 7
    hedge_spot: bool = False
    maker_fee_rate: float = 0.0
    adverse_selection_bps: float = 0.0
    fill_probability_scale: float = 1.0
    simulation_frequency: str | None = None
    funding_accrual_mode: str = "hourly_boundary"


def _prepare_market(
    price_frame: pd.DataFrame,
    funding_frame: pd.DataFrame,
    simulation_frequency: str | None = None,
) -> pd.DataFrame:
    prices = price_frame.copy()
    if "close_time" in prices.columns:
        prices["time"] = pd.to_datetime(prices["close_time"], utc=True).dt.ceil("1min")
    elif "open_time" in prices.columns:
        prices = prices.rename(columns={"open_time": "time"})
    if "mid" in prices.columns and "close" not in prices.columns:
        prices = prices.rename(columns={"mid": "close"})
    if "time" not in prices.columns or "close" not in prices.columns:
        raise ValueError("price_frame must contain open_time/close or time/mid columns")
    prices["time"] = pd.to_datetime(prices["time"], utc=True)
    prices = prices[["time", "close"]].sort_values("time").drop_duplicates("time", keep="last")
    if simulation_frequency:
        simulation_index = pd.date_range(
            start=prices["time"].iloc[0],
            end=prices["time"].iloc[-1],
            freq=simulation_frequency,
        )
        prices = (
            prices.set_index("time")
            .reindex(simulation_index)
            .ffill()
            .rename_axis("time")
            .reset_index()
        )
    funding = funding_frame[["time", "funding_rate"]].copy()
    funding["time"] = pd.to_datetime(funding["time"], utc=True)
    funding = funding.sort_values("time")
    merged = pd.merge_asof(prices, funding, on="time", direction="backward")
    merged["funding_rate"] = merged["funding_rate"].fillna(0.0)
    return merged.dropna(subset=["close"]).reset_index(drop=True)


def run_event_backtest(
    price_frame: pd.DataFrame,
    funding_frame: pd.DataFrame,
    policy: QuotePolicy,
    config: BacktestConfig,
) -> pd.DataFrame:
    if config.fill_probability_scale < 0.0:
        raise ValueError("fill_probability_scale must be non-negative")
    if config.adverse_selection_bps < 0.0:
        raise ValueError("adverse_selection_bps must be non-negative")
    if config.funding_accrual_mode not in {"hourly_boundary", "continuous"}:
        raise ValueError(
            "funding_accrual_mode must be `hourly_boundary` or `continuous`"
        )
    market = _prepare_market(price_frame, funding_frame, config.simulation_frequency)
    if len(market) < 2:
        raise ValueError("Need at least two market rows")

    rng = np.random.default_rng(config.seed)
    account = Account(config.initial_cash, config.initial_inventory)
    hedge_cash = 0.0
    hedge_inventory = 0.0
    row_count = len(market)
    times = market["time"].reset_index(drop=True)
    mids = market["close"].to_numpy(dtype=float)
    funding_rates = market["funding_rate"].to_numpy(dtype=float)
    t_hours = (times - times.iloc[0]).dt.total_seconds().to_numpy(dtype=float) / 3600.0
    dt_hours = times.diff().dt.total_seconds().to_numpy(dtype=float) / 3600.0
    dt_hours[0] = 1.0 / 60.0
    dt_hours[1:] = np.maximum(dt_hours[1:], 0.0)
    funding_hours = times.dt.floor("1h")
    funding_boundaries = np.zeros(row_count, dtype=bool)
    funding_boundaries[1:] = (
        funding_hours.iloc[1:].reset_index(drop=True)
        > funding_hours.iloc[:-1].reset_index(drop=True)
    ).to_numpy()

    bid_deltas = np.empty(row_count, dtype=float)
    ask_deltas = np.empty(row_count, dtype=float)
    bid_fills = np.zeros(row_count, dtype=bool)
    ask_fills = np.zeros(row_count, dtype=bool)
    cash_values = np.empty(row_count, dtype=float)
    inventory_values = np.empty(row_count, dtype=float)
    hedge_cash_values = np.empty(row_count, dtype=float)
    hedge_inventory_values = np.empty(row_count, dtype=float)
    funding_payments = np.zeros(row_count, dtype=float)
    trading_fees = np.zeros(row_count, dtype=float)
    execution_costs = np.zeros(row_count, dtype=float)
    turnovers = np.zeros(row_count, dtype=float)
    equity_values = np.empty(row_count, dtype=float)

    def rebalance_hedge(mid_price: float) -> None:
        nonlocal hedge_cash, hedge_inventory
        if not config.hedge_spot:
            return
        target_inventory = -account.inventory
        delta = target_inventory - hedge_inventory
        hedge_cash -= delta * mid_price
        hedge_inventory = target_inventory

    for index in range(row_count):
        mid = mids[index]
        funding_rate = funding_rates[index]
        deltas = policy(t_hours[index], account.inventory, funding_rate, mid)
        bid_deltas[index] = deltas.bid_delta
        ask_deltas[index] = deltas.ask_delta
        bid_fill = False
        ask_fill = False
        trading_fee = 0.0
        execution_cost = 0.0
        turnover = 0.0
        effective_lambda = config.lambda_base * config.fill_probability_scale

        if account.inventory + config.quote_size <= config.inventory_limit:
            bid_fill = simulate_fill(
                rng,
                effective_lambda,
                config.intensity_k,
                deltas.bid_delta,
                dt_hours[index],
            )
            if bid_fill:
                fill_price = mid - deltas.bid_delta
                account.buy_fill(fill_price, config.quote_size)
                notional = abs(fill_price * config.quote_size)
                turnover += notional
                trading_fee += account.apply_trade_cost(notional, config.maker_fee_rate)
                execution_cost += account.apply_trade_cost(notional, config.adverse_selection_bps * 1e-4)
                rebalance_hedge(mid)
        if account.inventory - config.quote_size >= -config.inventory_limit:
            ask_fill = simulate_fill(
                rng,
                effective_lambda,
                config.intensity_k,
                deltas.ask_delta,
                dt_hours[index],
            )
            if ask_fill:
                fill_price = mid + deltas.ask_delta
                account.sell_fill(fill_price, config.quote_size)
                notional = abs(fill_price * config.quote_size)
                turnover += notional
                trading_fee += account.apply_trade_cost(notional, config.maker_fee_rate)
                execution_cost += account.apply_trade_cost(notional, config.adverse_selection_bps * 1e-4)
                rebalance_hedge(mid)

        funding_payment = 0.0
        if config.funding_accrual_mode == "hourly_boundary" and funding_boundaries[index]:
            funding_payment = account.apply_funding(mid, funding_rate)
        elif config.funding_accrual_mode == "continuous" and index > 0:
            funding_payment = account.apply_funding(
                mid,
                funding_rate,
                dt_hours[index],
            )

        perp_equity = account.mark_to_market(mid)
        hedge_equity = hedge_cash + hedge_inventory * mid
        bid_fills[index] = bid_fill
        ask_fills[index] = ask_fill
        cash_values[index] = account.cash
        inventory_values[index] = account.inventory
        hedge_cash_values[index] = hedge_cash
        hedge_inventory_values[index] = hedge_inventory
        funding_payments[index] = funding_payment
        trading_fees[index] = trading_fee
        execution_costs[index] = execution_cost
        turnovers[index] = turnover
        equity_values[index] = perp_equity + hedge_equity

    return pd.DataFrame(
        {
            "time": times,
            "mid": mids,
            "funding_rate": funding_rates,
            "bid_delta": bid_deltas,
            "ask_delta": ask_deltas,
            "bid_fill": bid_fills,
            "ask_fill": ask_fills,
            "cash": cash_values,
            "inventory": inventory_values,
            "hedge_cash": hedge_cash_values,
            "hedge_inventory": hedge_inventory_values,
            "funding_payment": funding_payments,
            "trading_fee": trading_fees,
            "execution_cost": execution_costs,
            "turnover": turnovers,
            "equity": equity_values,
        }
    )
