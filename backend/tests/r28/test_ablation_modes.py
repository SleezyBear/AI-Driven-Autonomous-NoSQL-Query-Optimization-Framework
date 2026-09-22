"""R28: B0-B5 resolve to distinct, executable ablation configurations."""

from __future__ import annotations

from app.ablations.experiments import ABLATION_CONFIGURATIONS, AblationMode
from benchmarks.ablations import candidate_setup_for, configuration_for, resolve_plan


def test_every_mode_has_a_frozen_configuration() -> None:
    assert {configuration.mode for configuration in ABLATION_CONFIGURATIONS} == set(AblationMode)


def test_native_mode_has_no_candidate_or_gate() -> None:
    plan = resolve_plan(AblationMode.B0_NATIVE)
    assert plan.candidates == ()
    assert plan.selected_index is None
    assert candidate_setup_for(plan) is None
    assert plan.safety_gate is False
    assert plan.llm_ranking is False


def test_deterministic_no_gate_is_sandbox_only_and_selects_an_index() -> None:
    plan = resolve_plan(AblationMode.B1_DETERMINISTIC_NO_GATE)
    assert plan.sandbox_only is True
    assert plan.safety_gate is False
    assert plan.llm_ranking is False
    assert plan.selected_index is not None
    assert candidate_setup_for(plan) is not None
    assert configuration_for(AblationMode.B1_DETERMINISTIC_NO_GATE).production_deployment_eligible is False


def test_llm_no_gate_is_sandbox_only_and_differs_from_deterministic() -> None:
    deterministic = resolve_plan(AblationMode.B1_DETERMINISTIC_NO_GATE)
    llm = resolve_plan(AblationMode.B2_LLM_RANK_NO_GATE)
    assert llm.llm_ranking is True
    assert llm.sandbox_only is True
    assert llm.safety_gate is False
    assert llm.mode is not deterministic.mode
    assert configuration_for(AblationMode.B2_LLM_RANK_NO_GATE).production_deployment_eligible is False


def test_gated_modes_enable_admission_and_isolate_llm_and_experience() -> None:
    b3 = resolve_plan(AblationMode.B3_DETERMINISTIC_WITH_GATE)
    b4 = resolve_plan(AblationMode.B4_LLM_WITH_GATE)
    b5 = resolve_plan(AblationMode.B5_FULL_WITH_EXPERIENCE)
    assert b3.safety_gate is True and b3.llm_ranking is False
    assert b4.safety_gate is True and b4.llm_ranking is True
    assert b5.experience_memory is True
    assert b4.sandbox_only is False and b5.sandbox_only is False


def test_modes_produce_distinct_behavioral_configurations() -> None:
    signatures = {
        mode: (
            resolve_plan(mode).deterministic_candidates,
            resolve_plan(mode).llm_ranking,
            resolve_plan(mode).safety_gate,
            resolve_plan(mode).experience_memory,
        )
        for mode in AblationMode
    }
    assert len(set(signatures.values())) == len(AblationMode)


def test_explicit_boundaries_change_the_resolved_order() -> None:
    def reverse_ranker(candidates: tuple[object, ...]) -> tuple[str, ...]:
        return tuple(candidate.label for candidate in reversed(candidates))  # type: ignore[attr-defined]

    def prioritize(order: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(reversed(order))

    llm_plan = resolve_plan(AblationMode.B2_LLM_RANK_NO_GATE, ranker=reverse_ranker)
    full_plan = resolve_plan(AblationMode.B5_FULL_WITH_EXPERIENCE, ranker=reverse_ranker, prioritize=prioritize)
    deterministic_plan = resolve_plan(AblationMode.B1_DETERMINISTIC_NO_GATE)
    assert llm_plan.ranking_order != deterministic_plan.ranking_order
    assert full_plan.experience_invoked is True
    assert full_plan.ranking_order == tuple(reversed(llm_plan.ranking_order))


def test_invalid_ranking_permutation_is_rejected() -> None:
    def bad_ranker(candidates: tuple[object, ...]) -> tuple[str, ...]:
        return ("C1",)

    import pytest

    with pytest.raises(ValueError, match="exactly once"):
        resolve_plan(AblationMode.B2_LLM_RANK_NO_GATE, ranker=bad_ranker)
