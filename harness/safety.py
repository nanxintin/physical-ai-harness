"""Safety sandbox - gate-checks actions against device safety levels."""

from __future__ import annotations

from dataclasses import dataclass

from harness.models import CDD, SafetyLevel


@dataclass
class SafetyCheckResult:
    allowed: bool
    reason: str
    requires_confirmation: bool = False


class SafetySandbox:
    def __init__(self, max_allowed: SafetyLevel = SafetyLevel.HIGH):
        self.max_allowed = max_allowed

    def check(self, device: CDD, property_name: str | None = None) -> SafetyCheckResult:
        level = device.safety_class
        if property_name:
            for cap in device.capabilities:
                if cap.name == property_name:
                    if not (cap.safety_level <= level):
                        level = cap.safety_level
                    break

        if level == SafetyLevel.CRITICAL:
            return SafetyCheckResult(
                allowed=False,
                reason=f"CRITICAL action on {device.display_name} requires human confirmation",
                requires_confirmation=True,
            )

        if not (level <= self.max_allowed):
            return SafetyCheckResult(
                allowed=False,
                reason=f"Action safety level {level.value} exceeds max allowed {self.max_allowed.value}",
            )

        return SafetyCheckResult(allowed=True, reason="OK")
