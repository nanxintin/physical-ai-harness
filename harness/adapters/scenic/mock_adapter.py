"""Mock Scenic adapter for testing without Scenic/CARLA dependency."""

from __future__ import annotations

import base64
import io
import math
import time
from typing import Any

from PIL import Image, ImageDraw

from harness.adapter import Adapter
from harness.adapters.scenic.config import (
    ACTIONS,
    BRAKE_RANGE,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    LANE_WIDTH,
    ROAD_LENGTH,
    SCENARIOS,
    SIM_TIMESTEP,
    SPEED_RANGE,
    STEERING_RANGE,
    THROTTLE_RANGE,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class MockScenicAdapter(Adapter):
    """Mock adapter simulating autonomous driving scenarios without Scenic dependency."""

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._position = [0.0, 0.0]  # x (along road), y (lateral)
        self._speed = 0.0
        self._heading = 0.0  # radians (0 = along road)
        self._steering = 0.0
        self._throttle = 0.0
        self._brake = 0.0
        self._devices: dict[str, CDD] = {}
        self._scene = ""
        self._scenario_active = False
        self._sim_step = 0
        self._detected_objects: list[dict[str, Any]] = []
        self._other_vehicles: list[dict[str, Any]] = []

    @property
    def is_initialized(self) -> bool:
        return bool(self._devices)

    async def initialize(self, scene: str = "lane_follow") -> dict[str, Any]:
        self._scene = scene
        self._devices = {DEVICE_ID: self._build_vehicle_cdd()}
        self._reset_state()
        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "scenic_mock",
            "scenario": scene,
            "available_scenarios": SCENARIOS,
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

        fval = float(value)

        if property_name == "speed":
            low, high = SPEED_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}]")
            self._speed = fval
        elif property_name == "steering":
            low, high = STEERING_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}]")
            self._steering = fval
        elif property_name == "throttle":
            low, high = THROTTLE_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}]")
            self._throttle = fval
        elif property_name == "brake":
            low, high = BRAKE_RANGE
            if not (low <= fval <= high):
                raise ValueError(f"Value {fval} out of range [{low}, {high}]")
            self._brake = fval
        else:
            raise ValueError(
                f"Cannot set property: {property_name}. "
                "Writable: speed, steering, throttle, brake"
            )

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": fval,
        })
        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")
        if action not in ACTIONS:
            raise ValueError(f"Unknown action: {action}. Available: {list(ACTIONS.keys())}")

        params = params or {}

        if action == "start_scenario":
            scenario = params.get("scenario", self._scene)
            self._scene = scenario
            self._reset_state()
            self._scenario_active = True
            self._speed = 15.0  # Start at 15 m/s (54 km/h)
            self._throttle = 0.5

        elif action == "step_scenario":
            if self._scenario_active:
                self._step_physics()

        elif action == "reset_scenario":
            self._reset_state()
            self._scenario_active = False

        elif action == "change_lane":
            direction = params.get("direction", "left")
            lane_offset = LANE_WIDTH if direction == "left" else -LANE_WIDTH
            # Simulate smooth lane change over multiple steps
            steps = 20
            dy_per_step = lane_offset / steps
            for _ in range(steps):
                self._position[1] += dy_per_step
                self._step_physics()

        elif action == "emergency_brake":
            self._brake = 1.0
            self._throttle = 0.0
            # Decelerate to zero over multiple steps
            while self._speed > 0.1:
                self._speed = max(0.0, self._speed - 8.0 * SIM_TIMESTEP)  # ~8 m/s^2 deceleration
                self._step_physics()
            self._speed = 0.0
            self._brake = 0.0

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params, "mock": True}

    async def capture_image(self) -> str:
        img = Image.new("RGB", (800, 400), color=(80, 130, 80))  # green background
        draw = ImageDraw.Draw(img)

        # Draw road
        road_top = 100
        road_bottom = 300
        draw.rectangle([0, road_top, 800, road_bottom], fill=(60, 60, 60))

        # Draw lane markings
        num_lanes = 3
        for i in range(1, num_lanes):
            ly = road_top + i * (road_bottom - road_top) // num_lanes
            for dx in range(0, 800, 40):
                draw.rectangle([dx, ly - 1, dx + 20, ly + 1], fill=(255, 255, 255))

        # Draw road edges
        draw.rectangle([0, road_top - 2, 800, road_top], fill=(255, 255, 255))
        draw.rectangle([0, road_bottom, 800, road_bottom + 2], fill=(255, 255, 255))

        # Scale: x maps to horizontal, y maps to vertical lane position
        scale_x = 4.0  # pixels per meter along road
        road_center_y = (road_top + road_bottom) / 2

        # Draw other vehicles
        for obj in self._other_vehicles:
            ox = 400 + int((obj["x"] - self._position[0]) * scale_x)
            oy = int(road_center_y - obj["y"] * 20)
            if 0 <= ox <= 800:
                color = (200, 50, 50) if obj["type"] == "vehicle" else (255, 200, 50)
                draw.rectangle([ox - 15, oy - 8, ox + 15, oy + 8], fill=color, outline=(0, 0, 0))

        # Draw ego vehicle (center-ish)
        ego_x = 400
        ego_y = int(road_center_y - self._position[1] * 20)
        draw.rectangle([ego_x - 18, ego_y - 10, ego_x + 18, ego_y + 10],
                       fill=(50, 100, 220), outline=(20, 50, 150), width=2)
        # Heading indicator
        hx = ego_x + int(25 * math.cos(self._heading))
        hy = ego_y - int(25 * math.sin(self._heading))
        draw.line([ego_x, ego_y, hx, hy], fill=(255, 255, 0), width=2)

        # Info panel
        draw.rectangle([0, 0, 800, 95], fill=(30, 30, 30))
        draw.text((10, 5), f"Scenic (Mock) - {self._scene}", fill=(255, 255, 255))
        draw.text((10, 25), f"Speed: {self._speed:.1f} m/s ({self._speed * 3.6:.1f} km/h)", fill=(200, 255, 200))
        draw.text((10, 45), f"Pos: ({self._position[0]:.1f}, {self._position[1]:.2f}) Heading: {math.degrees(self._heading):.1f} deg", fill=(200, 200, 255))
        draw.text((10, 65), f"Throttle: {self._throttle:.2f} Brake: {self._brake:.2f} Steering: {self._steering:.2f}", fill=(255, 255, 200))
        draw.text((400, 5), f"Step: {self._sim_step}  Objects: {len(self._detected_objects)}", fill=(200, 200, 200))
        status = "ACTIVE" if self._scenario_active else "STOPPED"
        status_color = (100, 255, 100) if self._scenario_active else (255, 100, 100)
        draw.text((400, 25), f"Status: {status}", fill=status_color)

        # Bottom status bar
        draw.rectangle([0, 370, 800, 400], fill=(30, 30, 30))
        det_strs = [o["type"] + "@" + str(int(o["distance"])) + "m" for o in self._detected_objects[:3]]
        draw.text((10, 375), f"Detected: {det_strs}", fill=(200, 200, 200))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def _reset_state(self):
        """Reset all simulation state."""
        self._position = [0.0, 0.0]
        self._speed = 0.0
        self._heading = 0.0
        self._steering = 0.0
        self._throttle = 0.0
        self._brake = 0.0
        self._sim_step = 0
        self._scenario_active = False
        # Initialize mock traffic
        self._other_vehicles = [
            {"type": "vehicle", "x": 30.0, "y": 0.0, "speed": 12.0},
            {"type": "vehicle", "x": 60.0, "y": LANE_WIDTH, "speed": 14.0},
            {"type": "pedestrian", "x": 45.0, "y": -LANE_WIDTH * 1.5, "speed": 1.2},
        ]
        self._update_detected_objects()

    def _step_physics(self):
        """Advance physics by one timestep."""
        dt = SIM_TIMESTEP

        # Apply throttle/brake to speed
        if self._brake > 0:
            decel = self._brake * 10.0  # max 10 m/s^2 braking
            self._speed = max(0.0, self._speed - decel * dt)
        elif self._throttle > 0:
            accel = self._throttle * 4.0  # max 4 m/s^2 acceleration
            self._speed = min(SPEED_RANGE[1], self._speed + accel * dt)

        # Apply steering to heading
        turn_rate = self._steering * 0.5  # max 0.5 rad/s turn rate
        self._heading += turn_rate * dt
        self._heading = math.atan2(math.sin(self._heading), math.cos(self._heading))

        # Update position
        self._position[0] += self._speed * math.cos(self._heading) * dt
        self._position[1] += self._speed * math.sin(self._heading) * dt

        # Move other vehicles
        for v in self._other_vehicles:
            v["x"] += v["speed"] * dt

        # Update detected objects
        self._update_detected_objects()
        self._sim_step += 1

    def _update_detected_objects(self):
        """Update detected objects list based on other vehicles."""
        self._detected_objects = []
        for v in self._other_vehicles:
            dx = v["x"] - self._position[0]
            dy = v["y"] - self._position[1]
            distance = math.sqrt(dx * dx + dy * dy)
            if distance < 100.0:  # detection range 100m
                self._detected_objects.append({
                    "type": v["type"],
                    "distance": distance,
                    "position": [v["x"], v["y"]],
                    "relative_speed": v["speed"] - self._speed,
                })

    def _read_state(self) -> dict[str, Any]:
        return {
            "speed": self._speed,
            "steering": self._steering,
            "throttle": self._throttle,
            "brake": self._brake,
            "ego_position": list(self._position),
            "ego_velocity": [
                self._speed * math.cos(self._heading),
                self._speed * math.sin(self._heading),
            ],
            "ego_heading": self._heading,
            "detected_objects": list(self._detected_objects),
            "scenario": self._scene,
            "scenario_active": self._scenario_active,
            "sim_step": self._sim_step,
            "sim_time": self._sim_step * SIM_TIMESTEP,
        }

    def _build_vehicle_cdd(self) -> CDD:
        capabilities = []

        # Writable vehicle controls
        capabilities.append(DeviceCapability(
            name="speed",
            cap_type="float",
            readable=True,
            writable=True,
            safety_level=SafetyLevel.CRITICAL,
            value_range={"min": SPEED_RANGE[0], "max": SPEED_RANGE[1]},
            description="Vehicle speed (m/s)",
        ))
        capabilities.append(DeviceCapability(
            name="steering",
            cap_type="float",
            readable=True,
            writable=True,
            safety_level=SafetyLevel.CRITICAL,
            value_range={"min": STEERING_RANGE[0], "max": STEERING_RANGE[1]},
            description="Steering input (-1.0=full left, 1.0=full right)",
        ))
        capabilities.append(DeviceCapability(
            name="throttle",
            cap_type="float",
            readable=True,
            writable=True,
            safety_level=SafetyLevel.CRITICAL,
            value_range={"min": THROTTLE_RANGE[0], "max": THROTTLE_RANGE[1]},
            description="Throttle input (0=none, 1=full)",
        ))
        capabilities.append(DeviceCapability(
            name="brake",
            cap_type="float",
            readable=True,
            writable=True,
            safety_level=SafetyLevel.CRITICAL,
            value_range={"min": BRAKE_RANGE[0], "max": BRAKE_RANGE[1]},
            description="Brake input (0=none, 1=full)",
        ))

        # Read-only sensor/state properties
        capabilities.append(DeviceCapability(
            name="ego_position",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="Ego vehicle position [x, y] in meters",
        ))
        capabilities.append(DeviceCapability(
            name="ego_velocity",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="Ego vehicle velocity [vx, vy] in m/s",
        ))
        capabilities.append(DeviceCapability(
            name="ego_heading",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="Ego vehicle heading in radians (0=forward along road)",
        ))
        capabilities.append(DeviceCapability(
            name="detected_objects",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="List of detected objects [{type, distance, position, relative_speed}]",
        ))
        capabilities.append(DeviceCapability(
            name="camera",
            cap_type="boolean",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="Front camera image (use capture_image to retrieve)",
        ))
        capabilities.append(DeviceCapability(
            name="lidar_points",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="LiDAR point cloud (simulated, list of [x,y,z] points)",
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
            safety_class=SafetyLevel.CRITICAL,
            metadata={
                "engine": "scenic_mock",
                "available_scenarios": SCENARIOS,
            },
        )
