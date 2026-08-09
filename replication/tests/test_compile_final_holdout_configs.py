from perp_mm_funding.compile_final_holdout_configs import _scenario_config


def test_scenario_config_carries_selected_parameters_and_costs():
    design = {
        "assets": ["ETH"],
        "holdout_files": {"ETH": {"price_path": "price.parquet", "funding_path": "funding.parquet"}},
        "asset_base_configs": {"ETH": "base.yaml"},
        "final_holdout_start_time": "start",
        "final_holdout_end_time": "end",
    }
    selections = {
        "ETH": {
            "risk_matched_as": {"params": {"terminal_penalty": 1.0}},
            "selected_hjb": {"params": {"terminal_penalty": 2.0}},
        }
    }

    result = _scenario_config(
        design,
        selections,
        maker_fee_rate=0.00015,
        adverse_selection_bps=0.5,
        fill_probability_scale=0.5,
    )

    asset = result["assets"][0]
    assert asset["base_overrides"]["maker_fee_rate"] == 0.00015
    assert asset["base_overrides"]["adverse_selection_bps"] == 0.5
    assert asset["trials"][2]["params"]["terminal_penalty"] == 2.0
