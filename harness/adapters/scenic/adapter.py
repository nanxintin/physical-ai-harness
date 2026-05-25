"""Scenic adapter for autonomous driving scenario generation and simulation."""

from __future__ import annotations

import asyncio
import base64
import io
import math
import time
from pathlib import Path
from typing import Any

from PIL import Image

from harness.adapter import Adapter
from harness.adapters.scenic.config import (
    ACTIONS,
    BRAKE_RANGE,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    SCENARIOS,
    SIM_TIMESTEP,
    SPEED_RANGE,
    STEERING_RANGE,
    THROTTLE_RANGE,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel

try:
    import scenic
    from scenic.core.scenarios import Scene
    from scenic.simulators.carla import CarlaSimulator
except ImportError:
    scenic = None
    Scene = None
    CarlaSimulator = None


class ScenicAdapter(Adapter):
    """Adapter bridging Harness to Scenic probabilistic scenario simulation."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        scenario_dir: str | None = None,
        simulator_type: str = "carla",
    ):
        self._event_bus = event_bus or EventBus()
        self._scenario_dir = Path(scenario_dir) if scenario_dir else Path.cwd() / "scenarios"
        self._simulator_type = simulator_type
        self._scenario: Any = None
        self._simulation: Any = None
        self._scene_obj: Any = None
        self._ego: Any = None
        self._devices: dict[str, CDD] = {}
        self._scene_name = ""
        self._sim_step = 0
        self._scenario_active = False

        # Cached state
        self._speed = 0.0
        self._steering = 0.0
        self._throttle = 0.0
        self._brake = 0.0
        self._position = [0.0, 0.0]
        self._heading = 0.0
        self._detected_objects: list[dict[str, Any]] = []

    @property
    def is_initialized(self) -> bool:
        return self._scenario is not None

    async def initialize(self, scene: str = "lane_follow") -> dict[str, Any]:
        if scenic is None:
            raise ImportError(
                "Scenic not found. Install with: pip install scenic"
            )

        self._scene_name = scene
        scenario_file = self._scenario_dir / f"{scene}.scenic"
        if not scenario_file.exists():
            raise FileNotFoundError(f"Scenario file not found: {scenario_file}")

        # Load and compile the Scenic scenario
        self._scenario = await asyncio.to_thread(
            scenic.scenarioFromFile, str(scenario_file)
        )

        self._devices = {DEVICE_ID: self._build_vehicle_cdd()}

        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "scenic",
            "scenario_file": str(scenario_file),
            "available_scenarios": SCENARIOS,
            "simulator": self._simulator_type,
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
            if self._ego:
                self._ego.speed = fval
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
            scenario_name = params.get("scenario", self._scene_name)
            # Generate a scene from the scenario
            self._scene_obj, _ = await asyncio.to_thread(self._scenario.generate)
            # Create simulation from the scene
            if self._simulator_type == "carla" and CarlaSimulator:
                simulator = CarlaSimulator(
                    carla_map=params.get("map", "Town01"),
                    timestep=SIM_TIMESTEP,
                )
                self._simulation = simulator.simulate(self._scene_obj)
            self._ego = self._scene_obj.egoObject
            self._scenario_active = True
            self._sim_step = 0
            self._update_from_ego()

        elif action == "step_scenario":
            if self._simulation and self._scenario_active:
                result = await asyncio.to_thread(next, self._simulation, None)
                if result is None:
                    self._scenario_active = False
                else:
                    self._sim_step += 1
                    self._update_from_ego()

        elif action == "reset_scenario":
            self._scenario_active = False
            self._simulation = None
            self._scene_obj = None
            self._ego = None
            self._sim_step = 0
            self._speed = 0.0
            self._position = [0.0, 0.0]
            self._heading = 0.0
            self._detected_objects = []

        elif action == "change_lane":
            direction = params.get("direction", "left")
            if self._ego:
                # Apply lateral offset through the simulator
                offset = 3.7 if direction == "left" else -3.7
                self._position[1] += offset
                self._sim_step += 1

        elif action == "emergency_brake":
            self._brake = 1.0
            self._throttle = 0.0
            self._speed = 0.0
            if self._ego:
                self._ego.speed = 0.0

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params}

    async def capture_image(self) -> str:
        """Capture image from the scenario simulation."""
        if self._simulation and hasattr(self._simulation, 'render'):
            # Try to get a rendered image from the simulator
            img_data = await asyncio.to_thread(self._simulation.render)
            if img_data is not None:
                buf = io.BytesIO()
                Image.fromarray(img_data).save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode()

        # Fallback: simple visualization
        img = Image.new("RGB", (800, 400), color=(80, 80, 80))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    async def shutdown(self):
        """Clean up Scenic simulation resources."""
        self._scenario_active = False
        if self._simulation:
            try:
                await asyncio.to_thread(self._simulation.close)
            except Exception:
                pass
        self._simulation = None
        self._scene_obj = None
        self._ego = None

    # --- Private methods ---

    def _update_from_ego(self):
        """Update cached state from the Scenic ego object."""
        if self._ego is None:
            return
        try:
            pos = self._ego.position
            self._position = [float(pos.x), float(pos.y)]
            self._heading = float(self._ego.heading)
            self._speed = float(getattr(self._ego, 'speed', 0.0))
        except (AttributeError, TypeError):
            pass

        # Detect other objects in the scene
        self._detected_objects = []
        if self._scene_obj:
            for obj in self._scene_obj.objects:
                if obj is self._ego:
                    continue
                try:
                    obj_pos = obj.position
                    dx = float(obj_pos.x) - self._position[0]
                    dy = float(obj_pos.y) - self._position[1]
                    distance = math.sqrt(dx * dx + dy * dy)
                    if distance < 100.0:
                        self._detected_objects.append({
                            "type": getattr(obj, 'type', 'unknown'),
                            "distance": distance,
                            "position": [float(obj_pos.x), float(obj_pos.y)],
                            "relative_speed": getattr(obj, 'speed', 0.0) - self._speed,
                        })
                except (AttributeError, TypeError):
                    pass

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
            "scenario": self._scene_name,
            "scenario_active": self._scenario_active,
            "sim_step": self._sim_step,
            "sim_time": self._sim_step * SIM_TIMESTEP,
        }

    def _build_vehicle_cdd(self) -> CDD:
        capabilities = []

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
            description="Ego vehicle heading in radians",
        ))
        capabilities.append(DeviceCapability(
            name="detected_objects",
            cap_type="float",
            readable=True,
            writable=False,
            safety_level=SafetyLevel.LOW,
            description="Detected objects [{type, distance, position, relative_speed}]",
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
            description="LiDAR point cloud (list of [x,y,z] points)",
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
            safety_class=SafetyLevel.CRITICAL,
            metadata={
                "engine": "scenic",
                "available_scenarios": SCENARIOS,
                "simulator": self._simulator_type,
            },
        )
