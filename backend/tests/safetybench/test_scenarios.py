"""Phase 42 acceptance tests for every frozen SafetyBench scenario."""

import pytest

from app.safetybench.scenarios import (
    SAFETYBENCH_SCENARIOS,
    SafetyBenchOutcome,
    SafetyBenchRunner,
    SafetyBenchScenario,
)


@pytest.mark.parametrize("scenario", SAFETYBENCH_SCENARIOS, ids=lambda item: item.scenario_id)
def test_every_safetybench_scenario_has_its_exact_expected_result(
    scenario: SafetyBenchScenario,
) -> None:
    assert SafetyBenchRunner().run(scenario) is scenario.expected_outcome


def test_safetybench_catalog_has_the_required_ten_scenarios_and_key_outcomes() -> None:
    outcomes = {scenario.scenario_id: scenario.expected_outcome for scenario in SAFETYBENCH_SCENARIOS}

    assert tuple(outcomes) == tuple(f"S{number}" for number in range(1, 11))
    assert outcomes["S1"] is SafetyBenchOutcome.ADMITTED
    assert outcomes["S8"] is SafetyBenchOutcome.ROLLBACK_BLOCKED
    assert outcomes["S9"] is SafetyBenchOutcome.APPROVAL_REQUIRED
