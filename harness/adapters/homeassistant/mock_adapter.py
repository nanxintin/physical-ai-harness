"""Mock Home Assistant adapter for testing without a real HA instance."""

from __future__ import annotations

import base64
import copy
import io
import time
from typing import Any

from PIL import Image, ImageDraw

from harness.adapter import Adapter
from harness.adapters.homeassistant.config import (
    MOCK_ENTITIES,
    SAFETY_MAP,
    SERVICE_MAP,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class MockHomeAssistantAdapter(Adapter):
    """Mock adapter simulating Home Assistant entities and services."""

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._entities: dict[str, dict[str, Any]] = {}
        self._devices: dict[str, CDD] = {}
        self._scene: str = ""

    @property
    def is_initialized(self) -> bool:
        return bool(self._devices)

    async def initialize(self, scene: str = "full_home") -> dict[str, Any]:
        self._scene = scene
        self._entities = copy.deepcopy(MOCK_ENTITIES)
        self._devices = {}

        # Build CDD for each entity
        for entity_id in self._entities:
            self._devices[entity_id] = self._build_entity_cdd(entity_id)

        domains = set(eid.split(".")[0] for eid in self._entities)
        return {
            "scene": scene,
            "device_count": len(self._devices),
            "device_types": sorted(domains),
            "engine": "homeassistant_mock",
            "entities": list(self._entities.keys()),
        }

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        if device_id not in self._entities:
            raise ValueError(f"Entity not found: {device_id}")

        entity = self._entities[device_id]
        props = {"state": entity["state"]}
        props.update(entity["attributes"])

        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        if device_id not in self._entities:
            raise ValueError(f"Entity not found: {device_id}")

        entity = self._entities[device_id]
        domain = device_id.split(".")[0]

        if property_name == "state":
            entity["state"] = str(value)
        elif property_name in entity["attributes"]:
            entity["attributes"][property_name] = value
            # Side effects: setting brightness > 0 turns light on
            if domain == "light" and property_name == "brightness" and float(value) > 0:
                entity["state"] = "on"
            elif domain == "light" and property_name == "brightness" and float(value) == 0:
                entity["state"] = "off"
            elif domain == "fan" and property_name == "percentage" and float(value) > 0:
                entity["state"] = "on"
            elif domain == "fan" and property_name == "percentage" and float(value) == 0:
                entity["state"] = "off"
            elif domain == "cover" and property_name == "current_position":
                pos = int(value)
                entity["state"] = "open" if pos > 0 else "closed"
        else:
            raise ValueError(
                f"Unknown property '{property_name}' for entity '{device_id}'. "
                f"Available: state, {list(entity['attributes'].keys())}"
            )

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": value,
        })
        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        if device_id not in self._entities:
            raise ValueError(f"Entity not found: {device_id}")

        domain = device_id.split(".")[0]
        available_services = SERVICE_MAP.get(domain, [])

        if action not in available_services:
            raise ValueError(
                f"Unknown action '{action}' for domain '{domain}'. "
                f"Available: {available_services}"
            )

        params = params or {}
        entity = self._entities[device_id]

        # Execute service logic
        if action == "turn_on":
            entity["state"] = "on"
            if domain == "light":
                brightness = params.get("brightness", 255)
                entity["attributes"]["brightness"] = brightness
            elif domain == "fan":
                percentage = params.get("percentage", 50)
                entity["attributes"]["percentage"] = percentage

        elif action == "turn_off":
            entity["state"] = "off"
            if domain == "light":
                entity["attributes"]["brightness"] = 0
            elif domain == "fan":
                entity["attributes"]["percentage"] = 0

        elif action == "toggle":
            if entity["state"] == "on":
                entity["state"] = "off"
                if domain == "light":
                    entity["attributes"]["brightness"] = 0
            else:
                entity["state"] = "on"
                if domain == "light":
                    entity["attributes"]["brightness"] = 255

        elif action == "set_temperature":
            temp = params.get("temperature", 24)
            entity["attributes"]["temperature"] = temp
            if entity["state"] == "off":
                entity["state"] = "cool"

        elif action == "set_hvac_mode":
            mode = params.get("hvac_mode", "auto")
            valid = entity["attributes"].get("hvac_modes", [])
            if mode not in valid:
                raise ValueError(f"Invalid HVAC mode: {mode}. Valid: {valid}")
            entity["state"] = mode

        elif action == "set_fan_mode":
            mode = params.get("fan_mode", "medium")
            valid = entity["attributes"].get("fan_modes", [])
            if mode not in valid:
                raise ValueError(f"Invalid fan mode: {mode}. Valid: {valid}")
            entity["attributes"]["fan_mode"] = mode

        elif action == "lock":
            entity["state"] = "locked"

        elif action == "unlock":
            entity["state"] = "unlocked"

        elif action == "open_cover":
            entity["state"] = "open"
            entity["attributes"]["current_position"] = 100

        elif action == "close_cover":
            entity["state"] = "closed"
            entity["attributes"]["current_position"] = 0

        elif action == "set_cover_position":
            pos = params.get("position", 50)
            entity["attributes"]["current_position"] = pos
            entity["state"] = "open" if pos > 0 else "closed"

        elif action == "volume_set":
            vol = params.get("volume_level", 0.5)
            entity["attributes"]["volume_level"] = vol

        elif action == "select_source":
            source = params.get("source", "HDMI1")
            valid = entity["attributes"].get("source_list", [])
            if source not in valid:
                raise ValueError(f"Invalid source: {source}. Valid: {valid}")
            entity["attributes"]["source"] = source
            entity["state"] = "on"

        elif action == "media_play":
            entity["state"] = "playing"

        elif action == "media_pause":
            entity["state"] = "paused"

        elif action == "start":
            entity["state"] = "cleaning"
            entity["attributes"]["status"] = "cleaning"

        elif action == "pause":
            entity["state"] = "paused"
            entity["attributes"]["status"] = "paused"

        elif action == "return_to_base":
            entity["state"] = "returning"
            entity["attributes"]["status"] = "returning"

        elif action == "stop":
            entity["state"] = "idle"
            entity["attributes"]["status"] = "idle"

        elif action == "set_percentage":
            pct = params.get("percentage", 50)
            entity["attributes"]["percentage"] = pct
            entity["state"] = "on" if pct > 0 else "off"

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "entity_id": device_id, "params": params, "mock": True}

    async def capture_image(self) -> str:
        """Draw a Home Assistant-style dashboard with entity states."""
        img = Image.new("RGB", (640, 480), color=(30, 30, 40))
        draw = ImageDraw.Draw(img)

        # Title
        draw.rectangle([0, 0, 640, 40], fill=(50, 50, 70))
        draw.text((20, 12), "Home Assistant Dashboard (Mock)", fill=(255, 255, 255))

        # Layout entities in a grid
        col_width = 200
        row_height = 55
        margin_x, margin_y = 20, 50
        cols = 3

        for idx, (entity_id, entity) in enumerate(self._entities.items()):
            col = idx % cols
            row = idx // cols
            x = margin_x + col * col_width
            y = margin_y + row * row_height

            if y + row_height > 480:
                break  # Don't draw outside image

            domain = entity_id.split(".")[0]
            friendly = entity["attributes"].get("friendly_name", entity_id)
            state = entity["state"]

            # Color based on state
            if state in ("on", "unlocked", "open", "playing", "cleaning"):
                state_color = (80, 200, 120)
                bg_color = (40, 60, 45)
            elif state in ("off", "locked", "closed", "docked", "idle", "paused"):
                state_color = (150, 150, 160)
                bg_color = (40, 40, 50)
            elif state == "unavailable":
                state_color = (200, 80, 80)
                bg_color = (60, 35, 35)
            else:
                state_color = (200, 200, 100)
                bg_color = (50, 50, 40)

            # Card background
            draw.rectangle([x, y, x + col_width - 10, y + row_height - 5], fill=bg_color, outline=(70, 70, 90))

            # Icon placeholder based on domain
            icon_map = {
                "light": "L", "climate": "T", "lock": "K", "cover": "C",
                "media_player": "M", "sensor": "S", "binary_sensor": "B",
                "vacuum": "V", "switch": "W", "fan": "F",
            }
            icon_char = icon_map.get(domain, "?")
            draw.text((x + 8, y + 8), icon_char, fill=state_color)

            # Entity name (truncate)
            name_display = friendly if len(friendly) <= 18 else friendly[:16] + ".."
            draw.text((x + 25, y + 8), name_display, fill=(220, 220, 230))

            # State
            state_display = state
            # Add extra detail for certain entities
            if domain == "light" and state == "on":
                bri = entity["attributes"].get("brightness", 0)
                state_display = f"on ({bri})"
            elif domain == "climate" and state != "off":
                temp = entity["attributes"].get("temperature", "?")
                state_display = f"{state} {temp}C"
            elif domain == "cover":
                pos = entity["attributes"].get("current_position", 0)
                state_display = f"{state} ({pos}%)"
            elif domain == "vacuum":
                status = entity["attributes"].get("status", state)
                state_display = status

            draw.text((x + 25, y + 28), state_display, fill=state_color)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    # --- Private helpers ---

    def _get_domain(self, entity_id: str) -> str:
        return entity_id.split(".")[0]

    def _build_entity_cdd(self, entity_id: str) -> CDD:
        """Build a CDD from an HA entity."""
        domain = self._get_domain(entity_id)
        entity = self._entities[entity_id]
        attrs = entity["attributes"]
        friendly_name = attrs.get("friendly_name", entity_id)
        safety = SAFETY_MAP.get(domain, SafetyLevel.LOW)

        capabilities = []

        # Primary state (readable, writable for actuators)
        is_sensor = domain in ("sensor", "binary_sensor")
        capabilities.append(DeviceCapability(
            name="state",
            cap_type="enum" if domain in ("binary_sensor",) else "string",
            readable=True,
            writable=not is_sensor,
            safety_level=safety,
            description=f"Primary state of {friendly_name}",
        ))

        # Attribute-based capabilities
        for attr_name, attr_value in attrs.items():
            if attr_name == "friendly_name":
                continue

            # Determine type and writability
            if isinstance(attr_value, (int, float)):
                cap_type = "float"
                writable = not is_sensor
                value_range = None
                if attr_name == "brightness":
                    value_range = {"min": 0, "max": 255}
                elif attr_name == "volume_level":
                    value_range = {"min": 0.0, "max": 1.0}
                elif attr_name == "percentage":
                    value_range = {"min": 0, "max": 100}
                elif attr_name == "current_position":
                    value_range = {"min": 0, "max": 100}
                elif attr_name == "temperature":
                    value_range = {"min": 16, "max": 30}
                elif attr_name == "battery" or attr_name == "battery_level":
                    value_range = {"min": 0, "max": 100}
                    writable = False

                capabilities.append(DeviceCapability(
                    name=attr_name,
                    cap_type=cap_type,
                    readable=True,
                    writable=writable,
                    safety_level=safety,
                    value_range=value_range,
                    description=f"{attr_name.replace('_', ' ').title()} of {friendly_name}",
                ))
            elif isinstance(attr_value, list):
                # List attributes are informational (e.g., hvac_modes, source_list)
                capabilities.append(DeviceCapability(
                    name=attr_name,
                    cap_type="enum",
                    readable=True,
                    writable=False,
                    safety_level=SafetyLevel.LOW,
                    value_range={"values": attr_value},
                    description=f"Available {attr_name.replace('_', ' ')} for {friendly_name}",
                ))
            elif isinstance(attr_value, str):
                capabilities.append(DeviceCapability(
                    name=attr_name,
                    cap_type="string",
                    readable=True,
                    writable=not is_sensor,
                    safety_level=safety,
                    description=f"{attr_name.replace('_', ' ').title()} of {friendly_name}",
                ))

        # Service-based action capabilities
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

        # Determine area from entity_id
        entity_name = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
        area = "home"
        if "living" in entity_name:
            area = "living_room"
        elif "bedroom" in entity_name:
            area = "bedroom"
        elif "front_door" in entity_name:
            area = "entrance"
        elif "hallway" in entity_name:
            area = "hallway"
        elif "outdoor" in entity_name:
            area = "outdoor"
        elif "indoor" in entity_name:
            area = "indoor"

        return CDD(
            device_id=entity_id,
            device_type=domain,
            display_name=friendly_name,
            location=area,
            capabilities=capabilities,
            safety_class=safety,
            metadata={"engine": "homeassistant_mock", "domain": domain},
        )
