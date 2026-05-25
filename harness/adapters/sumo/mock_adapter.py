"""Mock SUMO adapter for testing without SUMO/traci dependency."""

from __future__ import annotations

import base64
import io
import math
import random
import time
from typing import Any

from PIL import Image, ImageDraw

from harness.adapter import Adapter
from harness.adapters.sumo.config import (
    DEFAULT_TRAFFIC_LIGHTS,
    DEFAULT_VEHICLES,
    TRAFFIC_LIGHT_ACTIONS,
    TRAFFIC_LIGHT_PHASES,
    TRAFFIC_LIGHT_SAFETY_CLASS,
    VEHICLE_ACTIONS,
    VEHICLE_PROPERTIES,
    VEHICLE_SAFETY_CLASS,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class _VehicleState:
    """Internal state for a simulated vehicle."""

    def __init__(self, vehicle_id: str, x: float, y: float, speed: float, heading: float, lane: int):
        self.vehicle_id = vehicle_id
        self.x = x
        self.y = y
        self.speed = speed
        self.heading = heading  # degrees
        self.lane = lane
        self.acceleration = 0.0


class _TrafficLightState:
    """Internal state for a simulated traffic light."""

    def __init__(self, tl_id: str, phase: str):
        self.tl_id = tl_id
        self.phase = phase
        self.phase_index = TRAFFIC_LIGHT_PHASES.index(phase)


class MockSUMOAdapter(Adapter):
    """Mock adapter simulating SUMO traffic without traci dependency."""

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._vehicles: dict[str, _VehicleState] = {}
        self._traffic_lights: dict[str, _TrafficLightState] = {}
        self._devices: dict[str, CDD] = {}
        self._scene = ""
        self._sim_time = 0.0

    @property
    def is_initialized(self) -> bool:
        return bool(self._devices)

    async def initialize(self, scene: str = "intersection") -> dict[str, Any]:
        self._scene = scene
        self._sim_time = 0.0

        # Initialize vehicles with varied positions
        self._vehicles = {
            "ego_vehicle": _VehicleState("ego_vehicle", x=50.0, y=100.0, speed=13.9, heading=0.0, lane=1),
            "vehicle_1": _VehicleState("vehicle_1", x=80.0, y=100.0, speed=11.1, heading=0.0, lane=0),
            "vehicle_2": _VehicleState("vehicle_2", x=20.0, y=100.0, speed=8.3, heading=0.0, lane=2),
        }

        # Initialize traffic lights
        self._traffic_lights = {
            "tl_north": _TrafficLightState("tl_north", "green"),
            "tl_east": _TrafficLightState("tl_east", "red"),
        }

        # Build CDDs
        self._devices = {}
        for vid in DEFAULT_VEHICLES:
            self._devices[vid] = self._build_vehicle_cdd(vid)
        for tl_id in DEFAULT_TRAFFIC_LIGHTS:
            self._devices[tl_id] = self._build_traffic_light_cdd(tl_id)

        return {
            "scene": scene,
            "device_count": len(self._devices),
            "device_types": ["vehicle", "traffic_light"],
            "engine": "sumo_mock",
            "vehicles": len(self._vehicles),
            "traffic_lights": len(self._traffic_lights),
        }

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")

        if device_id in self._vehicles:
            props = self._read_vehicle_state(device_id)
        elif device_id in self._traffic_lights:
            props = self._read_traffic_light_state(device_id)
        else:
            raise ValueError(f"Device not found: {device_id}")

        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")

        if device_id in self._vehicles:
            veh = self._vehicles[device_id]
            if property_name == "speed":
                fval = float(value)
                if not (0.0 <= fval <= 50.0):
                    raise ValueError(f"Speed {fval} out of range [0.0, 50.0]")
                veh.speed = fval
            elif property_name == "lane":
                ival = int(value)
                if not (0 <= ival <= 3):
                    raise ValueError(f"Lane {ival} out of range [0, 3]")
                veh.lane = ival
            elif property_name == "acceleration":
                fval = float(value)
                if not (-5.0 <= fval <= 5.0):
                    raise ValueError(f"Acceleration {fval} out of range [-5.0, 5.0]")
                veh.acceleration = fval
            else:
                raise ValueError(f"Unknown vehicle property: {property_name}")

        elif device_id in self._traffic_lights:
            tl = self._traffic_lights[device_id]
            if property_name == "phase":
                if value not in TRAFFIC_LIGHT_PHASES:
                    raise ValueError(f"Invalid phase: {value}. Must be one of {TRAFFIC_LIGHT_PHASES}")
                tl.phase = value
                tl.phase_index = TRAFFIC_LIGHT_PHASES.index(value)
            else:
                raise ValueError(f"Unknown traffic light property: {property_name}")

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": value,
        })
        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")
        params = params or {}

        if device_id in self._vehicles:
            veh = self._vehicles[device_id]
            if action not in VEHICLE_ACTIONS:
                raise ValueError(f"Unknown vehicle action: {action}. Available: {list(VEHICLE_ACTIONS.keys())}")

            if action == "change_lane":
                direction = params.get("direction", "right")
                if direction == "left":
                    veh.lane = min(3, veh.lane + 1)
                else:
                    veh.lane = max(0, veh.lane - 1)
            elif action == "emergency_stop":
                veh.speed = 0.0
                veh.acceleration = 0.0
            elif action == "set_route":
                # In mock, just acknowledge the route
                pass

        elif device_id in self._traffic_lights:
            tl = self._traffic_lights[device_id]
            if action not in TRAFFIC_LIGHT_ACTIONS:
                raise ValueError(f"Unknown traffic light action: {action}. Available: {list(TRAFFIC_LIGHT_ACTIONS.keys())}")

            if action == "next_phase":
                tl.phase_index = (tl.phase_index + 1) % len(TRAFFIC_LIGHT_PHASES)
                tl.phase = TRAFFIC_LIGHT_PHASES[tl.phase_index]
            elif action == "set_phase":
                phase = params.get("phase", "red")
                if phase not in TRAFFIC_LIGHT_PHASES:
                    raise ValueError(f"Invalid phase: {phase}")
                tl.phase = phase
                tl.phase_index = TRAFFIC_LIGHT_PHASES.index(phase)

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params, "mock": True}

    async def capture_image(self) -> str:
        img = Image.new("RGB", (640, 480), color=(80, 80, 80))
        draw = ImageDraw.Draw(img)

        # Draw road (horizontal)
        draw.rectangle([0, 180, 640, 300], fill=(50, 50, 50))
        # Lane markings
        for y in [210, 240, 270]:
            for x in range(0, 640, 40):
                draw.rectangle([x, y - 1, x + 20, y + 1], fill=(255, 255, 255))

        # Draw intersection area
        draw.rectangle([280, 0, 360, 480], fill=(50, 50, 50))

        # Draw traffic lights
        for tl_id, tl in self._traffic_lights.items():
            if tl_id == "tl_north":
                tx, ty = 270, 160
            else:
                tx, ty = 370, 310
            # Light housing
            draw.rectangle([tx - 5, ty - 20, tx + 5, ty + 20], fill=(30, 30, 30))
            colors = {"red": (255, 0, 0), "yellow": (255, 255, 0), "green": (0, 255, 0)}
            draw.ellipse([tx - 4, ty - 4, tx + 4, ty + 4], fill=colors.get(tl.phase, (100, 100, 100)))

        # Draw vehicles
        for vid, veh in self._vehicles.items():
            # Map position to image coordinates
            vx = int(veh.x * 4) % 640
            vy = 190 + veh.lane * 30
            # Vehicle as rectangle
            if vid == "ego_vehicle":
                color = (0, 120, 255)
            else:
                color = (200, 60, 60)
            draw.rectangle([vx - 12, vy - 6, vx + 12, vy + 6], fill=color, outline=(255, 255, 255))
            # Speed indicator
            draw.text((vx - 10, vy - 16), f"{veh.speed:.0f}", fill=(255, 255, 255))

        # Info overlay
        draw.text((10, 10), f"SUMO Mock - {self._scene}", fill=(255, 255, 255))
        draw.text((10, 30), f"Sim time: {self._sim_time:.1f}s", fill=(200, 200, 200))
        draw.text((10, 50), f"Vehicles: {len(self._vehicles)} | TL: {len(self._traffic_lights)}", fill=(200, 200, 200))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    # --- Private helpers ---

    def _read_vehicle_state(self, vehicle_id: str) -> dict[str, Any]:
        veh = self._vehicles[vehicle_id]
        return {
            "position": [veh.x, veh.y],
            "speed": veh.speed,
            "heading": veh.heading,
            "lane": veh.lane,
            "acceleration": veh.acceleration,
        }

    def _read_traffic_light_state(self, tl_id: str) -> dict[str, Any]:
        tl = self._traffic_lights[tl_id]
        return {
            "phase": tl.phase,
            "phase_index": tl.phase_index,
        }

    def _build_vehicle_cdd(self, vehicle_id: str) -> CDD:
        capabilities = []

        # Vehicle properties
        for prop_name, prop_info in VEHICLE_PROPERTIES.items():
            if prop_info["type"] == "float":
                capabilities.append(DeviceCapability(
                    name=prop_name,
                    cap_type="float",
                    readable=True,
                    writable=True,
                    safety_level=SafetyLevel.HIGH,
                    value_range={"min": prop_info["min"], "max": prop_info["max"]},
                    description=f"Vehicle {prop_name} ({prop_info.get('unit', '')})",
                ))
            elif prop_info["type"] == "int":
                capabilities.append(DeviceCapability(
                    name=prop_name,
                    cap_type="float",
                    readable=True,
                    writable=True,
                    safety_level=SafetyLevel.HIGH,
                    value_range={"min": prop_info["min"], "max": prop_info["max"]},
                    description=f"Vehicle {prop_name}",
                ))

        # Read-only state
        for name, desc in [
            ("position", "Vehicle position [x, y] in meters"),
            ("heading", "Vehicle heading in degrees"),
        ]:
            capabilities.append(DeviceCapability(
                name=name,
                cap_type="float",
                readable=True,
                writable=False,
                safety_level=SafetyLevel.LOW,
                description=desc,
            ))

        # Vehicle actions
        for action_name, action_info in VEHICLE_ACTIONS.items():
            capabilities.append(DeviceCapability(
                name=action_name,
                cap_type="action",
                readable=False,
                writable=True,
                safety_level=action_info["safety"],
                description=action_info["description"],
            ))

        display = "Ego Vehicle" if vehicle_id == "ego_vehicle" else f"Vehicle {vehicle_id.split('_')[-1]}"
        return CDD(
            device_id=vehicle_id,
            device_type="vehicle",
            display_name=display,
            location="simulation",
            capabilities=capabilities,
            safety_class=VEHICLE_SAFETY_CLASS,
            metadata={"engine": "sumo_mock", "vehicle_type": "passenger"},
        )

    def _build_traffic_light_cdd(self, tl_id: str) -> CDD:
        capabilities = []

        # Phase property
        capabilities.append(DeviceCapability(
            name="phase",
            cap_type="enum",
            readable=True,
            writable=True,
            safety_level=SafetyLevel.CRITICAL,
            value_range={"values": TRAFFIC_LIGHT_PHASES},
            description="Current traffic light phase",
        ))

        # Read-only
        capabilities.append(DeviceCapability(
            name="phase_index",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="Index of current phase in cycle",
        ))

        # Traffic light actions
        for action_name, action_info in TRAFFIC_LIGHT_ACTIONS.items():
            capabilities.append(DeviceCapability(
                name=action_name,
                cap_type="action",
                readable=False,
                writable=True,
                safety_level=action_info["safety"],
                description=action_info["description"],
            ))

        direction = tl_id.split("_")[-1].capitalize()
        return CDD(
            device_id=tl_id,
            device_type="traffic_light",
            display_name=f"Traffic Light {direction}",
            location="simulation",
            capabilities=capabilities,
            safety_class=TRAFFIC_LIGHT_SAFETY_CLASS,
            metadata={"engine": "sumo_mock"},
        )
