"""Mock Gazebo adapter for testing without Gazebo/ROS2 dependency."""

from __future__ import annotations

import base64
import io
import math
import time
from typing import Any

from PIL import Image, ImageDraw

from harness.adapter import Adapter
from harness.adapters.gazebo.config import (
    ACTIONS,
    ANGULAR_VEL_RANGE,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    LIDAR_MAX_RANGE,
    LIDAR_NUM_RAYS,
    LINEAR_VEL_RANGE,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class MockGazeboAdapter(Adapter):
    """Mock adapter simulating TurtleBot3 without Gazebo/ROS2 dependency."""

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._position = [0.0, 0.0]  # x, y in meters
        self._theta = 0.0  # heading in radians
        self._linear_vel = 0.0
        self._angular_vel = 0.0
        self._lidar_scan = [LIDAR_MAX_RANGE] * LIDAR_NUM_RAYS
        self._imu_orientation = [0.0, 0.0, 0.0]  # roll, pitch, yaw
        self._imu_angular_vel = [0.0, 0.0, 0.0]
        self._devices: dict[str, CDD] = {}
        self._scene = ""
        self._navigating = False
        self._nav_target: list[float] | None = None

    @property
    def is_initialized(self) -> bool:
        return bool(self._devices)

    async def initialize(self, scene: str = "empty_world") -> dict[str, Any]:
        self._scene = scene
        self._devices = {DEVICE_ID: self._build_robot_cdd()}
        self._position = [0.0, 0.0]
        self._theta = 0.0
        self._linear_vel = 0.0
        self._angular_vel = 0.0
        self._lidar_scan = [LIDAR_MAX_RANGE] * LIDAR_NUM_RAYS
        self._navigating = False
        self._nav_target = None
        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "gazebo_mock",
            "model": "turtlebot3_burger",
            "world": scene,
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

        if property_name == "linear_velocity":
            fval = float(value)
            low, high = LINEAR_VEL_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}] for linear_velocity")
            self._linear_vel = fval
            # Update position based on velocity (simulate one timestep of 0.1s)
            self._position[0] += self._linear_vel * math.cos(self._theta) * 0.1
            self._position[1] += self._linear_vel * math.sin(self._theta) * 0.1
        elif property_name == "angular_velocity":
            fval = float(value)
            low, high = ANGULAR_VEL_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}] for angular_velocity")
            self._angular_vel = fval
            self._theta += self._angular_vel * 0.1
        else:
            raise ValueError(f"Cannot set property: {property_name}. Writable: linear_velocity, angular_velocity")

        self._imu_orientation[2] = self._theta
        self._imu_angular_vel[2] = self._angular_vel

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

        if action == "navigate_to":
            target_x = params.get("x", 1.0)
            target_y = params.get("y", 0.0)
            self._nav_target = [target_x, target_y]
            self._navigating = True
            # Simulate partial movement toward target
            dx = target_x - self._position[0]
            dy = target_y - self._position[1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > 0.01:
                self._theta = math.atan2(dy, dx)
                step = min(dist, 0.5)  # Move at most 0.5m per action
                self._position[0] += step * math.cos(self._theta)
                self._position[1] += step * math.sin(self._theta)
                self._linear_vel = 0.22  # typical TurtleBot3 cruise speed
            if dist <= 0.5:
                self._navigating = False
                self._linear_vel = 0.0
                self._nav_target = None

        elif action == "stop":
            self._linear_vel = 0.0
            self._angular_vel = 0.0
            self._navigating = False
            self._nav_target = None

        elif action == "rotate":
            angle = params.get("angle", math.pi / 2)
            self._theta += angle
            # Normalize theta to [-pi, pi]
            self._theta = math.atan2(math.sin(self._theta), math.cos(self._theta))
            self._angular_vel = 0.0

        elif action == "dock":
            # Simulate docking: move to origin
            self._position = [0.0, 0.0]
            self._theta = 0.0
            self._linear_vel = 0.0
            self._angular_vel = 0.0

        self._imu_orientation[2] = self._theta
        self._imu_angular_vel[2] = self._angular_vel

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params, "mock": True}

    async def capture_image(self) -> str:
        img = Image.new("RGB", (640, 480), color=(220, 220, 220))
        draw = ImageDraw.Draw(img)

        # Draw grid floor
        for gx in range(0, 640, 40):
            draw.line([gx, 0, gx, 480], fill=(200, 200, 200), width=1)
        for gy in range(0, 480, 40):
            draw.line([0, gy, 640, gy], fill=(200, 200, 200), width=1)

        # Robot position in pixel space (center of image = origin, 40px per meter)
        scale = 40
        cx = 320 + int(self._position[0] * scale)
        cy = 240 - int(self._position[1] * scale)

        # Draw lidar fan (simplified: draw rays at 0, 90, 180, 270 degrees)
        for i in range(0, LIDAR_NUM_RAYS, 15):
            angle = self._theta + math.radians(i)
            ray_len = self._lidar_scan[i] * scale
            ex = cx + int(ray_len * math.cos(angle))
            ey = cy - int(ray_len * math.sin(angle))
            draw.line([cx, cy, ex, ey], fill=(200, 230, 255), width=1)

        # Draw robot body (circle)
        robot_radius = 10
        draw.ellipse(
            [cx - robot_radius, cy - robot_radius, cx + robot_radius, cy + robot_radius],
            fill=(50, 50, 200),
            outline=(20, 20, 100),
        )

        # Draw heading arrow
        arrow_len = 20
        ax = cx + int(arrow_len * math.cos(self._theta))
        ay = cy - int(arrow_len * math.sin(self._theta))
        draw.line([cx, cy, ax, ay], fill=(255, 50, 50), width=2)

        # Draw navigation target if active
        if self._nav_target:
            tx = 320 + int(self._nav_target[0] * scale)
            ty = 240 - int(self._nav_target[1] * scale)
            draw.ellipse([tx - 5, ty - 5, tx + 5, ty + 5], fill=(0, 200, 0))

        # Info text
        draw.text((10, 10), f"TurtleBot3 (Mock) - {self._scene}", fill=(0, 0, 0))
        draw.text((10, 30), f"Pos: ({self._position[0]:.2f}, {self._position[1]:.2f})", fill=(0, 0, 0))
        draw.text((10, 50), f"Heading: {math.degrees(self._theta):.1f} deg", fill=(0, 0, 0))
        draw.text((10, 70), f"Vel: lin={self._linear_vel:.2f} ang={self._angular_vel:.2f}", fill=(0, 0, 0))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def _read_state(self) -> dict[str, Any]:
        return {
            "linear_velocity": self._linear_vel,
            "angular_velocity": self._angular_vel,
            "position": list(self._position),
            "heading": self._theta,
            "lidar_scan": list(self._lidar_scan),
            "imu_orientation": list(self._imu_orientation),
            "imu_angular_velocity": list(self._imu_angular_vel),
            "odometry_position": list(self._position) + [0.0],
            "odometry_velocity": [
                self._linear_vel * math.cos(self._theta),
                self._linear_vel * math.sin(self._theta),
                0.0,
            ],
            "navigating": self._navigating,
            "nav_target": self._nav_target,
        }

    def _build_robot_cdd(self) -> CDD:
        capabilities = []

        # Writable velocity properties
        capabilities.append(DeviceCapability(
            name="linear_velocity",
            cap_type="float",
            readable=True,
            writable=True,
            safety_level=SafetyLevel.HIGH,
            value_range={"min": LINEAR_VEL_RANGE[0], "max": LINEAR_VEL_RANGE[1]},
            description="Linear velocity command (m/s)",
        ))
        capabilities.append(DeviceCapability(
            name="angular_velocity",
            cap_type="float",
            readable=True,
            writable=True,
            safety_level=SafetyLevel.HIGH,
            value_range={"min": ANGULAR_VEL_RANGE[0], "max": ANGULAR_VEL_RANGE[1]},
            description="Angular velocity command (rad/s)",
        ))

        # Read-only sensor properties
        capabilities.append(DeviceCapability(
            name="lidar_scan",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            value_range={"min": 0.0, "max": LIDAR_MAX_RANGE},
            description=f"LiDAR scan: {LIDAR_NUM_RAYS} range values (meters)",
        ))
        capabilities.append(DeviceCapability(
            name="imu_orientation",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="IMU orientation [roll, pitch, yaw] in radians",
        ))
        capabilities.append(DeviceCapability(
            name="imu_angular_velocity",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="IMU angular velocity [wx, wy, wz] rad/s",
        ))
        capabilities.append(DeviceCapability(
            name="odometry_position",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="Odometry position [x, y, z] in meters",
        ))
        capabilities.append(DeviceCapability(
            name="odometry_velocity",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="Odometry linear velocity [vx, vy, vz] m/s",
        ))
        capabilities.append(DeviceCapability(
            name="camera",
            cap_type="boolean",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="Camera image availability (use capture_image to retrieve)",
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
            metadata={"engine": "gazebo_mock", "robot": "turtlebot3_burger"},
        )
