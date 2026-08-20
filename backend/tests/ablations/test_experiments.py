"""Phase 43 acceptance tests for frozen baseline and ablation behavior."""

import pytest

from app.ablations.experiments import (
    ABLATION_CONFIGURATIONS,
    AblationConfiguration,
    AblationLedger,
    AblationMode,
    AblationObservation,
)


def test_matrix_contains_the_exact_six_required_modes_in_order() -> None:
    assert tuple(configuration.mode for configuration in ABLATION_CONFIGURATIONS) == tuple(AblationMode)


def test_no_gate_modes_are_sandbox_only_and_not_production_eligible() -> None:
    for configuration in ABLATION_CONFIGURATIONS:
        if not configuration.safety_gate:
            assert configuration.sandbox_only
            assert not configuration.production_deployment_eligible


def test_gated_modes_progress_from_deterministic_to_llm_to_experience() -> None:
    configurations = {item.mode: item for item in ABLATION_CONFIGURATIONS}
    assert configurations[AblationMode.B3_DETERMINISTIC_WITH_GATE].llm_ranking is False
    assert configurations[AblationMode.B4_LLM_WITH_GATE].llm_ranking is True
    assert configurations[AblationMode.B5_FULL_WITH_EXPERIENCE].experience_memory is True


def test_invalid_no_gate_configuration_cannot_leave_the_sandbox() -> None:
    with pytest.raises(ValueError, match="sandbox-only"):
        AblationConfiguration(AblationMode.B1_DETERMINISTIC_NO_GATE, True, False, False, False, False)


def test_ledger_collects_every_required_measure() -> None:
    ledger = AblationLedger()
    ledger.record(AblationObservation(AblationMode.B4_LLM_WITH_GATE, 0.20, 4.0, 1.0, safe_rejection=True, regression_prevented=True))
    ledger.record(AblationObservation(AblationMode.B4_LLM_WITH_GATE, 0.10, 2.0, 3.0, unsafe_acceptance=True, rollback_performed=True, inconclusive=True))

    metrics = ledger.metrics_for(AblationMode.B4_LLM_WITH_GATE)

    assert metrics.observation_count == 2
    assert metrics.mean_performance_improvement == pytest.approx(0.15)
    assert metrics.unsafe_acceptance_count == 1
    assert metrics.safe_rejection_count == 1
    assert metrics.regressions_prevented_count == 1
    assert metrics.mean_evaluation_overhead_seconds == pytest.approx(3.0)
    assert metrics.mean_ai_overhead_seconds == pytest.approx(2.0)
    assert metrics.rollback_count == 1
    assert metrics.inconclusive_rate == pytest.approx(0.5)


def test_empty_mode_reports_absent_rates_and_means() -> None:
    metrics = AblationLedger().metrics_for(AblationMode.B0_NATIVE)

    assert metrics.observation_count == 0
    assert metrics.mean_performance_improvement is None
    assert metrics.mean_evaluation_overhead_seconds is None
    assert metrics.mean_ai_overhead_seconds is None
    assert metrics.inconclusive_rate is None


def test_negative_overhead_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        AblationObservation(AblationMode.B0_NATIVE, 0.0, -0.1, 0.0)
