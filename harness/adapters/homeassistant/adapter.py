"""Real Home Assistant adapter using the HA REST API."""

from __future__ import annotations

import os
import time
from typing import Any

from harness.adapter import Adapter
from harness.adapters.homeassistant.config import (
    HA_TOKEN_ENV,
    HA_URL,
    SAFETY_MAP,
    SERVICE_MAP,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class HomeAssistantAdapter(Adapter):
    """Adapter connecting to a real Home Assistant instance via REST API.

    Requirements:
        - aiohttp: pip install aiohttp
        - A running Home Assistant instance
        - A Long-Lived Access Token (set via HA_TOKEN env var)

    API endpoints used:
        - GET  /api/states               -> list all entities
        - GET  /api/states/{entity_id}   -> get single entity state
        - POST /api/services/{domain}/{service} -> call a service

    For real-time events, the HA WebSocket API at ws://host:8123/api/websocket
    can be used for push-based state updates.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        ha_url: str | None = None,
        ha_token: str | None = None,
    ):
        self._event_bus = event_bus or EventBus()
        self._ha_url = ha_url or HA_URL
        self._ha_token = ha_token or os.environ.get(HA_TOKEN_ENV, "")
        self._session = None  # aiohttp.ClientSession
        self._devices: dict[str, CDD] = {}
        self._connected = False

    @property
    def is_initialized(self) -> bool:
        return self._connected

    async def initialize(self, scene: str = "full_home") -> dict[str, Any]:
        if not self._ha_token:
            raise RuntimeError(
                f"Home Assistant token not found. "
                f"Set the {HA_TOKEN_ENV} environment variable with a Long-Lived Access Token.\n"
                f"Generate one at: {self._ha_url}/profile/security\n"
                f"Use MockHomeAssistantAdapter for testing without a real HA instance."
            )

        try:
            import aiohttp
        except ImportError:
            raise ImportError(
                "aiohttp is required for the real Home Assistant adapter. "
                "Install it with: pip install aiohttp\n"
                "Use MockHomeAssistantAdapter for testing without dependencies."
            )

        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self._ha_token}",
                "Content-Type": "application/json",
            }
        )

        # Verify connection
        try:
            async with self._session.get(f"{self._ha_url}/api/") as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Failed to connect to Home Assistant at {self._ha_url}. "
                        f"Status: {resp.status}"
                    )
        except Exception as e:
            await self._session.close()
            self._session = None
            raise RuntimeError(
                f"Cannot reach Home Assistant at {self._ha_url}: {e}\n"
                f"Ensure HA is running and accessible."
            ) from e

        # Fetch all entity states
        async with self._session.get(f"{self._ha_url}/api/states") as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to fetch states: {resp.status}")
            entities = await resp.json()

        # Build CDDs from entities
        for entity_data in entities:
            entity_id = entity_data["entity_id"]
            domain = entity_id.split(".")[0]
            if domain in SERVICE_MAP or domain in ("sensor", "binary_sensor"):
                self._devices[entity_id] = self._build_entity_cdd(entity_id, entity_data)

        self._connected = True
        domains = set(eid.split(".")[0] for eid in self._devices)
        return {
            "scene": scene,
            "device_count": len(self._devices),
            "device_types": sorted(domains),
            "engine": "homeassistant",
            "ha_url": self._ha_url,
        }

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        if not self._session:
            raise RuntimeError("Adapter not initialized. Call initialize() first.")
        if device_id not in self._devices:
            raise ValueError(f"Entity not found: {device_id}")

        async with self._session.get(f"{self._ha_url}/api/states/{device_id}") as resp:
            if resp.status == 404:
                raise ValueError(f"Entity not found in HA: {device_id}")
            if resp.status != 200:
                raise RuntimeError(f"HA API error: {resp.status}")
            data = await resp.json()

        props = {"state": data["state"]}
        props.update(data.get("attributes", {}))
        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        if not self._session:
            raise RuntimeError("Adapter not initialized. Call initialize() first.")
        if device_id not in self._devices:
            raise ValueError(f"Entity not found: {device_id}")

        domain = device_id.split(".")[0]

        # Map property set to HA service call
        service_data = {"entity_id": device_id}

        if domain == "light" and property_name == "brightness":
            service_data["brightness"] = int(value)
            service = "turn_on"
        elif domain == "climate" and property_name == "temperature":
            service_data["temperature"] = float(value)
            service = "set_temperature"
        elif domain == "cover" and property_name == "current_position":
            service_data["position"] = int(value)
            service = "set_cover_position"
        elif domain == "fan" and property_name == "percentage":
            service_data["percentage"] = int(value)
            service = "set_percentage"
        elif domain == "media_player" and property_name == "volume_level":
            service_data["volume_level"] = float(value)
            service = "volume_set"
        else:
            raise ValueError(
                f"Cannot directly set '{property_name}' on '{device_id}'. "
                f"Use invoke_action() with the appropriate service call."
            )

        async with self._session.post(
            f"{self._ha_url}/api/services/{domain}/{service}",
            json=service_data,
        ) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"HA service call failed: {resp.status}")

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": value,
        })
        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        if not self._session:
            raise RuntimeError("Adapter not initialized. Call initialize() first.")
        if device_id not in self._devices:
            raise ValueError(f"Entity not found: {device_id}")

        domain = device_id.split(".")[0]
        available_services = SERVICE_MAP.get(domain, [])
        if action not in available_services:
            raise ValueError(
                f"Unknown action '{action}' for domain '{domain}'. "
                f"Available: {available_services}"
            )

        params = params or {}
        service_data = {"entity_id": device_id, **params}

        async with self._session.post(
            f"{self._ha_url}/api/services/{domain}/{action}",
            json=service_data,
        ) as resp:
            if resp.status not in (200, 201):
                error_text = await resp.text()
                raise RuntimeError(
                    f"HA service call {domain}.{action} failed: {resp.status} - {error_text}"
                )

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "entity_id": device_id, "params": params}

    async def capture_image(self) -> str:
        """Capture is not directly supported by HA REST API for all entities.

        For camera entities, use /api/camera_proxy/{entity_id}.
        This stub returns an empty image with a message.
        """
        if not self._session:
            raise RuntimeError("Adapter not initialized. Call initialize() first.")

        from PIL import Image, ImageDraw
        import io

        img = Image.new("RGB", (640, 480), color=(30, 30, 40))
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), "Home Assistant - Live View Not Available", fill=(255, 255, 255))
        draw.text((20, 50), f"Connected to: {self._ha_url}", fill=(150, 200, 255))
        draw.text((20, 80), f"Entities: {len(self._devices)}", fill=(150, 200, 255))
        draw.text((20, 120), "Use get_device_state() to read entity states.", fill=(180, 180, 180))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    async def shutdown(self):
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None
        self._connected = False

    # --- Private helpers ---

    def _build_entity_cdd(self, entity_id: str, entity_data: dict) -> CDD:
        """Build a CDD from HA entity data."""
        domain = entity_id.split(".")[0]
        attrs = entity_data.get("attributes", {})
        friendly_name = attrs.get("friendly_name", entity_id)
        safety = SAFETY_MAP.get(domain, SafetyLevel.LOW)

        capabilities = []

        # Primary state
        is_sensor = domain in ("sensor", "binary_sensor")
        capabilities.append(DeviceCapability(
            name="state",
            cap_type="string",
            readable=True,
            writable=not is_sensor,
            safety_level=safety,
            description=f"Primary state of {friendly_name}",
        ))

        # Attributes as readable capabilities
        for attr_name, attr_value in attrs.items():
            if attr_name == "friendly_name":
                continue
            if isinstance(attr_value, (int, float)):
                capabilities.append(DeviceCapability(
                    name=attr_name,
                    cap_type="float",
                    readable=True,
                    writable=not is_sensor,
                    safety_level=safety,
                    description=f"{attr_name} of {friendly_name}",
                ))
            elif isinstance(attr_value, list):
                capabilities.append(DeviceCapability(
                    name=attr_name,
                    cap_type="enum",
                    readable=True,
                    writable=False,
                    safety_level=SafetyLevel.LOW,
                    value_range={"values": attr_value},
                    description=f"Available {attr_name} for {friendly_name}",
                ))

        # Services as actions
        services = SERVICE_MAP.get(domain, [])
        for service in services:
            capabilities.append(DeviceCapability(
                name=service,
                cap_type="action",
                readable=False,
                writable=True,
                safety_level=safety,
                description=f"Call {domain}.{service} on {friendly_name}",
            ))

        return CDD(
            device_id=entity_id,
            device_type=domain,
            display_name=friendly_name,
            location="home",
            capabilities=capabilities,
            safety_class=safety,
            metadata={"engine": "homeassistant", "domain": domain},
        )
