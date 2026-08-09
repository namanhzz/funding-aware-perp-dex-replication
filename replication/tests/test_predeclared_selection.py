from perp_mm_funding.run_predeclared_selection import (
    _explicit_trials,
    _select_hjb,
    _select_risk_matched_as,
)


def test_select_hjb_enforces_baseline_inventory_constraint():
    selected, feasible = _select_hjb(
        [
            {"final_equity": 12.0, "inventory_rms": 3.0},
            {"final_equity": 11.0, "inventory_rms": 2.0},
        ],
        baseline_rms=2.5,
    )

    assert feasible
    assert selected["final_equity"] == 11.0


def test_select_hjb_has_predeclared_lowest_risk_fallback():
    selected, feasible = _select_hjb(
        [
            {"final_equity": 12.0, "inventory_rms": 3.0},
            {"final_equity": 11.0, "inventory_rms": 2.8},
        ],
        baseline_rms=2.5,
    )

    assert not feasible
    assert selected["inventory_rms"] == 2.8


def test_risk_matched_as_uses_equity_only_as_tie_breaker():
    selected = _select_risk_matched_as(
        [
            {"final_equity": 10.0, "inventory_rms": 2.9},
            {"final_equity": 12.0, "inventory_rms": 3.1},
        ],
        target_rms=3.0,
    )

    assert selected["final_equity"] == 12.0


def test_explicit_trials_preserve_candidate_pairs():
    trials = _explicit_trials(
        "pure_as",
        [{"terminal_penalty": 1.0, "running_penalty": 0.1}],
    )

    assert trials[0].params == {"terminal_penalty": 1.0, "running_penalty": 0.1}
