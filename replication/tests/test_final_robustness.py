import pytest
import pandas as pd

from perp_mm_funding.run_final_robustness import (
    _add_paired_vs_baseline,
    _complete_day_pnl,
    _complete_week_pnl,
    _hac_mean_ci,
    _moving_block_bootstrap_mean_interval,
    _asset_base_config,
    _mean_std_ci,
    _mean_std_t_ci,
    _resolve_jobs,
    _seed_chunks,
)


def test_mean_std_ci_uses_95_percent_normal_interval():
    mean, std, ci95 = _mean_std_ci([1.0, 2.0, 3.0])

    assert mean == 2.0
    assert std == pytest.approx(1.0)
    assert ci95 == pytest.approx(1.96 / (3**0.5))


def test_mean_std_t_ci_uses_student_t_interval():
    mean, std, ci95 = _mean_std_t_ci([1.0, 2.0, 3.0])

    assert mean == 2.0
    assert std == pytest.approx(1.0)
    assert ci95 == pytest.approx(4.3026527299 / (3**0.5))


def test_add_paired_vs_baseline_computes_win_rate_and_delta():
    results = [
        {
            "variant": "pure_as",
            "per_seed_results": [
                {"seed": 1, "final_equity": 10.0},
                {"seed": 2, "final_equity": 20.0},
            ],
        },
        {
            "variant": "hjb_fd",
            "per_seed_results": [
                {"seed": 1, "final_equity": 12.0},
                {"seed": 2, "final_equity": 19.0},
            ],
        },
    ]

    _add_paired_vs_baseline(results)

    assert results[1]["delta_final_equity_vs_baseline"] == 0.5
    assert results[1]["win_rate_vs_baseline"] == 0.5


def test_add_paired_vs_baseline_keeps_scaled_as_separate_from_baseline():
    results = [
        {
            "variant": "pure_as",
            "per_seed_results": [{"seed": 1, "final_equity": 10.0}],
        },
        {
            "variant": "pure_as_scaled",
            "per_seed_results": [{"seed": 1, "final_equity": 15.0}],
        },
    ]

    _add_paired_vs_baseline(results)

    assert results[1]["delta_final_equity_vs_baseline"] == 5.0
    assert results[1]["win_rate_vs_baseline"] == 1.0


def test_add_paired_vs_named_baseline_uses_distinct_output_fields():
    results = [
        {
            "trial": "as_default",
            "variant": "pure_as",
            "per_seed_results": [{"seed": 1, "final_equity": 10.0}],
        },
        {
            "trial": "as_matched",
            "variant": "pure_as",
            "per_seed_results": [{"seed": 1, "final_equity": 12.0}],
        },
        {
            "trial": "hjb",
            "variant": "hjb_fd",
            "per_seed_results": [{"seed": 1, "final_equity": 15.0}],
        },
    ]

    _add_paired_vs_baseline(results, baseline_trial="as_matched", field_suffix="risk_matched_as")

    assert results[2]["delta_final_equity_vs_risk_matched_as"] == 3.0


def test_complete_week_pnl_excludes_short_tail_block():
    times = pd.date_range("2026-01-01", periods=15 * 24, freq="1h", tz="UTC")
    events = pd.DataFrame({"time": times, "equity": range(len(times))})

    weekly = _complete_week_pnl(events, initial_equity=0.0)

    assert list(weekly) == ["0", "1"]


def test_complete_day_pnl_excludes_short_tail_block():
    times = pd.date_range("2026-01-01", periods=50, freq="1h", tz="UTC")
    events = pd.DataFrame({"time": times, "equity": range(len(times))})

    daily = _complete_day_pnl(events, initial_equity=0.0)

    assert list(daily) == ["0", "1"]


def test_hac_mean_ci_handles_serially_constant_values():
    mean, standard_error, half_width = _hac_mean_ci([2.0] * 20, max_lag=7)

    assert mean == 2.0
    assert standard_error == 0.0
    assert half_width == 0.0


def test_moving_block_bootstrap_interval_is_deterministic():
    first = _moving_block_bootstrap_mean_interval(list(range(20)), replications=100)
    second = _moving_block_bootstrap_mean_interval(list(range(20)), replications=100)

    assert first == second
    assert first[0] < first[1]


def test_resolve_jobs_caps_at_seed_count():
    assert _resolve_jobs(99, seed_count=3) == 3
    assert _resolve_jobs(1, seed_count=3) == 1


def test_seed_chunks_cover_each_seed_once():
    chunks = _seed_chunks([1, 2, 3, 4, 5], jobs=2)

    assert sorted(seed for chunk in chunks for seed in chunk) == [1, 2, 3, 4, 5]
    assert len(chunks) == 2


def test_asset_base_config_applies_overrides_and_global_window(tmp_path):
    config_path = tmp_path / "base.yaml"
    config_path.write_text(
        "\n".join(
            [
                "coin: ETH",
                "fill_intensity_path: old.json",
                "start_time: old-start",
                "end_time: old-end",
            ]
        ),
        encoding="utf-8",
    )

    cfg = _asset_base_config(
        {
            "base_config": str(config_path),
            "base_overrides": {"fill_intensity_path": "new.json"},
        },
        {"start_time": "2025-01-01T00:00:00Z", "end_time": "2025-01-02T00:00:00Z"},
    )

    assert cfg["fill_intensity_path"] == "new.json"
    assert cfg["start_time"] == "2025-01-01T00:00:00Z"
    assert cfg["end_time"] == "2025-01-02T00:00:00Z"
