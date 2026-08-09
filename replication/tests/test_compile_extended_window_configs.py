from perp_mm_funding.compile_extended_window_configs import extended_window_config


def test_extended_window_config_reuses_trials_and_repoints_data() -> None:
    source = {
        "assets": [
            {
                "asset": "SOL",
                "base_overrides": {"price_path": "old.parquet"},
                "trials": [{"name": "fixed", "variant": "hjb_fd", "params": {"x": 1}}],
            }
        ]
    }
    result = extended_window_config(
        source,
        start_time="2026-01-15T00:00:00Z",
        end_time="2026-07-31T23:59:00Z",
        seed_count=3,
        jobs=2,
        analysis_label="diagnostic",
    )

    assert result["seeds"] == [1, 2, 3]
    assert result["assets"][0]["trials"] == source["assets"][0]["trials"]
    assert result["assets"][0]["base_overrides"]["price_path"].endswith(
        "sol-causal-intrabar-bridge-1m-extended-20260115-20260731.parquet"
    )
    assert source["assets"][0]["base_overrides"]["price_path"] == "old.parquet"
