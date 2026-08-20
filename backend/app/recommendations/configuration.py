"""Human-gated configuration recommendations with a frozen safe whitelist."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProtectedConfigurationDomain(str, Enum):
    """Domains that configuration advice is never permitted to weaken."""

    SECURITY = "security"
    DURABILITY = "durability"
    CONSISTENCY = "consistency"
    DATA_INTEGRITY = "data_integrity"


class WhitelistedConfigurationSetting(str, Enum):
    """Known control-plane-only parameters permitted to enter advisory review."""

    TELEMETRY_WINDOW_SECONDS = "telemetry_window_seconds"
    EVALUATION_SAMPLE_COUNT = "evaluation_sample_count"
    POST_DEPLOYMENT_WINDOW_SECONDS = "post_deployment_window_seconds"


@dataclass(frozen=True)
class ConfigurationRecommendation:
    """An advisory that can only be acted on through separate human approval."""

    parameter_name: WhitelistedConfigurationSetting | None
    proposed_value: int | None
    human_approval_required: bool
    accepted: bool
    reason_codes: tuple[str, ...]


class ConfigurationAdvisor:
    """Accept known, safe control-plane settings and reject all other proposals."""

    _RANGES = {
        WhitelistedConfigurationSetting.TELEMETRY_WINDOW_SECONDS: (10, 3600),
        WhitelistedConfigurationSetting.EVALUATION_SAMPLE_COUNT: (1, 1000),
        WhitelistedConfigurationSetting.POST_DEPLOYMENT_WINDOW_SECONDS: (10, 86400),
    }

    def recommend(
        self,
        parameter_name: str,
        proposed_value: int,
        weakened_domains: tuple[ProtectedConfigurationDomain, ...] = (),
    ) -> ConfigurationRecommendation:
        """Validate an LLM-supplied name against the frozen whitelist; never apply it."""
        try:
            setting = WhitelistedConfigurationSetting(parameter_name)
        except ValueError:
            return ConfigurationRecommendation(None, None, True, False, ("UNKNOWN_PARAMETER",))
        if weakened_domains:
            return ConfigurationRecommendation(
                setting, None, True, False, ("REJECTED_SAFETY_INVARIANT",)
            )
        minimum, maximum = self._RANGES[setting]
        if not minimum <= proposed_value <= maximum:
            return ConfigurationRecommendation(setting, None, True, False, ("VALUE_OUT_OF_RANGE",))
        return ConfigurationRecommendation(setting, proposed_value, True, True, ())
