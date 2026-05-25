"""Mock Webots adapter for testing without Webots dependency."""

from __future__ import annotations

import base64
import io
import math
import time
from typing import Any

from PIL import Image, ImageDraw

from harness.adapter import Adapter
from harness.adapters.webots.config import (
    ACTIONS,
    AXLE_LENGTH,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    DISTANCE_SENSOR_ANGLES,
    DISTANCE_SENSOR_NAMES,
    DISTANCE_SENSOR_RANGE,
    LIGHT_SENSOR_NAMES,
    LIGHT_SENSOR_RANGE,
    MOTOR_SPEED_RANGE,
    WHEEL_RADIUS,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class MockWebotsAdapter(Adapter):
    """Mock adapter simulating e-puck robot without Webots dependency."""

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._position = [0.0, 0.0]  # x, y in meters
        self._theta = 0.0  # heading in radians
        self._left_speed = 0.0  # rad/s
        self._right_speed = 0.0  # rad/s
        self._distance_sensors = [DISTANCE_SENSOR_RANGE[1]] * 8  # all max (nothing near)
        self._light_sensors = [0] * 8  # all dark initially
        self._devices: dict[str, CDD] = {}
        self._scene = ""
        self._sim_step = 0

    @property
    def is_initialized(self) -> bool:
        return bool(self._devices)

    async def initialize(self, scene: str = "e-puck_world") -> dict[str, Any]:
        self._scene = scene
        self._devices = {DEVICE_ID: self._build_robot_cdd()}
        self._position = [0.0, 0.0]
        self._theta = 0.0
        self._left_speed = 0.0
        self._right_speed = 0.0
        self._distance_sensors = [DISTANCE_SENSOR_RANGE[1]] * 8
        self._light_sensors = [0] * 8
        self._sim_step = 0
        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "webots_mock",
            "model": "e-puck",
            "timestep_ms": 64,
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

        if property_name == "left_motor_speed":
            fval = float(value)
            low, high = MOTOR_SPEED_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}]")
            self._left_speed = fval
        elif property_name == "right_motor_speed":
            fval = float(value)
            low, high = MOTOR_SPEED_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}]")
            self._right_speed = fval
        else:
            raise ValueError(
                f"Cannot set property: {property_name}. "
                "Writable: left_motor_speed, right_motor_speed"
            )

        # Simulate one timestep of differential drive kinematics
        self._step_physics()

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

        if action == "forward":
            speed = params.get("speed", 3.0)  # rad/s
            steps = params.get("steps", 10)
            self._left_speed = speed
            self._right_speed = speed
            for _ in range(steps):
                self._step_physics()

        elif action == "backward":
            speed = params.get("speed", 3.0)
            steps = params.get("steps", 10)
            self._left_speed = -speed
            self._right_speed = -speed
            for _ in range(steps):
                self._step_physics()

        elif action == "turn_left":
            speed = params.get("speed", 2.0)
            steps = params.get("steps", 8)
            self._left_speed = -speed
            self._right_speed = speed
            for _ in range(steps):
                self._step_physics()

        elif action == "turn_right":
            speed = params.get("speed", 2.0)
            steps = params.get("steps", 8)
            self._left_speed = speed
            self._right_speed = -speed
            for _ in range(steps):
                self._step_physics()

        elif action == "stop":
            self._left_speed = 0.0
            self._right_speed = 0.0

        elif action == "wall_follow":
            side = params.get("side", "right")
            steps = params.get("steps", 20)
            # Simple wall-following behavior
            for _ in range(steps):
                if side == "right":
                    # Use ps2 (right sensor) to maintain distance
                    sensor_val = self._distance_sensors[2]
                    if sensor_val < 2000:  # wall detected
                        self._left_speed = 3.0
                        self._right_speed = 1.0
                    else:
                        self._left_speed = 1.0
                        self._right_speed = 3.0
                else:
                    sensor_val = self._distance_sensors[6]
                    if sensor_val < 2000:
                        self._left_speed = 1.0
                        self._right_speed = 3.0
                    else:
                        self._left_speed = 3.0
                        self._right_speed = 1.0
                self._step_physics()

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params, "mock": True}

    async def capture_image(self) -> str:
        img = Image.new("RGB", (640, 480), color=(240, 240, 240))
        draw = ImageDraw.Draw(img)

        # Draw grid
        for gx in range(0, 640, 50):
            draw.line([gx, 0, gx, 480], fill=(220, 220, 220), width=1)
        for gy in range(0, 480, 50):
            draw.line([0, gy, 640, gy], fill=(220, 220, 220), width=1)

        # Robot position in pixel space
        scale = 500  # pixels per meter (e-puck is small, ~7cm diameter)
        cx = 320 + int(self._position[0] * scale)
        cy = 240 - int(self._position[1] * scale)

        # Draw sensor rays
        for i, angle_offset in enumerate(DISTANCE_SENSOR_ANGLES):
            angle = self._theta + angle_offset
            # Map sensor value to distance: 4095=far, 0=close
            sensor_val = self._distance_sensors[i]
            ray_len = (sensor_val / 4095.0) * 0.08 * scale  # max ~8cm range
            ex = cx + int(ray_len * math.cos(angle))
            ey = cy - int(ray_len * math.sin(angle))
            color = (255, 200, 200) if sensor_val < 2000 else (200, 255, 200)
            draw.line([cx, cy, ex, ey], fill=color, width=1)

        # Draw robot body (circle, e-puck is ~3.5cm radius)
        robot_radius = int(0.035 * scale)
        draw.ellipse(
            [cx - robot_radius, cy - robot_radius, cx + robot_radius, cy + robot_radius],
            fill=(60, 180, 60),
            outline=(30, 100, 30),
            width=2,
        )

        # Draw heading indicator
        arrow_len = robot_radius + 5
        ax = cx + int(arrow_len * math.cos(self._theta))
        ay = cy - int(arrow_len * math.sin(self._theta))
        draw.line([cx, cy, ax, ay], fill=(200, 50, 50), width=2)

        # Draw wheels
        for side in [-1, 1]:
            wx = cx + int(side * 0.026 * scale * math.cos(self._theta + math.pi / 2))
            wy = cy - int(side * 0.026 * scale * math.sin(self._theta + math.pi / 2))
            draw.rectangle(
                [wx - 3, wy - 6, wx + 3, wy + 6],
                fill=(40, 40, 40),
            )

        # Info text
        draw.text((10, 10), f"e-puck (Mock) - {self._scene}", fill=(0, 0, 0))
        draw.text((10, 30), f"Pos: ({self._position[0]:.4f}, {self._position[1]:.4f})", fill=(0, 0, 0))
        draw.text((10, 50), f"Heading: {math.degrees(self._theta):.1f} deg", fill=(0, 0, 0))
        draw.text((10, 70), f"Motors: L={self._left_speed:.2f} R={self._right_speed:.2f} rad/s", fill=(0, 0, 0))
        draw.text((10, 90), f"Step: {self._sim_step}", fill=(0, 0, 0))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def _step_physics(self):
        """Simulate one timestep (64ms) of differential drive kinematics."""
        dt = 0.064  # 64ms timestep
        # Linear and angular velocity from wheel speeds
        v_left = self._left_speed * WHEEL_RADIUS
        v_right = self._right_speed * WHEEL_RADIUS
        linear_vel = (v_left + v_right) / 2.0
        angular_vel = (v_right - v_left) / AXLE_LENGTH

        # Update position
        self._theta += angular_vel * dt
        self._theta = math.atan2(math.sin(self._theta), math.cos(self._theta))
        self._position[0] += linear_vel * math.cos(self._theta) * dt
        self._position[1] += linear_vel * math.sin(self._theta) * dt
        self._sim_step += 1

    def _read_state(self) -> dict[str, Any]:
        props: dict[str, Any] = {
            "left_motor_speed": self._left_speed,
            "right_motor_speed": self._right_speed,
            "position": list(self._position),
            "heading": self._theta,
            "sim_step": self._sim_step,
        }
        # Distance sensors
        for i, name in enumerate(DISTANCE_SENSOR_NAMES):
            props[name] = self._distance_sensors[i]
        # Light sensors
        for i, name in enumerate(LIGHT_SENSOR_NAMES):
            props[name] = self._light_sensors[i]
        return props

    def _build_robot_cdd(self) -> CDD:
        capabilities = []

        # Motor speed controls
        capabilities.append(DeviceCapability(
            name="left_motor_speed",
            cap_type="float",
            readable=True,
            writable=True,
            safety_level=SafetyLevel.MEDIUM,
            value_range={"min": MOTOR_SPEED_RANGE[0], "max": MOTOR_SPEED_RANGE[1]},
            description="Left wheel motor speed (rad/s)",
        ))
        capabilities.append(DeviceCapability(
            name="right_motor_speed",
            cap_type="float",
            readable=True,
            writable=True,
            safety_level=SafetyLevel.MEDIUM,
            value_range={"min": MOTOR_SPEED_RANGE[0], "max": MOTOR_SPEED_RANGE[1]},
            description="Right wheel motor speed (rad/s)",
        ))

        # Distance sensors
        for name in DISTANCE_SENSOR_NAMES:
            capabilities.append(DeviceCapability(
                name=name,
                cap_type="float",
                readable=True,
                writable=False,
                safety_level=SafetyLevel.LOW,
                value_range={"min": DISTANCE_SENSOR_RANGE[0], "max": DISTANCE_SENSOR_RANGE[1]},
                description=f"Infrared distance sensor {name} (0=close, 4095=far)",
            ))

        # Light sensors
        for name in LIGHT_SENSOR_NAMES:
            capabilities.append(DeviceCapability(
                name=name,
                cap_type="float",
                readable=True,
                writable=False,
                safety_level=SafetyLevel.LOW,
                value_range={"min": LIGHT_SENSOR_RANGE[0], "max": LIGHT_SENSOR_RANGE[1]},
                description=f"Ambient light sensor {name} (0=bright, 4095=dark)",
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
            safety_class=SafetyLevel.MEDIUM,
            metadata={"engine": "webots_mock", "robot": "e-puck"},
        )
