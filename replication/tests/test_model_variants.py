import pytest

from perp_mm_funding.strategy.model_variants import regime_gated_funding_aware_deltas


PURE_AS_DELTAS = (1.0, 2.0)
FUNDING_AWARE_DELTAS = (3.0, 4.0)


def test_regime_gate_uses_pure_as_below_absolute_threshold():
    assert (
        regime_gated_funding_aware_deltas(
            PURE_AS_DELTAS,
            FUNDING_AWARE_DELTAS,
            funding_rate=0.0004,
            threshold=0.0005,
            mode="absolute",
        )
        == PURE_AS_DELTAS
    )


def test_regime_gate_uses_funding_aware_at_absolute_threshold():
    assert (
        regime_gated_funding_aware_deltas(
            PURE_AS_DELTAS,
            FUNDING_AWARE_DELTAS,
            funding_rate=-0.0005,
            threshold=0.0005,
            mode="absolute",
        )
        == FUNDING_AWARE_DELTAS
    )


def test_regime_gate_supports_signed_modes():
    assert (
        regime_gated_funding_aware_deltas(
            PURE_AS_DELTAS,
            FUNDING_AWARE_DELTAS,
            funding_rate=0.0006,
            threshold=0.0005,
            mode="positive",
        )
        == FUNDING_AWARE_DELTAS
    )
    assert (
        regime_gated_funding_aware_deltas(
            PURE_AS_DELTAS,
            FUNDING_AWARE_DELTAS,
            funding_rate=0.0006,
            threshold=0.0005,
            mode="negative",
        )
        == PURE_AS_DELTAS
    )
    assert (
        regime_gated_funding_aware_deltas(
            PURE_AS_DELTAS,
            FUNDING_AWARE_DELTAS,
            funding_rate=-0.0006,
            threshold=0.0005,
            mode="negative",
        )
        == FUNDING_AWARE_DELTAS
    )


def test_regime_gate_rejects_invalid_parameters():
    with pytest.raises(ValueError, match="threshold"):
        regime_gated_funding_aware_deltas(
            PURE_AS_DELTAS,
            FUNDING_AWARE_DELTAS,
            funding_rate=0.0,
            threshold=-0.1,
        )

    with pytest.raises(ValueError, match="unsupported funding gate mode"):
        regime_gated_funding_aware_deltas(
            PURE_AS_DELTAS,
            FUNDING_AWARE_DELTAS,
            funding_rate=0.0,
            threshold=0.1,
            mode="unknown",
        )
