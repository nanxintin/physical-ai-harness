"""Mock MuJoCo adapter for testing without GPU or MuJoCo dependency."""

from __future__ import annotations

import base64
import io
import math
import time
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from harness.adapter import Adapter
from harness.adapters.mujoco_go1.robot_config import (
    ACTIONS,
    ACTUATOR_NAMES,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    STAND_POSE,
    SIT_POSE,
    get_joint_range,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class MockMuJoCoAdapter(Adapter):
    """Mock adapter simulating Go1 robot without MuJoCo dependency."""

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._joint_positions = list(STAND_POSE)
        self._body_position = [0.0, 0.0, 0.34]
        self._body_orientation = [0.0, 0.0, 0.0]
        self._body_velocity = [0.0, 0.0, 0.0]
        self._imu_angular_velocity = [0.0, 0.0, 0.0]
        self._foot_contacts = [True, True, True, True]
        self._devices: dict[str, CDD] = {}
        self._scene = ""
        self._current_action = "stand"

    @property
    def is_initialized(self) -> bool:
        return bool(self._devices)

    async def initialize(self, scene: str = "flat_ground") -> dict[str, Any]:
        self._scene = scene
        self._devices = {DEVICE_ID: self._build_robot_cdd()}
        self._joint_positions = list(STAND_POSE)
        self._body_position = [0.0, 0.0, 0.34]
        self._current_action = "stand"
        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "mujoco_mock",
            "model": "unitree_go1",
            "actuators": len(ACTUATOR_NAMES),
        }

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")
        props = self._read_state()
        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")
        if not property_name.startswith("joint_"):
            raise ValueError(f"Cannot set non-joint property: {property_name}")

        actuator_name = property_name[6:]
        try:
            idx = ACTUATOR_NAMES.index(actuator_name)
        except ValueError:
            raise ValueError(f"Unknown actuator: {actuator_name}")

        float_value = float(value)
        low, high = get_joint_range(actuator_name)
        if not (low <= float_value <= high):
            raise ValueError(f"Value {float_value} out of range [{low}, {high}] for {actuator_name}")

        self._joint_positions[idx] = float_value
        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": float_value,
        })
        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")
        if action not in ACTIONS:
            raise ValueError(f"Unknown action: {action}. Available: {list(ACTIONS.keys())}")

        params = params or {}
        self._current_action = action

        if action == "stand":
            self._joint_positions = list(STAND_POSE)
            self._body_position[2] = 0.34
        elif action == "sit":
            self._joint_positions = list(SIT_POSE)
            self._body_position[2] = 0.15
        elif action == "walk_forward":
            speed = params.get("speed", 0.3)
            duration = params.get("duration", 2.0)
            self._body_position[0] += speed * duration
            self._body_velocity = [speed, 0.0, 0.0]
        elif action == "walk_backward":
            speed = params.get("speed", 0.3)
            duration = params.get("duration", 2.0)
            self._body_position[0] -= speed * duration
            self._body_velocity = [-speed, 0.0, 0.0]
        elif action == "turn_left":
            self._body_orientation[2] += math.radians(45)
            self._imu_angular_velocity = [0.0, 0.0, 0.5]
        elif action == "turn_right":
            self._body_orientation[2] -= math.radians(45)
            self._imu_angular_velocity = [0.0, 0.0, -0.5]
        elif action == "trot":
            speed = params.get("speed", 0.6)
            duration = params.get("duration", 2.0)
            self._body_position[0] += speed * duration
            self._body_velocity = [speed, 0.0, 0.0]
        elif action == "stop":
            self._joint_positions = list(STAND_POSE)
            self._body_velocity = [0.0, 0.0, 0.0]
            self._imu_angular_velocity = [0.0, 0.0, 0.0]
            self._current_action = "stand"

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params, "mock": True}

    async def capture_image(self) -> str:
        img = Image.new("RGB", (640, 480), color=(200, 220, 240))
        draw = ImageDraw.Draw(img)
        # Draw ground
        draw.rectangle([0, 350, 640, 480], fill=(100, 150, 100))
        # Draw robot body (simplified)
        cx = 320 + int(self._body_position[0] * 50)
        cy = 250 - int(self._body_position[2] * 100)
        draw.rectangle([cx - 60, cy - 20, cx + 60, cy + 20], fill=(80, 80, 80), outline=(40, 40, 40))
        # Draw legs
        for i, (dx, dy_label) in enumerate([(-45, "FR"), (-15, "FL"), (15, "RR"), (45, "RL")]):
            lx = cx + dx
            draw.line([lx, cy + 20, lx, cy + 80], fill=(60, 60, 60), width=3)
        # Draw info text
        draw.text((10, 10), f"Unitree Go1 (Mock) - {self._current_action}", fill=(0, 0, 0))
        draw.text((10, 30), f"Pos: ({self._body_position[0]:.2f}, {self._body_position[1]:.2f}, {self._body_position[2]:.2f})", fill=(0, 0, 0))
        draw.text((10, 50), f"Scene: {self._scene}", fill=(0, 0, 0))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def _read_state(self) -> dict[str, Any]:
        props = {}
        for i, name in enumerate(ACTUATOR_NAMES):
            props[f"joint_{name}"] = self._joint_positions[i]
        props["body_position"] = list(self._body_position)
        props["body_orientation"] = list(self._body_orientation)
        props["body_velocity"] = list(self._body_velocity)
        props["imu_angular_velocity"] = list(self._imu_angular_velocity)
        props["foot_contacts"] = list(self._foot_contacts)
        props["current_action"] = self._current_action
        return props

    def _build_robot_cdd(self) -> CDD:
        capabilities = []
        for name in ACTUATOR_NAMES:
            low, high = get_joint_range(name)
            capabilities.append(DeviceCapability(
                name=f"joint_{name}",
                cap_type="float",
                readable=True,
                writable=True,
                safety_level=SafetyLevel.HIGH,
                value_range={"min": low, "max": high},
                description=f"Joint position target for {name} (radians)",
            ))
        for name, desc in [
            ("body_position", "Robot body position [x, y, z] in world frame"),
            ("body_orientation", "Robot body orientation [roll, pitch, yaw] in radians"),
            ("body_velocity", "Robot body linear velocity [vx, vy, vz] m/s"),
            ("imu_angular_velocity", "IMU angular velocity [wx, wy, wz] rad/s"),
        ]:
            capabilities.append(DeviceCapability(
                name=name,
                cap_type="float",
                readable=True,
                writable=False,
                safety_level=SafetyLevel.LOW,
                description=desc,
            ))
        capabilities.append(DeviceCapability(
            name="foot_contacts",
            cap_type="boolean",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="Foot ground contacts [FR, FL, RR, RL]",
        ))
        for action_name, action_info in ACTIONS.items():
            capabilities.append(DeviceCapability(
                name=action_name,
                cap_type="action",
                readable=False,
                writable=True,
                safety_level=action_info["safety"],
                description=action_info["description"],
            ))
        return CDD(
            device_id=DEVICE_ID,
            device_type=DEVICE_TYPE,
            display_name=DISPLAY_NAME,
            location="simulation",
            capabilities=capabilities,
            safety_class=SafetyLevel.HIGH,
            metadata={"engine": "mujoco_mock"},
        )
