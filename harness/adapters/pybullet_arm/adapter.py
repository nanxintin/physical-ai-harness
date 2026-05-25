"""PyBullet adapter for Franka Panda 7-DOF robot arm simulation."""

from __future__ import annotations

import asyncio
import base64
import io
import math
import time
from typing import Any

import numpy as np
import pybullet as p
import pybullet_data
from PIL import Image

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
    PANDA_END_EFFECTOR_INDEX,
    PANDA_GRIPPER_INDICES,
    PANDA_NUM_JOINTS,
    PANDA_URDF,
    SIM_TIMESTEP,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class PyBulletArmAdapter(Adapter):
    """Adapter bridging Harness capabilities to PyBullet simulation of Franka Panda."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        render_mode: str = "DIRECT",
        sim_timestep: float = SIM_TIMESTEP,
    ):
        self._event_bus = event_bus or EventBus()
        self._render_mode = render_mode
        self._sim_timestep = sim_timestep
        self._physics_client: int | None = None
        self._robot_id: int | None = None
        self._plane_id: int | None = None
        self._devices: dict[str, CDD] = {}
        self._scene = ""
        self._lock = asyncio.Lock()

    @property
    def is_initialized(self) -> bool:
        return self._physics_client is not None

    async def initialize(self, scene: str = "table_top") -> dict[str, Any]:
        self._scene = scene

        def _setup():
            # Connect to physics server
            if self._render_mode == "GUI":
                client = p.connect(p.GUI)
            else:
                client = p.connect(p.DIRECT)

            p.setAdditionalSearchPath(pybullet_data.getDataPath())
            p.setGravity(0, 0, -9.81, physicsClientId=client)
            p.setTimeStep(self._sim_timestep, physicsClientId=client)

            # Load ground plane
            plane_id = p.loadURDF("plane.urdf", physicsClientId=client)

            # Load Franka Panda
            robot_id = p.loadURDF(
                PANDA_URDF,
                basePosition=[0, 0, 0],
                useFixedBase=True,
                physicsClientId=client,
            )

            # Set to home position
            for i in range(PANDA_NUM_JOINTS):
                p.resetJointState(robot_id, i, HOME_POSITION[i], physicsClientId=client)

            # Open gripper
            for gi in PANDA_GRIPPER_INDICES:
                p.resetJointState(robot_id, gi, GRIPPER_RANGE[1] / 2, physicsClientId=client)

            return client, robot_id, plane_id

        self._physics_client, self._robot_id, self._plane_id = await asyncio.to_thread(_setup)
        self._devices = {DEVICE_ID: self._build_arm_cdd()}

        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "pybullet",
            "model": "franka_panda",
            "joints": PANDA_NUM_JOINTS,
        }

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")
        async with self._lock:
            props = await asyncio.to_thread(self._read_state)
        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")

        fval = float(value)

        if property_name == "gripper_width":
            if not (GRIPPER_RANGE[0] <= fval <= GRIPPER_RANGE[1]):
                raise ValueError(
                    f"Gripper width {fval} out of range [{GRIPPER_RANGE[0]}, {GRIPPER_RANGE[1]}]"
                )
            async with self._lock:
                await asyncio.to_thread(self._set_gripper, fval)
        elif property_name in JOINT_NAMES:
            idx = JOINT_NAMES.index(property_name)
            low, high = JOINT_RANGES[property_name]
            if not (low <= fval <= high):
                raise ValueError(f"Joint value {fval} out of range [{low}, {high}] for {property_name}")
            async with self._lock:
                await asyncio.to_thread(self._set_joint, idx, fval)
        else:
            raise ValueError(f"Unknown property: {property_name}")

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

        async with self._lock:
            if action == "home":
                await asyncio.to_thread(self._move_to_joint_positions, HOME_POSITION)
            elif action == "open_gripper":
                await asyncio.to_thread(self._set_gripper, GRIPPER_RANGE[1])
            elif action == "close_gripper":
                await asyncio.to_thread(self._set_gripper, GRIPPER_RANGE[0])
            elif action == "pick":
                x = params.get("x", 0.4)
                y = params.get("y", 0.0)
                z = params.get("z", 0.1)
                await asyncio.to_thread(self._execute_pick, x, y, z)
            elif action == "place":
                x = params.get("x", 0.4)
                y = params.get("y", 0.2)
                z = params.get("z", 0.1)
                await asyncio.to_thread(self._execute_place, x, y, z)

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params}

    async def capture_image(self) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._render_image)

    async def shutdown(self):
        """Disconnect from PyBullet."""
        if self._physics_client is not None:
            await asyncio.to_thread(p.disconnect, self._physics_client)
            self._physics_client = None

    # --- Private: simulation control ---

    def _step_simulation(self, steps: int = 1):
        for _ in range(steps):
            p.stepSimulation(physicsClientId=self._physics_client)

    def _set_joint(self, joint_index: int, target: float):
        p.setJointMotorControl2(
            self._robot_id,
            joint_index,
            p.POSITION_CONTROL,
            targetPosition=target,
            force=240,
            physicsClientId=self._physics_client,
        )
        self._step_simulation(100)

    def _set_gripper(self, width: float):
        finger_pos = width / 2.0
        for gi in PANDA_GRIPPER_INDICES:
            p.setJointMotorControl2(
                self._robot_id,
                gi,
                p.POSITION_CONTROL,
                targetPosition=finger_pos,
                force=20,
                physicsClientId=self._physics_client,
            )
        self._step_simulation(100)

    def _move_to_joint_positions(self, positions: list[float]):
        for i in range(PANDA_NUM_JOINTS):
            p.setJointMotorControl2(
                self._robot_id,
                i,
                p.POSITION_CONTROL,
                targetPosition=positions[i],
                force=240,
                physicsClientId=self._physics_client,
            )
        self._step_simulation(240)

    def _execute_pick(self, x: float, y: float, z: float):
        # Move above target
        self._move_to_cartesian(x, y, z + 0.1)
        # Open gripper
        self._set_gripper(GRIPPER_RANGE[1])
        # Move down
        self._move_to_cartesian(x, y, z)
        # Close gripper
        self._set_gripper(GRIPPER_RANGE[0])
        # Lift
        self._move_to_cartesian(x, y, z + 0.1)

    def _execute_place(self, x: float, y: float, z: float):
        # Move above target
        self._move_to_cartesian(x, y, z + 0.1)
        # Move down
        self._move_to_cartesian(x, y, z)
        # Open gripper
        self._set_gripper(GRIPPER_RANGE[1])
        # Lift
        self._move_to_cartesian(x, y, z + 0.1)

    def _move_to_cartesian(self, x: float, y: float, z: float):
        """Use IK to move end effector to target position."""
        target_orn = p.getQuaternionFromEuler([math.pi, 0, 0])  # Top-down grasp
        joint_positions = p.calculateInverseKinematics(
            self._robot_id,
            PANDA_END_EFFECTOR_INDEX,
            [x, y, z],
            target_orn,
            physicsClientId=self._physics_client,
        )
        for i in range(PANDA_NUM_JOINTS):
            p.setJointMotorControl2(
                self._robot_id,
                i,
                p.POSITION_CONTROL,
                targetPosition=joint_positions[i],
                force=240,
                physicsClientId=self._physics_client,
            )
        self._step_simulation(240)

    # --- Private: state reading ---

    def _read_state(self) -> dict[str, Any]:
        props = {}
        for i, name in enumerate(JOINT_NAMES):
            state = p.getJointState(self._robot_id, i, physicsClientId=self._physics_client)
            props[name] = state[0]  # position

        # Gripper width (sum of both finger positions)
        g0 = p.getJointState(self._robot_id, PANDA_GRIPPER_INDICES[0], physicsClientId=self._physics_client)
        g1 = p.getJointState(self._robot_id, PANDA_GRIPPER_INDICES[1], physicsClientId=self._physics_client)
        props["gripper_width"] = g0[0] + g1[0]

        # End effector position
        ee_state = p.getLinkState(self._robot_id, PANDA_END_EFFECTOR_INDEX, physicsClientId=self._physics_client)
        props["end_effector_position"] = list(ee_state[0])

        return props

    # --- Private: rendering ---

    def _render_image(self) -> str:
        """Render the scene using PyBullet's built-in renderer."""
        width, height = 640, 480
        view_matrix = p.computeViewMatrix(
            cameraEyePosition=[1.0, -0.5, 0.8],
            cameraTargetPosition=[0.4, 0.0, 0.3],
            cameraUpVector=[0, 0, 1],
            physicsClientId=self._physics_client,
        )
        proj_matrix = p.computeProjectionMatrixFOV(
            fov=60,
            aspect=width / height,
            nearVal=0.1,
            farVal=3.0,
            physicsClientId=self._physics_client,
        )
        _, _, rgba, _, _ = p.getCameraImage(
            width, height,
            viewMatrix=view_matrix,
            projectionMatrix=proj_matrix,
            physicsClientId=self._physics_client,
        )
        img_array = np.array(rgba, dtype=np.uint8).reshape(height, width, 4)
        pil_img = Image.fromarray(img_array[:, :, :3])  # Drop alpha
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    # --- Private: CDD builder ---

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
            metadata={"engine": "pybullet", "dof": PANDA_NUM_JOINTS},
        )
