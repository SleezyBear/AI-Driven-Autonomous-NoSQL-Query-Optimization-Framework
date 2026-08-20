"""Phase 43 typed ablation matrix and outcome aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AblationMode(str, Enum):
    """The frozen baseline and ablation modes used for comparison."""

    B0_NATIVE = "B0_NATIVE"
    B1_DETERMINISTIC_NO_GATE = "B1_DETERMINISTIC_NO_GATE"
    B2_LLM_RANK_NO_GATE = "B2_LLM_RANK_NO_GATE"
    B3_DETERMINISTIC_WITH_GATE = "B3_DETERMINISTIC_WITH_GATE"
    B4_LLM_WITH_GATE = "B4_LLM_WITH_GATE"
    B5_FULL_WITH_EXPERIENCE = "B5_FULL_WITH_EXPERIENCE"


@dataclass(frozen=True)
class AblationConfiguration:
    """Capabilities declared by an experiment mode; this grants no execution authority."""

    mode: AblationMode
    deterministic_candidates: bool
    llm_ranking: bool
    safety_gate: bool
    experience_memory: bool
    sandbox_only: bool

    def __post_init__(self) -> None:
        if not self.safety_gate and not self.sandbox_only:
            raise ValueError("no-gate ablation modes must be sandbox-only")

    @property
    def production_deployment_eligible(self) -> bool:
        """Only gated, non-sandbox experiments may be considered for production."""
        return self.safety_gate and not self.sandbox_only


ABLATION_CONFIGURATIONS = (
    AblationConfiguration(AblationMode.B0_NATIVE, False, False, False, False, True),
    AblationConfiguration(AblationMode.B1_DETERMINISTIC_NO_GATE, True, False, False, False, True),
    AblationConfiguration(AblationMode.B2_LLM_RANK_NO_GATE, True, True, False, False, True),
    AblationConfiguration(AblationMode.B3_DETERMINISTIC_WITH_GATE, True, False, True, False, False),
    AblationConfiguration(AblationMode.B4_LLM_WITH_GATE, True, True, True, False, False),
    AblationConfiguration(AblationMode.B5_FULL_WITH_EXPERIENCE, True, True, True, True, False),
)


@dataclass(frozen=True)
class AblationObservation:
    """One measured outcome, retaining safety and cost evidence without raw telemetry."""

    mode: AblationMode
    performance_improvement: float
    evaluation_overhead_seconds: float
    ai_overhead_seconds: float
    unsafe_acceptance: bool = False
    safe_rejection: bool = False
    regression_prevented: bool = False
    rollback_performed: bool = False
    inconclusive: bool = False

    def __post_init__(self) -> None:
        if self.evaluation_overhead_seconds < 0 or self.ai_overhead_seconds < 0:
            raise ValueError("overhead measurements cannot be negative")


@dataclass(frozen=True)
class AblationMetrics:
    """Aggregate measures required for a single ablation mode."""

    mode: AblationMode
    observation_count: int
    mean_performance_improvement: float | None
    unsafe_acceptance_count: int
    safe_rejection_count: int
    regressions_prevented_count: int
    mean_evaluation_overhead_seconds: float | None
    mean_ai_overhead_seconds: float | None
    rollback_count: int
    inconclusive_rate: float | None


class AblationLedger:
    """In-memory experiment collector with no database or deployment capability."""

    def __init__(self) -> None:
        self._observations: list[AblationObservation] = []

    def record(self, observation: AblationObservation) -> None:
        self._observations.append(observation)

    def metrics_for(self, mode: AblationMode) -> AblationMetrics:
        observations = tuple(item for item in self._observations if item.mode is mode)
        count = len(observations)
        if not observations:
            return AblationMetrics(mode, 0, None, 0, 0, 0, None, None, 0, None)
        return AblationMetrics(
            mode=mode,
            observation_count=count,
            mean_performance_improvement=sum(item.performance_improvement for item in observations) / count,
            unsafe_acceptance_count=sum(item.unsafe_acceptance for item in observations),
            safe_rejection_count=sum(item.safe_rejection for item in observations),
            regressions_prevented_count=sum(item.regression_prevented for item in observations),
            mean_evaluation_overhead_seconds=sum(item.evaluation_overhead_seconds for item in observations) / count,
            mean_ai_overhead_seconds=sum(item.ai_overhead_seconds for item in observations) / count,
            rollback_count=sum(item.rollback_performed for item in observations),
            inconclusive_rate=sum(item.inconclusive for item in observations) / count,
        )
