"""MuJoCo adapter for Unitree Go1 quadruped robot."""

from __future__ import annotations

import asyncio
import base64
import io
import math
import os
import time
from pathlib import Path
from typing import Any

import mujoco
import numpy as np
from PIL import Image

from harness.adapter import Adapter
from harness.adapters.mujoco_go1.locomotion import GaitController
from harness.adapters.mujoco_go1.robot_config import (
    ACTIONS,
    ACTUATOR_NAMES,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    JOINT_NAMES,
    STAND_POSE,
    get_joint_range,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel

os.environ.setdefault("MUJOCO_GL", "egl")

_MODEL_DIR = Path(__file__).parent / "models" / "unitree_go1"


class MuJoCoAdapter(Adapter):
    """Adapter bridging Harness capabilities to MuJoCo simulation of Unitree Go1."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        model_path: str | None = None,
        sim_dt: float = 0.002,
        control_dt: float = 0.02,
    ):
        self._event_bus = event_bus or EventBus()
        self._model_path = model_path or str(_MODEL_DIR / "scene.xml")
        self._sim_dt = sim_dt
        self._control_dt = control_dt
        self._model: mujoco.MjModel | None = None
        self._data: mujoco.MjData | None = None
        self._devices: dict[str, CDD] = {}
        self._scene: str = ""
        self._sim_task: asyncio.Task | None = None
        self._running = False
        self._lock = asyncio.Lock()
        self._renderer: mujoco.Renderer | None = None
        self._gait = GaitController()
        self._current_action = "stand"

    @property
    def is_initialized(self) -> bool:
        return self._model is not None

    async def initialize(self, scene: str = "flat_ground") -> dict[str, Any]:
        self._scene = scene
        self._model = mujoco.MjModel.from_xml_path(self._model_path)
        self._data = mujoco.MjData(self._model)
        mujoco.mj_resetData(self._model, self._data)
        self._apply_pose(STAND_POSE)
        for _ in range(200):
            mujoco.mj_step(self._model, self._data)
        self._devices = {DEVICE_ID: self._build_robot_cdd()}
        self._running = True
        self._sim_task = asyncio.create_task(self._simulation_loop())
        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "mujoco",
            "model": "unitree_go1",
            "actuators": len(ACTUATOR_NAMES),
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
        if not property_name.startswith("joint_"):
            raise ValueError(f"Cannot set non-joint property: {property_name}")

        actuator_name = property_name[6:]  # strip "joint_" prefix
        actuator_idx = self._get_actuator_index(actuator_name)
        float_value = float(value)
        low, high = get_joint_range(actuator_name)
        if not (low <= float_value <= high):
            raise ValueError(f"Value {float_value} out of range [{low}, {high}] for {actuator_name}")

        async with self._lock:
            self._data.ctrl[actuator_idx] = float_value

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
            await self._execute_pose_transition(STAND_POSE, duration=params.get("duration", 1.0))
        elif action == "sit":
            from harness.adapters.mujoco_go1.robot_config import SIT_POSE
            await self._execute_pose_transition(SIT_POSE, duration=params.get("duration", 1.5))
        elif action == "walk_forward":
            await self._execute_gait("walk", params.get("speed", 0.3), params.get("duration", 2.0))
        elif action == "walk_backward":
            await self._execute_gait("walk", -params.get("speed", 0.3), params.get("duration", 2.0))
        elif action == "turn_left":
            await self._execute_gait("turn", 1.0, params.get("duration", 1.5))
        elif action == "turn_right":
            await self._execute_gait("turn", -1.0, params.get("duration", 1.5))
        elif action == "trot":
            await self._execute_gait("trot", params.get("speed", 0.6), params.get("duration", 2.0))
        elif action == "stop":
            await self._execute_pose_transition(STAND_POSE, duration=0.5)
            self._current_action = "stand"

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params}

    async def capture_image(self) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._render_offscreen)

    # --- Private methods ---

    async def _simulation_loop(self):
        steps_per_control = int(self._control_dt / self._sim_dt)
        while self._running:
            async with self._lock:
                for _ in range(steps_per_control):
                    mujoco.mj_step(self._model, self._data)
            await asyncio.sleep(self._control_dt)

    async def _execute_pose_transition(self, target_pose: list[float], duration: float = 1.0):
        steps = int(duration / self._control_dt)
        async with self._lock:
            current = [self._data.ctrl[i] for i in range(self._model.nu)]
        for step in range(steps):
            t = (step + 1) / steps
            interp = [current[i] + t * (target_pose[i] - current[i]) for i in range(12)]
            async with self._lock:
                for i in range(12):
                    self._data.ctrl[i] = interp[i]
            await asyncio.sleep(self._control_dt)

    async def _execute_gait(self, gait_type: str, speed_or_dir: float, duration: float):
        steps = int(duration / self._control_dt)
        freq = 2.0 * math.pi * 2.0  # 2 Hz gait cycle
        for step in range(steps):
            phase = freq * step * self._control_dt
            if gait_type == "walk":
                targets = self._gait.walk(phase, speed=abs(speed_or_dir))
            elif gait_type == "trot":
                targets = self._gait.trot(phase, speed=abs(speed_or_dir))
            elif gait_type == "turn":
                targets = self._gait.turn(phase, direction=speed_or_dir)
            else:
                targets = STAND_POSE
            async with self._lock:
                for i in range(12):
                    self._data.ctrl[i] = targets[i]
            await asyncio.sleep(self._control_dt)

    def _apply_pose(self, pose: list[float]):
        for i in range(min(len(pose), self._model.nu)):
            self._data.ctrl[i] = pose[i]

    def _get_actuator_index(self, name: str) -> int:
        try:
            return ACTUATOR_NAMES.index(name)
        except ValueError:
            raise ValueError(f"Unknown actuator: {name}. Available: {ACTUATOR_NAMES}")

    def _read_state(self) -> dict[str, Any]:
        props = {}
        # Joint positions (from qpos, skip 7 for free joint: 3 pos + 4 quat)
        for i, name in enumerate(ACTUATOR_NAMES):
            props[f"joint_{name}"] = float(self._data.qpos[7 + i])
        # Body position (first 3 of qpos)
        props["body_position"] = [float(self._data.qpos[j]) for j in range(3)]
        # Body orientation (quaternion -> euler)
        quat = self._data.qpos[3:7]
        props["body_orientation"] = self._quat_to_euler(quat)
        # Body velocity
        props["body_velocity"] = [float(self._data.qvel[j]) for j in range(3)]
        # Angular velocity
        props["imu_angular_velocity"] = [float(self._data.qvel[j]) for j in range(3, 6)]
        # Foot contacts (check if z-force > threshold on geom contacts)
        props["foot_contacts"] = self._check_foot_contacts()
        props["current_action"] = self._current_action
        return props

    def _check_foot_contacts(self) -> list[bool]:
        contacts = [False, False, False, False]
        foot_geoms = ["FR", "FL", "RR", "RL"]
        for i in range(self._data.ncon):
            contact = self._data.contact[i]
            geom1 = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_GEOM, contact.geom1)
            geom2 = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_GEOM, contact.geom2)
            for idx, foot in enumerate(foot_geoms):
                if (geom1 == foot or geom2 == foot):
                    contacts[idx] = True
        return contacts

    @staticmethod
    def _quat_to_euler(quat) -> list[float]:
        w, x, y, z = float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3])
        sinr_cosp = 2 * (w * x + y * z)
        cosr_cosp = 1 - 2 * (x * x + y * y)
        roll = math.atan2(sinr_cosp, cosr_cosp)
        sinp = 2 * (w * y - z * x)
        pitch = math.asin(max(-1, min(1, sinp)))
        siny_cosp = 2 * (w * z + x * y)
        cosy_cosp = 1 - 2 * (y * y + z * z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        return [roll, pitch, yaw]

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
        # Read-only body state
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
            metadata={"engine": "mujoco", "model_file": str(self._model_path)},
        )

    def _render_offscreen(self) -> str:
        if self._renderer is None:
            self._renderer = mujoco.Renderer(self._model, height=480, width=640)
        self._renderer.update_scene(self._data)
        img = self._renderer.render()
        pil_img = Image.fromarray(img)
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    async def shutdown(self):
        self._running = False
        if self._sim_task:
            self._sim_task.cancel()
            try:
                await self._sim_task
            except asyncio.CancelledError:
                pass
        if self._renderer:
            self._renderer.close()
            self._renderer = None
