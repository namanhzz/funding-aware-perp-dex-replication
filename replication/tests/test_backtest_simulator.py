import numpy as np
import pandas as pd
import pytest

from perp_mm_funding.backtest.benchmarks import BenchmarkDeltas
from perp_mm_funding.backtest.simulator import BacktestConfig, run_event_backtest


def test_spot_hedge_columns_are_recorded():
    price = pd.DataFrame(
        {
            "open_time": pd.date_range("2024-01-01", periods=3, freq="1min", tz="UTC"),
            "close": [100.0, 101.0, 102.0],
        }
    )
    funding = pd.DataFrame({"time": [pd.Timestamp("2024-01-01", tz="UTC")], "funding_rate": [0.0]})

    def policy(_t, _q, _f, _mid):
        return BenchmarkDeltas(bid_delta=0.0, ask_delta=1000.0)

    events = run_event_backtest(
        price,
        funding,
        policy,
        BacktestConfig(lambda_base=1e9, intensity_k=1.0, quote_size=1.0, hedge_spot=True, seed=1),
    )
    assert "hedge_inventory" in events.columns
    assert events["hedge_inventory"].iloc[-1] == -events["inventory"].iloc[-1]


def test_l2_panel_time_mid_input_is_supported():
    price = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=3, freq="1min", tz="UTC"),
            "coin": ["ETH", "ETH", "ETH"],
            "mid": [100.0, 101.0, 102.0],
        }
    )
    funding = pd.DataFrame({"time": [pd.Timestamp("2024-01-01", tz="UTC")], "funding_rate": [0.0]})

    def policy(_t, _q, _f, _mid):
        return BenchmarkDeltas(bid_delta=1000.0, ask_delta=1000.0)

    events = run_event_backtest(price, funding, policy, BacktestConfig(lambda_base=0.0, intensity_k=1.0))

    assert list(events["mid"]) == [100.0, 101.0, 102.0]


def test_maker_fees_and_execution_costs_are_debited_and_recorded():
    price = pd.DataFrame(
        {
            "open_time": pd.date_range("2024-01-01", periods=2, freq="1min", tz="UTC"),
            "close": [100.0, 100.0],
        }
    )
    funding = pd.DataFrame({"time": [pd.Timestamp("2024-01-01", tz="UTC")], "funding_rate": [0.0]})

    def policy(_t, _q, _f, _mid):
        return BenchmarkDeltas(bid_delta=0.0, ask_delta=1000.0)

    events = run_event_backtest(
        price,
        funding,
        policy,
        BacktestConfig(
            lambda_base=1e9,
            intensity_k=1.0,
            quote_size=1.0,
            inventory_limit=2.0,
            maker_fee_rate=0.001,
            adverse_selection_bps=1.0,
            seed=1,
        ),
    )

    assert events["bid_fill"].sum() == 2
    assert events["trading_fee"].sum() == 0.2
    assert events["execution_cost"].sum() == 0.02
    assert events["turnover"].sum() == 200.0
    assert np.isclose(events["equity"].iloc[-1], -0.22)


def test_zero_fill_probability_scale_blocks_all_fills():
    price = pd.DataFrame(
        {
            "open_time": pd.date_range("2024-01-01", periods=2, freq="1min", tz="UTC"),
            "close": [100.0, 100.0],
        }
    )
    funding = pd.DataFrame({"time": [pd.Timestamp("2024-01-01", tz="UTC")], "funding_rate": [0.0]})

    def policy(_t, _q, _f, _mid):
        return BenchmarkDeltas(bid_delta=0.0, ask_delta=0.0)

    events = run_event_backtest(
        price,
        funding,
        policy,
        BacktestConfig(lambda_base=1e9, intensity_k=1.0, fill_probability_scale=0.0),
    )

    assert not events["bid_fill"].any()
    assert not events["ask_fill"].any()


def test_simulation_frequency_forward_fills_price_grid():
    price = pd.DataFrame(
        {
            "time": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"]
            ),
            "mid": [100.0, 101.0],
        }
    )
    funding = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01T00:00:00Z"]),
            "funding_rate": [0.0],
        }
    )

    events = run_event_backtest(
        price,
        funding,
        lambda *_: BenchmarkDeltas(bid_delta=1_000.0, ask_delta=1_000.0),
        BacktestConfig(simulation_frequency="30min", seed=1),
    )

    assert len(events) == 3
    assert events["mid"].tolist() == [100.0, 100.0, 101.0]


def test_candle_close_is_not_available_at_open_time():
    price = pd.DataFrame(
        {
            "open_time": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"]
            ),
            "close_time": pd.to_datetime(
                ["2026-01-01T00:14:59.999Z", "2026-01-01T00:29:59.999Z"]
            ),
            "close": [100.0, 101.0],
        }
    )
    funding = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01T00:00:00Z"]),
            "funding_rate": [0.0],
        }
    )

    events = run_event_backtest(
        price,
        funding,
        lambda *_: BenchmarkDeltas(bid_delta=1_000.0, ask_delta=1_000.0),
        BacktestConfig(simulation_frequency="1min", seed=1),
    )

    assert events["time"].iloc[0] == pd.Timestamp("2026-01-01T00:15:00Z")
    assert events["mid"].iloc[0] == 100.0


def test_continuous_funding_accrues_by_elapsed_fraction():
    price = pd.DataFrame(
        {
            "open_time": pd.date_range("2026-01-01", periods=61, freq="1min", tz="UTC"),
            "close": np.full(61, 100.0),
        }
    )
    funding = pd.DataFrame(
        {
            "time": [pd.Timestamp("2026-01-01", tz="UTC")],
            "funding_rate": [0.01],
        }
    )
    policy = lambda *_: BenchmarkDeltas(bid_delta=1_000.0, ask_delta=1_000.0)

    events = run_event_backtest(
        price,
        funding,
        policy,
        BacktestConfig(
            initial_inventory=2.0,
            inventory_limit=2.0,
            lambda_base=0.0,
            funding_accrual_mode="continuous",
        ),
    )

    assert events["funding_payment"].sum() == pytest.approx(2.0)
    assert events["equity"].iloc[-1] == pytest.approx(198.0)


def test_invalid_funding_accrual_mode_is_rejected():
    price = pd.DataFrame(
        {
            "open_time": pd.date_range("2026-01-01", periods=2, freq="1min", tz="UTC"),
            "close": [100.0, 100.0],
        }
    )
    funding = pd.DataFrame(
        {"time": [pd.Timestamp("2026-01-01", tz="UTC")], "funding_rate": [0.0]}
    )
    with pytest.raises(ValueError, match="funding_accrual_mode"):
        run_event_backtest(
            price,
            funding,
            lambda *_: BenchmarkDeltas(bid_delta=1.0, ask_delta=1.0),
            BacktestConfig(funding_accrual_mode="invalid"),
        )
