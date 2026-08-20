"""Phase 39 acceptance tests for the human-gated configuration advisor."""

from app.recommendations.configuration import (
    ConfigurationAdvisor,
    ProtectedConfigurationDomain,
    WhitelistedConfigurationSetting,
)


def test_known_whitelisted_setting_is_advisory_and_human_gated() -> None:
    advisor = ConfigurationAdvisor()

    recommendation = advisor.recommend("telemetry_window_seconds", 60)

    assert recommendation.accepted is True
    assert recommendation.parameter_name is WhitelistedConfigurationSetting.TELEMETRY_WINDOW_SECONDS
    assert recommendation.human_approval_required is True
    assert not hasattr(advisor, "apply")


def test_llm_cannot_invent_a_configuration_parameter() -> None:
    recommendation = ConfigurationAdvisor().recommend("enable_unbounded_execution", 1)

    assert recommendation.accepted is False
    assert recommendation.reason_codes == ("UNKNOWN_PARAMETER",)


def test_no_configuration_candidate_may_weaken_a_protected_domain() -> None:
    advisor = ConfigurationAdvisor()
    for domain in ProtectedConfigurationDomain:
        recommendation = advisor.recommend("evaluation_sample_count", 10, (domain,))

        assert recommendation.accepted is False
        assert recommendation.reason_codes == ("REJECTED_SAFETY_INVARIANT",)
