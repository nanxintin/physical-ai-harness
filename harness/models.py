"""Core data models: CDD, DeviceState, SafetyLevel."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SafetyLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    def __le__(self, other: SafetyLevel) -> bool:
        order = [SafetyLevel.LOW, SafetyLevel.MEDIUM, SafetyLevel.HIGH, SafetyLevel.CRITICAL]
        return order.index(self) <= order.index(other)

    def __lt__(self, other: SafetyLevel) -> bool:
        order = [SafetyLevel.LOW, SafetyLevel.MEDIUM, SafetyLevel.HIGH, SafetyLevel.CRITICAL]
        return order.index(self) < order.index(other)


@dataclass
class DeviceCapability:
    name: str
    cap_type: str  # "boolean", "float", "enum", "action"
    readable: bool = True
    writable: bool = True
    safety_level: SafetyLevel = SafetyLevel.LOW
    value_range: dict[str, Any] | None = None
    description: str = ""


@dataclass
class CDD:
    """Capability Description Document."""
    device_id: str
    device_type: str
    display_name: str
    location: str
    capabilities: list[DeviceCapability] = field(default_factory=list)
    safety_class: SafetyLevel = SafetyLevel.LOW
    exclusive: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "display_name": self.display_name,
            "location": self.location,
            "safety_class": self.safety_class.value,
            "exclusive": self.exclusive,
            "capabilities": [
                {
                    "name": c.name,
                    "type": c.cap_type,
                    "readable": c.readable,
                    "writable": c.writable,
                    "safety_level": c.safety_level.value,
                    "description": c.description,
                    **({"value_range": c.value_range} if c.value_range else {}),
                }
                for c in self.capabilities
            ],
        }


@dataclass
class DeviceState:
    device_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "properties": self.properties,
            "timestamp": self.timestamp,
        }
