"""Gazebo Harmonic adapter for TurtleBot3 via gz-transport Python bindings."""

from __future__ import annotations

import asyncio
import base64
import io
import math
import subprocess
import time
from typing import Any

from PIL import Image

from harness.adapter import Adapter
from harness.adapters.gazebo.config import (
    ACTIONS,
    ANGULAR_VEL_RANGE,
    DEFAULT_WORLD,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    LIDAR_MAX_RANGE,
    LIDAR_NUM_RAYS,
    LINEAR_VEL_RANGE,
    TOPICS,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel

try:
    from gz.transport import Node
    from gz.msgs.twist_pb2 import Twist
    from gz.msgs.vector3d_pb2 import Vector3d
except ImportError:
    Node = None
    Twist = None
    Vector3d = None


class GazeboAdapter(Adapter):
    """Adapter bridging Harness to Gazebo Harmonic simulation of TurtleBot3."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        world_file: str | None = None,
    ):
        self._event_bus = event_bus or EventBus()
        self._world_file = world_file or DEFAULT_WORLD
        self._gz_process: subprocess.Popen | None = None
        self._node: Any = None
        self._cmd_vel_pub: Any = None
        self._devices: dict[str, CDD] = {}
        self._scene = ""

        # Cached state from subscriptions
        self._position = [0.0, 0.0, 0.0]
        self._orientation = [0.0, 0.0, 0.0]
        self._linear_vel = 0.0
        self._angular_vel = 0.0
        self._lidar_scan = [LIDAR_MAX_RANGE] * LIDAR_NUM_RAYS
        self._imu_orientation = [0.0, 0.0, 0.0]
        self._imu_angular_vel = [0.0, 0.0, 0.0]
        self._lock = asyncio.Lock()

    @property
    def is_initialized(self) -> bool:
        return self._node is not None

    async def initialize(self, scene: str = "empty_world") -> dict[str, Any]:
        if Node is None:
            raise ImportError(
                "gz-transport Python bindings not found. "
                "Install with: pip install gz-transport13 (or appropriate version)"
            )

        self._scene = scene
        world = self._world_file if scene == "empty_world" else f"{scene}.sdf"

        # Launch Gazebo sim process
        self._gz_process = subprocess.Popen(
            ["gz", "sim", "-r", world],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Wait for Gazebo to start
        await asyncio.sleep(3.0)

        # Create gz-transport node
        self._node = Node()

        # Publisher for velocity commands
        self._cmd_vel_pub = self._node.advertise(TOPICS["cmd_vel"], Twist)

        # Subscribe to sensor topics
        self._node.subscribe(TOPICS["odom"], self._odom_callback)
        self._node.subscribe(TOPICS["scan"], self._scan_callback)
        self._node.subscribe(TOPICS["imu"], self._imu_callback)

        self._devices = {DEVICE_ID: self._build_robot_cdd()}

        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "gazebo_harmonic",
            "model": "turtlebot3_burger",
            "world": world,
            "pid": self._gz_process.pid,
        }

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")
        async with self._lock:
            props = self._read_state()
        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")

        if property_name == "linear_velocity":
            fval = float(value)
            low, high = LINEAR_VEL_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}]")
            self._linear_vel = fval
        elif property_name == "angular_velocity":
            fval = float(value)
            low, high = ANGULAR_VEL_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}]")
            self._angular_vel = fval
        else:
            raise ValueError(f"Cannot set property: {property_name}")

        # Publish Twist message
        self._publish_cmd_vel(self._linear_vel, self._angular_vel)

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
            await self._navigate_to(target_x, target_y)

        elif action == "stop":
            self._linear_vel = 0.0
            self._angular_vel = 0.0
            self._publish_cmd_vel(0.0, 0.0)

        elif action == "rotate":
            angle = params.get("angle", math.pi / 2)
            duration = abs(angle) / 1.0  # rotate at 1 rad/s
            direction = 1.0 if angle > 0 else -1.0
            self._publish_cmd_vel(0.0, direction * 1.0)
            await asyncio.sleep(duration)
            self._publish_cmd_vel(0.0, 0.0)

        elif action == "dock":
            # Simple docking: navigate to origin
            await self._navigate_to(0.0, 0.0)

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params}

    async def capture_image(self) -> str:
        """Capture image from Gazebo camera topic via gz-transport."""
        # Request image via gz service or topic snapshot
        # For simplicity, use gz command-line tool to capture
        result = await asyncio.to_thread(
            subprocess.run,
            ["gz", "topic", "-e", "-t", TOPICS["camera"], "-n", "1"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            # Parse raw image bytes from gz-transport serialized message
            # Fallback: render a simple representation
            return base64.b64encode(result.stdout).decode()

        # Fallback: simple PIL rendering
        img = Image.new("RGB", (640, 480), color=(100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    async def shutdown(self):
        """Shutdown Gazebo process and clean up."""
        if self._gz_process:
            self._gz_process.terminate()
            self._gz_process.wait(timeout=10)
            self._gz_process = None
        self._node = None

    # --- Private methods ---

    def _publish_cmd_vel(self, linear: float, angular: float):
        """Publish a Twist message to /cmd_vel."""
        if self._cmd_vel_pub is None:
            return
        msg = Twist()
        msg.linear.x = linear
        msg.angular.z = angular
        self._cmd_vel_pub.publish(msg)

    async def _navigate_to(self, target_x: float, target_y: float):
        """Simple proportional navigation controller."""
        for _ in range(200):  # Max 200 control steps
            dx = target_x - self._position[0]
            dy = target_y - self._position[1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 0.05:
                break
            target_angle = math.atan2(dy, dx)
            angle_error = target_angle - self._orientation[2]
            # Normalize angle error
            angle_error = math.atan2(math.sin(angle_error), math.cos(angle_error))

            if abs(angle_error) > 0.1:
                self._publish_cmd_vel(0.0, min(max(angle_error, -1.82), 1.82))
            else:
                speed = min(0.22, dist)
                self._publish_cmd_vel(speed, angle_error * 0.5)
            await asyncio.sleep(0.05)

        self._publish_cmd_vel(0.0, 0.0)

    def _odom_callback(self, msg):
        """Handle odometry messages."""
        self._position = [msg.pose.position.x, msg.pose.position.y, msg.pose.position.z]
        # Extract yaw from quaternion
        q = msg.pose.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        self._orientation = [0.0, 0.0, yaw]

    def _scan_callback(self, msg):
        """Handle LaserScan messages."""
        self._lidar_scan = list(msg.ranges[:LIDAR_NUM_RAYS])

    def _imu_callback(self, msg):
        """Handle IMU messages."""
        q = msg.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        self._imu_orientation = [0.0, 0.0, yaw]
        self._imu_angular_vel = [
            msg.angular_velocity.x,
            msg.angular_velocity.y,
            msg.angular_velocity.z,
        ]

    def _read_state(self) -> dict[str, Any]:
        return {
            "linear_velocity": self._linear_vel,
            "angular_velocity": self._angular_vel,
            "position": list(self._position),
            "heading": self._orientation[2],
            "lidar_scan": list(self._lidar_scan),
            "imu_orientation": list(self._imu_orientation),
            "imu_angular_velocity": list(self._imu_angular_vel),
            "odometry_position": list(self._position),
            "odometry_velocity": [
                self._linear_vel * math.cos(self._orientation[2]),
                self._linear_vel * math.sin(self._orientation[2]),
                0.0,
            ],
        }

    def _build_robot_cdd(self) -> CDD:
        capabilities = []

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
            description="Camera image (use capture_image to retrieve)",
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
            metadata={"engine": "gazebo_harmonic", "world": self._world_file},
        )
