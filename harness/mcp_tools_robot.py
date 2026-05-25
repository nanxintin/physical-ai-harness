"""Robot-specific MCP tools for quadruped control.

These tools are conditionally registered when HARNESS_BACKEND is mujoco or mujoco_mock.
"""

from __future__ import annotations

import json
from typing import Any

from harness.adapters.mujoco_go1.robot_config import ACTIONS, ACTUATOR_NAMES, DEVICE_ID, get_joint_range
from harness.models import SafetyLevel
from harness.safety import SafetySandbox


def register_robot_tools(mcp_app, adapter, sandbox: SafetySandbox):
    """Register robot-specific MCP tools on the given FastMCP app."""

    @mcp_app.tool()
    async def robot_move(action: str, speed: float = 0.3, duration: float = 2.0) -> str:
        """Command the robot to perform a locomotion action.

        Args:
            action: One of: stand, sit, walk_forward, walk_backward, turn_left, turn_right, trot, stop
            speed: Movement speed in m/s (0.1-1.0, default 0.3)
            duration: Duration in seconds (0.5-10.0, default 2.0)
        """
        if not adapter.is_initialized:
            return json.dumps({"error": "Scene not loaded. Call scene_load first."})

        if action not in ACTIONS:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "available": list(ACTIONS.keys()),
            })

        # Safety check
        action_safety = ACTIONS[action]["safety"]
        if action_safety == SafetyLevel.CRITICAL:
            check = sandbox.check(adapter._devices[DEVICE_ID], action)
            if not check.allowed:
                return json.dumps({
                    "error": "blocked_by_safety",
                    "reason": check.reason,
                    "action": action,
                    "safety_level": action_safety.value,
                })

        speed = max(0.1, min(1.0, speed))
        duration = max(0.5, min(10.0, duration))

        try:
            result = await adapter.invoke_action(
                DEVICE_ID, action, {"speed": speed, "duration": duration}
            )
            state = await adapter.get_device_state(DEVICE_ID)
            return json.dumps({
                "status": "success",
                "action": action,
                "speed": speed,
                "duration": duration,
                "body_position": state.properties.get("body_position"),
                "body_orientation": state.properties.get("body_orientation"),
            }, indent=2)
        except (ValueError, RuntimeError) as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp_app.tool()
    async def robot_joints(targets: str) -> str:
        """Set target positions for one or more robot joints.

        Args:
            targets: JSON object mapping joint names to target positions in radians.
                     Example: {"FR_hip": 0.1, "FR_thigh": 0.8, "FR_calf": -1.5}
                     Available joints: FR_hip, FR_thigh, FR_calf, FL_hip, FL_thigh, FL_calf,
                     RR_hip, RR_thigh, RR_calf, RL_hip, RL_thigh, RL_calf
        """
        if not adapter.is_initialized:
            return json.dumps({"error": "Scene not loaded. Call scene_load first."})

        try:
            joint_targets = json.loads(targets)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})

        if not isinstance(joint_targets, dict):
            return json.dumps({"error": "targets must be a JSON object"})

        results = []
        for joint_name, value in joint_targets.items():
            if joint_name not in ACTUATOR_NAMES:
                results.append({"joint": joint_name, "error": f"Unknown joint. Available: {ACTUATOR_NAMES}"})
                continue
            try:
                float_val = float(value)
                low, high = get_joint_range(joint_name)
                if not (low <= float_val <= high):
                    results.append({"joint": joint_name, "error": f"Out of range [{low}, {high}]"})
                    continue
                await adapter.set_property(DEVICE_ID, f"joint_{joint_name}", float_val)
                results.append({"joint": joint_name, "target": float_val, "status": "set"})
            except (ValueError, RuntimeError) as e:
                results.append({"joint": joint_name, "error": str(e)})

        state = await adapter.get_device_state(DEVICE_ID)
        return json.dumps({
            "status": "success",
            "results": results,
            "current_joints": {
                name: state.properties.get(f"joint_{name}")
                for name in ACTUATOR_NAMES
            },
        }, indent=2)

    @mcp_app.tool()
    async def robot_sensors() -> str:
        """Read all robot sensor data: joint positions, body pose, IMU, foot contacts."""
        if not adapter.is_initialized:
            return json.dumps({"error": "Scene not loaded. Call scene_load first."})

        state = await adapter.get_device_state(DEVICE_ID)
        props = state.properties

        return json.dumps({
            "joints": {name: props.get(f"joint_{name}") for name in ACTUATOR_NAMES},
            "body": {
                "position": props.get("body_position"),
                "orientation": props.get("body_orientation"),
                "velocity": props.get("body_velocity"),
            },
            "imu": {
                "angular_velocity": props.get("imu_angular_velocity"),
            },
            "foot_contacts": {
                "FR": props.get("foot_contacts", [False]*4)[0],
                "FL": props.get("foot_contacts", [False]*4)[1],
                "RR": props.get("foot_contacts", [False]*4)[2],
                "RL": props.get("foot_contacts", [False]*4)[3],
            },
            "current_action": props.get("current_action"),
            "timestamp": state.timestamp,
        }, indent=2)
