import pytest

from perp_mm_funding.run_variant_sweep import (
    VariantTrial,
    _aggregate_seed_results,
    _grid_trials,
    _select_best_by_variant,
)


def test_grid_trials_builds_cartesian_product_with_stable_names():
    trials = _grid_trials(
        {
            "risk_calibrated": {
                "risk_widening": [0.5, 1.0],
                "risk_skew_cap": [0.25],
            }
        }
    )

    assert trials == [
        VariantTrial(
            name="risk_calibrated__risk_widening=0p5__risk_skew_cap=0p25",
            variant="risk_calibrated",
            params={"risk_widening": 0.5, "risk_skew_cap": 0.25},
        ),
        VariantTrial(
            name="risk_calibrated__risk_widening=1__risk_skew_cap=0p25",
            variant="risk_calibrated",
            params={"risk_widening": 1.0, "risk_skew_cap": 0.25},
        ),
    ]


def test_select_best_by_variant_excludes_baseline_and_keeps_top_n():
    results = [
        {"variant": "pure_as", "trial": "pure_as", "final_equity": 10.0},
        {"variant": "carry_overlay", "trial": "bad_carry", "final_equity": 11.0},
        {"variant": "carry_overlay", "trial": "good_carry", "final_equity": 12.0},
        {"variant": "hjb_fd", "trial": "hjb", "final_equity": 9.0},
    ]

    selected = _select_best_by_variant(results, metric="final_equity", top_n=1)

    assert selected == [
        {"variant": "carry_overlay", "trial": "good_carry", "final_equity": 12.0},
        {"variant": "hjb_fd", "trial": "hjb", "final_equity": 9.0},
    ]


def test_aggregate_seed_results_keeps_mean_and_std():
    trial = VariantTrial(name="risk", variant="risk_calibrated", params={"risk_widening": 1.0})
    result = _aggregate_seed_results(
        trial,
        [
            {
                "seed": 1,
                "sharpe_hourly": 1.0,
                "mean_pnl_per_day": 2.0,
                "max_drawdown": -1.0,
                "inventory_rms": 3.0,
                "realized_funding_cost": -4.0,
                "fill_rate": 0.1,
                "worst_single_hour": -5.0,
                "final_equity": 10.0,
            },
            {
                "seed": 2,
                "sharpe_hourly": 3.0,
                "mean_pnl_per_day": 4.0,
                "max_drawdown": -3.0,
                "inventory_rms": 5.0,
                "realized_funding_cost": -6.0,
                "fill_rate": 0.3,
                "worst_single_hour": -7.0,
                "final_equity": 14.0,
            },
        ],
    )

    assert result["final_equity"] == 12.0
    assert result["final_equity_std"] == pytest.approx(2.8284271247461903)
    assert result["seeds"] == [1, 2]
