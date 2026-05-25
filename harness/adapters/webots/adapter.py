"""Webots R2025a adapter for e-puck robot via external controller API."""

from __future__ import annotations

import asyncio
import base64
import io
import math
import time
from typing import Any

from PIL import Image

from harness.adapter import Adapter
from harness.adapters.webots.config import (
    ACTIONS,
    AXLE_LENGTH,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    DISTANCE_SENSOR_NAMES,
    DISTANCE_SENSOR_RANGE,
    LIGHT_SENSOR_NAMES,
    LIGHT_SENSOR_RANGE,
    MOTOR_SPEED_RANGE,
    TIMESTEP,
    WHEEL_RADIUS,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel

try:
    from controller import Robot, Motor, DistanceSensor, LightSensor, Camera
except ImportError:
    Robot = None
    Motor = None
    DistanceSensor = None
    LightSensor = None
    Camera = None


class WebotsAdapter(Adapter):
    """Adapter bridging Harness to Webots R2025a simulation of e-puck."""

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._robot: Any = None
        self._left_motor: Any = None
        self._right_motor: Any = None
        self._distance_sensors: list[Any] = []
        self._light_sensors: list[Any] = []
        self._camera: Any = None
        self._devices: dict[str, CDD] = {}
        self._scene = ""
        self._left_speed = 0.0
        self._right_speed = 0.0
        self._position = [0.0, 0.0]
        self._theta = 0.0
        self._sim_step = 0

    @property
    def is_initialized(self) -> bool:
        return self._robot is not None

    async def initialize(self, scene: str = "e-puck_world") -> dict[str, Any]:
        if Robot is None:
            raise ImportError(
                "Webots controller module not found. "
                "Run this as a Webots external controller or install the webots package."
            )

        self._scene = scene
        self._robot = Robot()

        # Initialize motors
        self._left_motor = self._robot.getDevice("left wheel motor")
        self._right_motor = self._robot.getDevice("right wheel motor")
        self._left_motor.setPosition(float("inf"))  # velocity control mode
        self._right_motor.setPosition(float("inf"))
        self._left_motor.setVelocity(0.0)
        self._right_motor.setVelocity(0.0)

        # Initialize distance sensors
        self._distance_sensors = []
        for name in DISTANCE_SENSOR_NAMES:
            sensor = self._robot.getDevice(name)
            sensor.enable(TIMESTEP)
            self._distance_sensors.append(sensor)

        # Initialize light sensors
        self._light_sensors = []
        for name in LIGHT_SENSOR_NAMES:
            sensor = self._robot.getDevice(name)
            sensor.enable(TIMESTEP)
            self._light_sensors.append(sensor)

        # Initialize camera
        self._camera = self._robot.getDevice("camera")
        if self._camera:
            self._camera.enable(TIMESTEP)

        # Step once to get initial sensor readings
        self._robot.step(TIMESTEP)

        self._devices = {DEVICE_ID: self._build_robot_cdd()}

        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "webots_r2025a",
            "model": "e-puck",
            "timestep_ms": TIMESTEP,
        }

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")
        props = await asyncio.to_thread(self._read_state)
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
            self._left_motor.setVelocity(fval)
        elif property_name == "right_motor_speed":
            fval = float(value)
            low, high = MOTOR_SPEED_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}]")
            self._right_speed = fval
            self._right_motor.setVelocity(fval)
        else:
            raise ValueError(
                f"Cannot set property: {property_name}. "
                "Writable: left_motor_speed, right_motor_speed"
            )

        # Step simulation to apply changes
        await asyncio.to_thread(self._robot.step, TIMESTEP)
        self._sim_step += 1

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
            speed = params.get("speed", 3.0)
            steps = params.get("steps", 10)
            self._left_motor.setVelocity(speed)
            self._right_motor.setVelocity(speed)
            self._left_speed = speed
            self._right_speed = speed
            for _ in range(steps):
                await asyncio.to_thread(self._robot.step, TIMESTEP)
                self._sim_step += 1

        elif action == "backward":
            speed = params.get("speed", 3.0)
            steps = params.get("steps", 10)
            self._left_motor.setVelocity(-speed)
            self._right_motor.setVelocity(-speed)
            self._left_speed = -speed
            self._right_speed = -speed
            for _ in range(steps):
                await asyncio.to_thread(self._robot.step, TIMESTEP)
                self._sim_step += 1

        elif action == "turn_left":
            speed = params.get("speed", 2.0)
            steps = params.get("steps", 8)
            self._left_motor.setVelocity(-speed)
            self._right_motor.setVelocity(speed)
            self._left_speed = -speed
            self._right_speed = speed
            for _ in range(steps):
                await asyncio.to_thread(self._robot.step, TIMESTEP)
                self._sim_step += 1

        elif action == "turn_right":
            speed = params.get("speed", 2.0)
            steps = params.get("steps", 8)
            self._left_motor.setVelocity(speed)
            self._right_motor.setVelocity(-speed)
            self._left_speed = speed
            self._right_speed = -speed
            for _ in range(steps):
                await asyncio.to_thread(self._robot.step, TIMESTEP)
                self._sim_step += 1

        elif action == "stop":
            self._left_motor.setVelocity(0.0)
            self._right_motor.setVelocity(0.0)
            self._left_speed = 0.0
            self._right_speed = 0.0
            await asyncio.to_thread(self._robot.step, TIMESTEP)
            self._sim_step += 1

        elif action == "wall_follow":
            side = params.get("side", "right")
            steps = params.get("steps", 20)
            for _ in range(steps):
                if side == "right":
                    sensor_val = self._distance_sensors[2].getValue()
                    if sensor_val > 80:  # wall detected (Webots: higher=closer)
                        self._left_motor.setVelocity(3.0)
                        self._right_motor.setVelocity(1.0)
                    else:
                        self._left_motor.setVelocity(1.0)
                        self._right_motor.setVelocity(3.0)
                else:
                    sensor_val = self._distance_sensors[6].getValue()
                    if sensor_val > 80:
                        self._left_motor.setVelocity(1.0)
                        self._right_motor.setVelocity(3.0)
                    else:
                        self._left_motor.setVelocity(3.0)
                        self._right_motor.setVelocity(1.0)
                await asyncio.to_thread(self._robot.step, TIMESTEP)
                self._sim_step += 1

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params}

    async def capture_image(self) -> str:
        """Capture image from e-puck camera."""
        if self._camera is None:
            # Fallback
            img = Image.new("RGB", (640, 480), color=(128, 128, 128))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()

        await asyncio.to_thread(self._robot.step, TIMESTEP)
        width = self._camera.getWidth()
        height = self._camera.getHeight()
        image_data = self._camera.getImage()

        # Convert Webots BGRA image to PIL RGB
        img = Image.new("RGB", (width, height))
        pixels = img.load()
        for y in range(height):
            for x in range(width):
                idx = (y * width + x) * 4
                b = image_data[idx]
                g = image_data[idx + 1]
                r = image_data[idx + 2]
                pixels[x, y] = (r, g, b)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    async def shutdown(self):
        """Clean shutdown of Webots controller."""
        if self._robot:
            self._left_motor.setVelocity(0.0)
            self._right_motor.setVelocity(0.0)
            self._robot.step(TIMESTEP)

    # --- Private methods ---

    def _read_state(self) -> dict[str, Any]:
        props: dict[str, Any] = {
            "left_motor_speed": self._left_speed,
            "right_motor_speed": self._right_speed,
            "position": list(self._position),
            "heading": self._theta,
            "sim_step": self._sim_step,
        }
        # Read distance sensors
        for i, name in enumerate(DISTANCE_SENSOR_NAMES):
            props[name] = self._distance_sensors[i].getValue()
        # Read light sensors
        for i, name in enumerate(LIGHT_SENSOR_NAMES):
            props[name] = self._light_sensors[i].getValue()
        return props

    def _build_robot_cdd(self) -> CDD:
        capabilities = []

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

        for name in DISTANCE_SENSOR_NAMES:
            capabilities.append(DeviceCapability(
                name=name,
                cap_type="float",
                readable=True,
                writable=False,
                safety_level=SafetyLevel.LOW,
                value_range={"min": DISTANCE_SENSOR_RANGE[0], "max": DISTANCE_SENSOR_RANGE[1]},
                description=f"Infrared distance sensor {name} (0=far, 4095=close)",
            ))

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
            metadata={"engine": "webots_r2025a", "robot": "e-puck"},
        )
