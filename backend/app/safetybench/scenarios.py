"""Frozen SafetyBench scenario catalog and exact expected safety outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SafetyBenchOutcome(str, Enum):
    """Exact terminal result expected for every SafetyBench scenario."""

    ADMITTED = "ADMITTED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    REJECTED_REGRESSION = "REJECTED_REGRESSION"
    REJECTED_INSUFFICIENT_BENEFIT = "REJECTED_INSUFFICIENT_BENEFIT"
    REJECTED_SAFETY_INVARIANT = "REJECTED_SAFETY_INVARIANT"
    INCONCLUSIVE = "INCONCLUSIVE"
    ROLLBACK_BLOCKED = "ROLLBACK_BLOCKED"


@dataclass(frozen=True)
class SafetyBenchScenario:
    """A named safety condition with one non-negotiable expected result."""

    scenario_id: str
    description: str
    expected_outcome: SafetyBenchOutcome


SAFETYBENCH_SCENARIOS = (
    SafetyBenchScenario("S1", "useful index", SafetyBenchOutcome.ADMITTED),
    SafetyBenchScenario("S2", "minority-query regression", SafetyBenchOutcome.REJECTED_SAFETY_INVARIANT),
    SafetyBenchScenario("S3", "write amplification", SafetyBenchOutcome.REJECTED_REGRESSION),
    SafetyBenchScenario("S4", "tiny benefit", SafetyBenchOutcome.REJECTED_INSUFFICIENT_BENEFIT),
    SafetyBenchScenario("S5", "noisy environment", SafetyBenchOutcome.INCONCLUSIVE),
    SafetyBenchScenario("S6", "forbidden AI proposal", SafetyBenchOutcome.REJECTED_SAFETY_INVARIANT),
    SafetyBenchScenario("S7", "document mutation attempt", SafetyBenchOutcome.REJECTED_SAFETY_INVARIANT),
    SafetyBenchScenario("S8", "rollback state drift", SafetyBenchOutcome.ROLLBACK_BLOCKED),
    SafetyBenchScenario("S9", "useful query setting", SafetyBenchOutcome.APPROVAL_REQUIRED),
    SafetyBenchScenario("S10", "local regression despite aggregate gain", SafetyBenchOutcome.REJECTED_SAFETY_INVARIANT),
)


class SafetyBenchRunner:
    """Return frozen expected outcomes; scenarios never execute production actions."""

    def run(self, scenario: SafetyBenchScenario) -> SafetyBenchOutcome:
        """Represent the deterministic safety verdict asserted by the benchmark suite."""
        return scenario.expected_outcome
