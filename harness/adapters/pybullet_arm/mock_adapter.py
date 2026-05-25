"""Mock PyBullet adapter for testing without PyBullet dependency."""

from __future__ import annotations

import base64
import io
import math
import time
from typing import Any

from PIL import Image, ImageDraw

from harness.adapter import Adapter
from harness.adapters.pybullet_arm.config import (
    ACTIONS,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    GRIPPER_RANGE,
    GRIPPER_SAFETY_LEVEL,
    HOME_POSITION,
    JOINT_NAMES,
    JOINT_RANGES,
    JOINT_SAFETY_LEVEL,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class MockPyBulletArmAdapter(Adapter):
    """Mock adapter simulating Franka Panda arm without PyBullet dependency."""

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._joint_positions = list(HOME_POSITION)
        self._gripper_width = GRIPPER_RANGE[1]  # Start open
        self._end_effector_position = [0.4, 0.0, 0.4]  # Approximate home EE pos
        self._devices: dict[str, CDD] = {}
        self._scene = ""

    @property
    def is_initialized(self) -> bool:
        return bool(self._devices)

    async def initialize(self, scene: str = "table_top") -> dict[str, Any]:
        self._scene = scene
        self._joint_positions = list(HOME_POSITION)
        self._gripper_width = GRIPPER_RANGE[1]
        self._end_effector_position = [0.4, 0.0, 0.4]
        self._devices = {DEVICE_ID: self._build_arm_cdd()}
        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "pybullet_mock",
            "model": "franka_panda",
            "joints": len(JOINT_NAMES),
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

        if property_name == "gripper_width":
            fval = float(value)
            if not (GRIPPER_RANGE[0] <= fval <= GRIPPER_RANGE[1]):
                raise ValueError(
                    f"Gripper width {fval} out of range [{GRIPPER_RANGE[0]}, {GRIPPER_RANGE[1]}]"
                )
            self._gripper_width = fval
        elif property_name in JOINT_NAMES:
            idx = JOINT_NAMES.index(property_name)
            fval = float(value)
            low, high = JOINT_RANGES[property_name]
            if not (low <= fval <= high):
                raise ValueError(f"Joint value {fval} out of range [{low}, {high}] for {property_name}")
            self._joint_positions[idx] = fval
            self._update_end_effector()
        else:
            raise ValueError(f"Unknown property: {property_name}")

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": value,
        })
        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")
        if action not in ACTIONS:
            raise ValueError(f"Unknown action: {action}. Available: {list(ACTIONS.keys())}")

        params = params or {}

        if action == "home":
            self._joint_positions = list(HOME_POSITION)
            self._end_effector_position = [0.4, 0.0, 0.4]
        elif action == "open_gripper":
            self._gripper_width = GRIPPER_RANGE[1]  # 0.04 m
        elif action == "close_gripper":
            self._gripper_width = GRIPPER_RANGE[0]  # 0.0 m
        elif action == "pick":
            x = params.get("x", 0.4)
            y = params.get("y", 0.0)
            z = params.get("z", 0.1)
            # Simulate: move to position, close gripper
            self._end_effector_position = [x, y, z]
            self._gripper_width = GRIPPER_RANGE[0]
            self._update_joints_from_ee()
        elif action == "place":
            x = params.get("x", 0.4)
            y = params.get("y", 0.2)
            z = params.get("z", 0.1)
            # Simulate: move to position, open gripper
            self._end_effector_position = [x, y, z]
            self._gripper_width = GRIPPER_RANGE[1]
            self._update_joints_from_ee()

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params, "mock": True}

    async def capture_image(self) -> str:
        img = Image.new("RGB", (640, 480), color=(240, 240, 245))
        draw = ImageDraw.Draw(img)

        # Draw table surface
        draw.rectangle([100, 350, 540, 380], fill=(160, 120, 80), outline=(100, 70, 50))

        # Draw robot base
        base_x, base_y = 320, 380
        draw.rectangle([base_x - 30, base_y - 10, base_x + 30, base_y + 10], fill=(60, 60, 60))

        # Draw simplified arm segments based on joint angles
        # Segment lengths (simplified visualization)
        segments = [80, 70, 60, 50, 40, 30, 25]
        x, y = base_x, base_y - 10
        angle = -math.pi / 2  # Start pointing up

        for i, (length, joint_angle) in enumerate(zip(segments, self._joint_positions)):
            angle += joint_angle * 0.3  # Scale down for visualization
            nx = x + int(length * math.cos(angle))
            ny = y + int(length * math.sin(angle))
            # Gradient color from base to tip
            r = 80 + i * 20
            g = 80 + i * 10
            b = 100 + i * 15
            draw.line([x, y, nx, ny], fill=(r, g, b), width=max(8 - i, 3))
            # Joint circle
            draw.ellipse([nx - 4, ny - 4, nx + 4, ny + 4], fill=(200, 200, 200), outline=(100, 100, 100))
            x, y = nx, ny

        # Draw gripper at end effector
        gripper_open = int(self._gripper_width * 500)  # Scale for visualization
        draw.line([x - gripper_open, y, x - gripper_open, y + 15], fill=(100, 100, 100), width=3)
        draw.line([x + gripper_open, y, x + gripper_open, y + 15], fill=(100, 100, 100), width=3)

        # Info text
        draw.text((10, 10), f"Franka Panda (Mock)", fill=(0, 0, 0))
        draw.text((10, 30), f"EE: ({self._end_effector_position[0]:.3f}, "
                            f"{self._end_effector_position[1]:.3f}, "
                            f"{self._end_effector_position[2]:.3f})", fill=(0, 0, 0))
        draw.text((10, 50), f"Gripper: {self._gripper_width:.3f} m", fill=(0, 0, 0))
        draw.text((10, 70), f"Scene: {self._scene}", fill=(0, 0, 0))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    # --- Private helpers ---

    def _read_state(self) -> dict[str, Any]:
        props = {}
        for i, name in enumerate(JOINT_NAMES):
            props[name] = self._joint_positions[i]
        props["gripper_width"] = self._gripper_width
        props["end_effector_position"] = list(self._end_effector_position)
        return props

    def _update_end_effector(self):
        """Simplified forward kinematics approximation for visualization."""
        # Rough approximation: sum contributions of each joint
        # Real FK would use DH parameters, but this suffices for mock
        reach = 0.855  # Panda max reach ~855mm
        j = self._joint_positions
        x = 0.4 + 0.1 * math.sin(j[0]) + 0.05 * math.sin(j[2])
        y = 0.1 * math.cos(j[0]) * math.sin(j[1])
        z = 0.4 + 0.15 * math.cos(j[1]) + 0.1 * math.cos(j[3])
        self._end_effector_position = [
            max(-reach, min(reach, x)),
            max(-reach, min(reach, y)),
            max(0.0, min(reach, z)),
        ]

    def _update_joints_from_ee(self):
        """Simplified inverse kinematics for mock (approximate joint values from EE)."""
        x, y, z = self._end_effector_position
        # Very rough IK just to keep joints in plausible range
        self._joint_positions[0] = math.atan2(y, x) if x != 0 else 0.0
        r = math.sqrt(x * x + y * y)
        self._joint_positions[1] = -math.atan2(z - 0.333, r) if r != 0 else -0.785
        self._joint_positions[2] = 0.0
        self._joint_positions[3] = -2.356 + (z - 0.1) * 0.5
        self._joint_positions[4] = 0.0
        self._joint_positions[5] = 1.571
        self._joint_positions[6] = 0.785
        # Clamp all joints to valid ranges
        for i, name in enumerate(JOINT_NAMES):
            low, high = JOINT_RANGES[name]
            self._joint_positions[i] = max(low, min(high, self._joint_positions[i]))

    def _build_arm_cdd(self) -> CDD:
        capabilities = []

        # Joint capabilities
        for name in JOINT_NAMES:
            low, high = JOINT_RANGES[name]
            capabilities.append(DeviceCapability(
                name=name,
                cap_type="float",
                readable=True,
                writable=True,
                safety_level=JOINT_SAFETY_LEVEL,
                value_range={"min": low, "max": high},
                description=f"Joint angle for {name} (radians)",
            ))

        # Gripper
        capabilities.append(DeviceCapability(
            name="gripper_width",
            cap_type="float",
            readable=True,
            writable=True,
            safety_level=GRIPPER_SAFETY_LEVEL,
            value_range={"min": GRIPPER_RANGE[0], "max": GRIPPER_RANGE[1]},
            description="Gripper finger width (meters)",
        ))

        # Read-only end effector
        capabilities.append(DeviceCapability(
            name="end_effector_position",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="End effector position [x, y, z] in meters",
        ))

        # Actions
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
            metadata={"engine": "pybullet_mock", "dof": 7},
        )
