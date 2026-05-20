"""AI2-THOR adapter - bridges Harness capabilities to AI2-THOR simulation."""

from __future__ import annotations

import asyncio
import base64
import io
import time
from typing import Any

from harness.adapter import Adapter
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel

_SAFETY_MAP: dict[str, SafetyLevel] = {
    "FloorLamp": SafetyLevel.LOW,
    "DeskLamp": SafetyLevel.LOW,
    "LightSwitch": SafetyLevel.LOW,
    "Television": SafetyLevel.LOW,
    "Laptop": SafetyLevel.LOW,
    "CellPhone": SafetyLevel.LOW,
    "Book": SafetyLevel.LOW,
    "Fridge": SafetyLevel.MEDIUM,
    "Microwave": SafetyLevel.MEDIUM,
    "CoffeeMachine": SafetyLevel.MEDIUM,
    "Toaster": SafetyLevel.MEDIUM,
    "Window": SafetyLevel.MEDIUM,
    "Blinds": SafetyLevel.MEDIUM,
    "StoveBurner": SafetyLevel.HIGH,
    "StoveKnob": SafetyLevel.HIGH,
    "Faucet": SafetyLevel.HIGH,
    "Safe": SafetyLevel.CRITICAL,
}


def _infer_safety(obj_type: str) -> SafetyLevel:
    return _SAFETY_MAP.get(obj_type, SafetyLevel.LOW)


def _build_capabilities(obj: dict[str, Any]) -> list[DeviceCapability]:
    caps = []
    if obj.get("toggleable"):
        caps.append(DeviceCapability(
            name="isToggled",
            cap_type="boolean",
            writable=True,
            description="Power on/off state",
        ))
    if obj.get("openable"):
        caps.append(DeviceCapability(
            name="isOpen",
            cap_type="boolean",
            writable=True,
            description="Open/close state",
        ))
    if obj.get("canFillWithLiquid"):
        caps.append(DeviceCapability(
            name="isFilledWithLiquid",
            cap_type="boolean",
            writable=True,
            description="Filled with liquid",
        ))
    if obj.get("dirtyable"):
        caps.append(DeviceCapability(
            name="isDirty",
            cap_type="boolean",
            writable=True,
            description="Clean/dirty state",
        ))
    if obj.get("canChangeTempToHot") or obj.get("canChangeTempToCold"):
        caps.append(DeviceCapability(
            name="temperature",
            cap_type="enum",
            writable=False,
            description="Temperature state (Hot/Cold/RoomTemp)",
        ))
    if obj.get("breakable"):
        caps.append(DeviceCapability(
            name="isBroken",
            cap_type="boolean",
            writable=False,
            readable=True,
            description="Broken state",
        ))
    return caps


def _build_cdd(obj: dict[str, Any]) -> CDD | None:
    caps = _build_capabilities(obj)
    if not caps:
        return None
    obj_type = obj["objectType"]
    return CDD(
        device_id=obj["objectId"],
        device_type=obj_type,
        display_name=obj.get("name", obj["objectId"].split("|")[0]),
        location=f"position({obj['position']['x']:.1f}, {obj['position']['z']:.1f})",
        capabilities=caps,
        safety_class=_infer_safety(obj_type),
        exclusive=False,
        metadata={"receptacle": obj.get("receptacle", False), "pickupable": obj.get("pickupable", False)},
    )


class AI2ThorAdapter(Adapter):
    def __init__(self, event_bus: EventBus | None = None):
        self._controller = None
        self._devices: dict[str, CDD] = {}
        self._scene: str = ""
        self._event_bus = event_bus or EventBus()

    @property
    def is_initialized(self) -> bool:
        return self._controller is not None

    async def initialize(self, scene: str = "FloorPlan1") -> dict[str, Any]:
        self._scene = scene

        def _start():
            from ai2thor.controller import Controller
            ctrl = Controller(
                scene=scene,
                gridSize=0.25,
                width=800,
                height=600,
                renderDepthImage=False,
                renderInstanceSegmentation=False,
            )
            return ctrl

        self._controller = await asyncio.to_thread(_start)
        self._devices = self._discover_devices()
        return {
            "scene": scene,
            "device_count": len(self._devices),
            "device_types": list({d.device_type for d in self._devices.values()}),
        }

    def _discover_devices(self) -> dict[str, CDD]:
        devices = {}
        for obj in self._controller.last_event.metadata["objects"]:
            cdd = _build_cdd(obj)
            if cdd:
                devices[cdd.device_id] = cdd
        return devices

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        def _get():
            for obj in self._controller.last_event.metadata["objects"]:
                if obj["objectId"] == device_id:
                    return obj
            return None

        obj = await asyncio.to_thread(_get)
        if obj is None:
            raise ValueError(f"Device not found: {device_id}")

        props = {}
        cdd = self._devices.get(device_id)
        if cdd:
            for cap in cdd.capabilities:
                if cap.readable and cap.name in obj:
                    props[cap.name] = obj[cap.name]

        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        action_map = {
            ("isToggled", True): "ToggleObjectOn",
            ("isToggled", False): "ToggleObjectOff",
            ("isOpen", True): "OpenObject",
            ("isOpen", False): "CloseObject",
            ("isFilledWithLiquid", True): "FillObjectWithLiquid",
            ("isFilledWithLiquid", False): "EmptyLiquidFromObject",
            ("isDirty", False): "CleanObject",
            ("isDirty", True): "DirtyObject",
        }

        bool_value = value if isinstance(value, bool) else str(value).lower() in ("true", "on", "1", "yes")
        action = action_map.get((property_name, bool_value))
        if not action:
            raise ValueError(f"Cannot set {property_name}={value} on {device_id}")

        def _step():
            return self._controller.step(action=action, objectId=device_id)

        event = await asyncio.to_thread(_step)
        if not event.metadata["lastActionSuccess"]:
            raise RuntimeError(f"AI2-THOR action failed: {event.metadata.get('errorMessage', 'unknown')}")

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": bool_value,
            "timestamp": time.time(),
        })

        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        def _step():
            kwargs = {"action": action, "objectId": device_id}
            if params:
                kwargs.update(params)
            return self._controller.step(**kwargs)

        event = await asyncio.to_thread(_step)
        success = event.metadata["lastActionSuccess"]
        return {
            "success": success,
            "error": event.metadata.get("errorMessage") if not success else None,
        }

    async def capture_image(self) -> str:
        def _capture():
            frame = self._controller.last_event.frame
            from PIL import Image
            img = Image.fromarray(frame)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")

        return await asyncio.to_thread(_capture)
