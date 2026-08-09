from __future__ import annotations

from perp_mm_funding.compile_risk_frontier_config import compile_frontier_config


def _candidate(variant: str, rms: float, equity: float, alpha: float, phi: float):
    return {
        "variant": variant,
        "inventory_rms": rms,
        "final_equity": equity,
        "params": {"terminal_penalty": alpha, "running_penalty": phi},
    }


def test_compile_frontier_uses_development_efficient_points_and_nearest_as():
    hjb_low = _candidate("hjb_fd", 10.0, 5.0, 0.00025, 0.2)
    hjb_dominated = _candidate("hjb_fd", 12.0, 4.0, 0.00025, 0.1)
    hjb_selected = _candidate("hjb_fd", 15.0, 8.0, 0.00025, 0.05)
    as_low = _candidate("pure_as", 10.5, 3.0, 0.1, 0.01)
    as_high = _candidate("pure_as", 14.5, 6.0, 0.01, 0.001)
    selection = {
        "assets": [
            {
                "asset": "SOL",
                "selected_hjb": hjb_selected,
                "hjb_candidates": [hjb_low, hjb_dominated, hjb_selected],
                "as_candidates": [as_low, as_high],
            }
        ]
    }

    config = compile_frontier_config(selection, price_path="price.parquet", funding_path="funding.parquet")

    assert len(config["frontier_pairs"]) == 2
    assert config["frontier_selected_hjb_trial"].endswith("0p05")
    assert config["frontier_selected_as_trial"] == config["frontier_pairs"][1]["as_trial"]
    assert config["assets"][0]["base_overrides"]["price_path"] == "price.parquet"
