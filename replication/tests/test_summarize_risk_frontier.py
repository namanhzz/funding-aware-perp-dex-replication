from __future__ import annotations

from perp_mm_funding.summarize_risk_frontier import summarize_frontier


def _seed(seed: int, equity: float):
    return {
        "seed": seed,
        "final_equity": equity,
        "complete_week_pnl": {"0": equity},
        "complete_day_pnl": {"0": equity},
    }


def test_frontier_summary_pairs_named_policies():
    payload = {
        "config": "frontier.yaml",
        "frontier_pairs": [{"hjb_trial": "hjb", "as_trial": "as"}],
        "assets": [
            {
                "results": [
                    {"trial": "hjb", "inventory_rms": 10.5, "final_equity": 12.0, "per_seed_results": [_seed(1, 11.0), _seed(2, 13.0)]},
                    {"trial": "as", "inventory_rms": 10.0, "final_equity": 10.0, "per_seed_results": [_seed(1, 9.0), _seed(2, 11.0)]},
                ]
            }
        ],
    }

    summary = summarize_frontier(payload)

    assert summary["comparable_risk_points"] == 1
    assert summary["positive_comparable_risk_points"] == 1
    assert summary["rows"][0]["paired_delta"] == 2.0
