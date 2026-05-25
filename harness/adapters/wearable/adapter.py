"""Real wearable adapter connecting to BLE devices or health data APIs."""

from __future__ import annotations

import time
from typing import Any

from harness.adapter import Adapter
from harness.adapters.wearable.config import (
    ACTIONS,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    SENSORS,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class WearableAdapter(Adapter):
    """Adapter connecting to a real wearable device via BLE or health data API.

    Requirements:
        - bleak (BLE communication): pip install bleak
        - Or a health data API SDK (e.g., Garmin Connect, Fitbit Web API)

    Environment variables:
        - WEARABLE_MAC: BLE MAC address of the wearable device
        - WEARABLE_API_KEY: API key for health data service (if using cloud API)
        - WEARABLE_API_URL: Base URL for health data service
    """

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._devices: dict[str, CDD] = {}
        self._connected = False

    @property
    def is_initialized(self) -> bool:
        return self._connected

    async def initialize(self, scene: str = "daily_activity") -> dict[str, Any]:
        raise NotImplementedError(
            "Real wearable adapter requires BLE or API connection. "
            "Install 'bleak' for BLE: pip install bleak\n"
            "Or configure WEARABLE_API_KEY and WEARABLE_API_URL environment variables "
            "for cloud health data API access.\n"
            "Use MockWearableAdapter for testing without hardware."
        )

    async def list_devices(self) -> list[CDD]:
        raise NotImplementedError("Adapter not initialized. Call initialize() first.")

    async def get_device_state(self, device_id: str) -> DeviceState:
        raise NotImplementedError("Adapter not initialized. Call initialize() first.")

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        raise NotImplementedError("Adapter not initialized. Call initialize() first.")

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        raise NotImplementedError("Adapter not initialized. Call initialize() first.")

    async def capture_image(self) -> str:
        raise NotImplementedError("Adapter not initialized. Call initialize() first.")
