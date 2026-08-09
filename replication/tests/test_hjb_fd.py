import numpy as np
import pytest

from perp_mm_funding.model.hjb_fd import HJBFDSolverParams, monotone_cfl_bound, solve_hjb_fd


def _params(**overrides):
    values = {
        "horizon_hours": 1.0,
        "q_min": -2,
        "q_max": 2,
        "f_min": -0.001,
        "f_max": 0.001,
        "n_f": 5,
        "n_t": 21,
        "kappa": 0.5,
        "theta_bar": 0.0,
        "sigma_f": 0.0,
        "fill_intensity": 0.0,
        "intensity_k": 100.0,
        "terminal_penalty": 0.02,
        "running_penalty": 0.01,
        "min_delta": 0.0,
    }
    values.update(overrides)
    return HJBFDSolverParams(**values)


def test_solve_hjb_fd_builds_expected_grid_and_terminal_penalty():
    solution = solve_hjb_fd(_params())

    assert solution.values.shape == (21, 5, 5)
    np.testing.assert_array_equal(solution.q_grid, np.array([-2, -1, 0, 1, 2]))
    np.testing.assert_allclose(solution.values[-1, :, 2], -0.02 * solution.q_grid**2)
    assert solution.time_step <= solution.max_time_step


def test_optimal_deltas_widen_bid_for_long_inventory():
    solution = solve_hjb_fd(_params())

    bid_delta, ask_delta = solution.optimal_deltas(t_hours=0.0, q=1, f=0.0)

    assert bid_delta > ask_delta
    assert ask_delta >= 0.0


def test_optimal_deltas_return_infinity_for_inventory_boundary_side():
    solution = solve_hjb_fd(_params())

    top_bid_delta, top_ask_delta = solution.optimal_deltas(t_hours=0.0, q=2, f=0.0)
    bottom_bid_delta, bottom_ask_delta = solution.optimal_deltas(t_hours=0.0, q=-2, f=0.0)

    assert np.isinf(top_bid_delta)
    assert np.isfinite(top_ask_delta)
    assert np.isfinite(bottom_bid_delta)
    assert np.isinf(bottom_ask_delta)


def test_nonunit_quote_size_recovers_per_unit_value_difference():
    q_step = 0.05
    solution = solve_hjb_fd(
        _params(
            q_min=-0.1,
            q_max=0.1,
            q_step=q_step,
            fill_intensity=0.0,
            terminal_penalty=2.0,
            running_penalty=0.0,
        )
    )

    bid_delta, ask_delta = solution.optimal_deltas(t_hours=1.0, q=0.05, f=0.0)
    theta_now = -2.0 * 0.05**2
    bid_jump = -2.0 * 0.1**2 - theta_now
    ask_jump = -2.0 * 0.0**2 - theta_now

    np.testing.assert_allclose(bid_delta, 1.0 / 100.0 - bid_jump / q_step)
    np.testing.assert_allclose(ask_delta, max(0.0, 1.0 / 100.0 - ask_jump / q_step))


def test_quote_recovery_is_invariant_to_inventory_unit_rescaling():
    physical = solve_hjb_fd(
        _params(
            q_min=-0.1,
            q_max=0.1,
            q_step=0.05,
            fill_intensity=0.0,
            terminal_penalty=2.0,
            running_penalty=0.0,
        )
    )
    lots = solve_hjb_fd(
        _params(
            q_min=-2.0,
            q_max=2.0,
            q_step=1.0,
            fill_intensity=0.0,
            intensity_k=100.0 / 0.05,
            terminal_penalty=2.0 * 0.05**2,
            running_penalty=0.0,
        )
    )

    physical_deltas = physical.optimal_deltas(t_hours=1.0, q=0.05, f=0.0)
    lot_deltas = lots.optimal_deltas(t_hours=1.0, q=1.0, f=0.0)

    np.testing.assert_allclose(physical_deltas, np.asarray(lot_deltas) / 0.05)


def test_funding_off_zero_risk_limit_recovers_symmetric_as_spread():
    intensity_k = 80.0
    solution = solve_hjb_fd(
        _params(
            kappa=0.0,
            theta_bar=0.0,
            sigma_f=0.0,
            fill_intensity=0.0,
            intensity_k=intensity_k,
            terminal_penalty=0.0,
            running_penalty=0.0,
        )
    )

    bid_delta, ask_delta = solution.optimal_deltas(t_hours=0.0, q=0, f=0.0)

    np.testing.assert_allclose(bid_delta, 1.0 / intensity_k)
    np.testing.assert_allclose(ask_delta, 1.0 / intensity_k)


def test_theta_rejects_inventory_outside_grid():
    solution = solve_hjb_fd(_params())

    with pytest.raises(ValueError, match="outside the inventory grid"):
        solution.theta(t_hours=0.0, q=3, f=0.0)


def test_solve_hjb_fd_rejects_invalid_intensity_k():
    with pytest.raises(ValueError, match="intensity_k must be positive"):
        solve_hjb_fd(_params(intensity_k=0.0))


def test_monotone_cfl_bound_rejects_too_coarse_time_grid():
    params = _params(fill_intensity=100.0, n_t=2)

    assert monotone_cfl_bound(params) < 0.01
    with pytest.raises(ValueError, match="n_t too low for monotone explicit HJB scheme"):
        solve_hjb_fd(params)


def test_monotone_scheme_can_disable_cfl_for_diagnostics():
    solution = solve_hjb_fd(_params(fill_intensity=100.0, n_t=2, enforce_cfl=False))

    assert solution.max_transition_rate > 0.0
    assert solution.time_step > solution.max_time_step
