"""Mock adapter for testing without AI2-THOR Unity binary.

Simulates a kitchen scene with realistic device states and behavior.
"""

from __future__ import annotations

import base64
import io
import time
from typing import Any

from harness.adapter import Adapter
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel

_MOCK_SCENE = {
    "FloorLamp|+01.32|+00.00|+00.45": {
        "objectId": "FloorLamp|+01.32|+00.00|+00.45",
        "objectType": "FloorLamp",
        "toggleable": True,
        "isToggled": False,
        "position": {"x": 1.32, "y": 0.9, "z": 0.45},
    },
    "DeskLamp|+02.10|+00.78|+01.20": {
        "objectId": "DeskLamp|+02.10|+00.78|+01.20",
        "objectType": "DeskLamp",
        "toggleable": True,
        "isToggled": True,
        "position": {"x": 2.10, "y": 0.78, "z": 1.20},
    },
    "Television|+00.50|+01.20|+03.00": {
        "objectId": "Television|+00.50|+01.20|+03.00",
        "objectType": "Television",
        "toggleable": True,
        "isToggled": True,
        "position": {"x": 0.50, "y": 1.20, "z": 3.00},
    },
    "Fridge|+03.00|+00.00|+02.50": {
        "objectId": "Fridge|+03.00|+00.00|+02.50",
        "objectType": "Fridge",
        "openable": True,
        "isOpen": False,
        "toggleable": False,
        "position": {"x": 3.00, "y": 0.0, "z": 2.50},
    },
    "Microwave|+02.50|+01.00|+02.80": {
        "objectId": "Microwave|+02.50|+01.00|+02.80",
        "objectType": "Microwave",
        "openable": True,
        "isOpen": False,
        "toggleable": True,
        "isToggled": False,
        "position": {"x": 2.50, "y": 1.00, "z": 2.80},
    },
    "StoveBurner|+01.80|+00.90|+02.80": {
        "objectId": "StoveBurner|+01.80|+00.90|+02.80",
        "objectType": "StoveBurner",
        "toggleable": True,
        "isToggled": False,
        "position": {"x": 1.80, "y": 0.90, "z": 2.80},
    },
    "Faucet|+02.00|+01.00|+01.50": {
        "objectId": "Faucet|+02.00|+01.00|+01.50",
        "objectType": "Faucet",
        "toggleable": True,
        "isToggled": False,
        "position": {"x": 2.00, "y": 1.00, "z": 1.50},
    },
    "Window|+00.00|+01.50|+02.00": {
        "objectId": "Window|+00.00|+01.50|+02.00",
        "objectType": "Window",
        "openable": True,
        "isOpen": False,
        "position": {"x": 0.00, "y": 1.50, "z": 2.00},
    },
    "Safe|+03.50|+00.00|+00.20": {
        "objectId": "Safe|+03.50|+00.00|+00.20",
        "objectType": "Safe",
        "openable": True,
        "isOpen": False,
        "position": {"x": 3.50, "y": 0.0, "z": 0.20},
    },
    "CoffeeMachine|+02.20|+00.90|+01.80": {
        "objectId": "CoffeeMachine|+02.20|+00.90|+01.80",
        "objectType": "CoffeeMachine",
        "toggleable": True,
        "isToggled": False,
        "position": {"x": 2.20, "y": 0.90, "z": 1.80},
    },
}

_SAFETY_MAP = {
    "FloorLamp": SafetyLevel.LOW,
    "DeskLamp": SafetyLevel.LOW,
    "Television": SafetyLevel.LOW,
    "Fridge": SafetyLevel.MEDIUM,
    "Microwave": SafetyLevel.MEDIUM,
    "CoffeeMachine": SafetyLevel.MEDIUM,
    "Window": SafetyLevel.MEDIUM,
    "StoveBurner": SafetyLevel.HIGH,
    "Faucet": SafetyLevel.HIGH,
    "Safe": SafetyLevel.CRITICAL,
}


class MockAdapter(Adapter):
    """In-memory mock adapter that simulates device behavior without Unity."""

    def __init__(self, event_bus: EventBus | None = None):
        self._objects: dict[str, dict] = {}
        self._devices: dict[str, CDD] = {}
        self._scene: str = ""
        self._event_bus = event_bus or EventBus()

    @property
    def is_initialized(self) -> bool:
        return len(self._objects) > 0

    async def initialize(self, scene: str = "FloorPlan1") -> dict[str, Any]:
        self._scene = scene
        self._objects = {k: dict(v) for k, v in _MOCK_SCENE.items()}
        self._devices = {}
        for obj_id, obj in self._objects.items():
            cdd = self._build_cdd(obj)
            if cdd:
                self._devices[obj_id] = cdd

        return {
            "scene": scene,
            "device_count": len(self._devices),
            "device_types": list({d.device_type for d in self._devices.values()}),
            "mock": True,
        }

    def _build_cdd(self, obj: dict) -> CDD | None:
        caps = []
        if obj.get("toggleable"):
            caps.append(DeviceCapability(
                name="isToggled", cap_type="boolean", writable=True,
                description="Power on/off state",
            ))
        if obj.get("openable"):
            caps.append(DeviceCapability(
                name="isOpen", cap_type="boolean", writable=True,
                description="Open/close state",
            ))
        if not caps:
            return None

        obj_type = obj["objectType"]
        return CDD(
            device_id=obj["objectId"],
            device_type=obj_type,
            display_name=obj_type,
            location=f"position({obj['position']['x']:.1f}, {obj['position']['z']:.1f})",
            capabilities=caps,
            safety_class=_SAFETY_MAP.get(obj_type, SafetyLevel.LOW),
        )

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        obj = self._objects.get(device_id)
        if not obj:
            raise ValueError(f"Device not found: {device_id}")
        cdd = self._devices.get(device_id)
        props = {}
        if cdd:
            for cap in cdd.capabilities:
                if cap.name in obj:
                    props[cap.name] = obj[cap.name]
        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        obj = self._objects.get(device_id)
        if not obj:
            raise ValueError(f"Device not found: {device_id}")

        bool_value = value if isinstance(value, bool) else str(value).lower() in ("true", "on", "1")

        if property_name not in obj:
            raise ValueError(f"Property {property_name} not found on {device_id}")

        obj[property_name] = bool_value

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": bool_value,
            "timestamp": time.time(),
        })

        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        if device_id not in self._objects:
            return {"success": False, "error": f"Device not found: {device_id}"}
        return {"success": True, "action": action, "mock": True}

    async def capture_image(self) -> str:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (800, 600), color=(40, 40, 50))
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), f"Mock Scene: {self._scene}", fill=(255, 255, 255))
        y = 60
        for device_id, cdd in list(self._devices.items())[:12]:
            obj = self._objects[device_id]
            state_parts = []
            for cap in cdd.capabilities:
                if cap.name in obj:
                    state_parts.append(f"{cap.name}={obj[cap.name]}")
            state_str = ", ".join(state_parts)
            color = (0, 255, 0) if any(obj.get(c.name) for c in cdd.capabilities) else (180, 180, 180)
            draw.text((20, y), f"[{cdd.safety_class.value:8s}] {cdd.display_name:15s} | {state_str}", fill=color)
            y += 35
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
