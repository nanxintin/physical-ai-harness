"""Abstract adapter interface for simulation/real-world backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from harness.models import CDD, DeviceState


class Adapter(ABC):
    @abstractmethod
    async def initialize(self, scene: str = "FloorPlan1") -> dict[str, Any]:
        """Load a scene, return scene metadata."""
        ...

    @abstractmethod
    async def list_devices(self) -> list[CDD]:
        """Return CDDs for all controllable devices."""
        ...

    @abstractmethod
    async def get_device_state(self, device_id: str) -> DeviceState:
        """Read current state of a device."""
        ...

    @abstractmethod
    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        """Set a device property."""
        ...

    @abstractmethod
    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        """Invoke a discrete action on a device."""
        ...

    @abstractmethod
    async def capture_image(self) -> str:
        """Capture current scene view, return base64-encoded PNG."""
        ...
