"""Test MCP tool layer for MuJoCo robot backend."""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["HARNESS_BACKEND"] = "mujoco_mock"

from harness.adapters.mujoco_go1.mock_adapter import MockMuJoCoAdapter
from harness.adapters.mujoco_go1.robot_config import DEVICE_ID
from harness.events import EventBus
from harness.models import SafetyLevel
from harness.safety import SafetySandbox
from mcp.server.fastmcp import FastMCP


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, condition: bool, name: str):
        if condition:
            self.passed += 1
            print(f"  ✅ {name}")
        else:
            self.failed += 1
            print(f"  ❌ {name}")


async def main():
    results = TestResults()

    # Setup: create adapter and register tools
    event_bus = EventBus()
    adapter = MockMuJoCoAdapter(event_bus=event_bus)
    sandbox = SafetySandbox(max_allowed=SafetyLevel.HIGH)

    mcp_app = FastMCP("test_harness")

    # Register base tools (simulate mcp_server setup)
    @mcp_app.tool()
    async def scene_load(scene: str = "flat_ground") -> str:
        result = await adapter.initialize(scene)
        return json.dumps(result, indent=2)

    @mcp_app.tool()
    async def devices_list() -> str:
        devices = await adapter.list_devices()
        return json.dumps({"count": len(devices), "devices": [d.to_dict() for d in devices]}, indent=2)

    # Register robot tools
    from harness.mcp_tools_robot import register_robot_tools
    register_robot_tools(mcp_app, adapter, sandbox)

    # --- Test: Scene Load ---
    print("\n--- Test: Scene Load (MuJoCo) ---")
    result = json.loads(await scene_load("flat_ground"))
    results.check(result["device_count"] == 1, "scene loads with 1 device")
    results.check(result["engine"] == "mujoco_mock", "engine is mujoco_mock")

    # --- Test: Devices List ---
    print("\n--- Test: Devices List ---")
    result = json.loads(await devices_list())
    results.check(result["count"] == 1, "1 device listed")
    dev = result["devices"][0]
    results.check(dev["device_type"] == "quadruped_robot", "device type is quadruped_robot")
    results.check(len(dev["capabilities"]) == 25, "25 capabilities")

    # --- Test: robot_move tool ---
    print("\n--- Test: robot_move ---")
    # Get the tool function from registered tools
    tools = mcp_app._tool_manager._tools
    robot_move_fn = tools["robot_move"].fn
    robot_joints_fn = tools["robot_joints"].fn
    robot_sensors_fn = tools["robot_sensors"].fn

    result = json.loads(await robot_move_fn(action="stand"))
    results.check(result["status"] == "success", "stand succeeds")
    results.check(result["action"] == "stand", "action is stand")

    result = json.loads(await robot_move_fn(action="walk_forward", speed=0.5, duration=3.0))
    results.check(result["status"] == "success", "walk_forward succeeds")
    results.check(result["body_position"][0] > 0, "position moved forward")

    result = json.loads(await robot_move_fn(action="turn_left"))
    results.check(result["status"] == "success", "turn_left succeeds")

    # Invalid action
    result = json.loads(await robot_move_fn(action="fly"))
    results.check("error" in result, "invalid action returns error")

    # CRITICAL action (trot) blocked by safety
    result = json.loads(await robot_move_fn(action="trot"))
    results.check(result.get("error") == "blocked_by_safety", "trot blocked by safety")
    results.check(result.get("safety_level") == "critical", "reports CRITICAL level")

    # stop (MEDIUM) should work
    result = json.loads(await robot_move_fn(action="stop"))
    results.check(result["status"] == "success", "stop (MEDIUM) succeeds")

    # --- Test: robot_joints tool ---
    print("\n--- Test: robot_joints ---")
    result = json.loads(await robot_joints_fn(targets='{"FR_hip": 0.3, "FR_thigh": 1.0}'))
    results.check(result["status"] == "success", "joint set succeeds")
    results.check(len(result["results"]) == 2, "2 joints set")
    results.check(result["current_joints"]["FR_hip"] == 0.3, "FR_hip value correct")

    # Invalid JSON
    result = json.loads(await robot_joints_fn(targets='not json'))
    results.check("error" in result, "invalid JSON returns error")

    # Out of range
    result = json.loads(await robot_joints_fn(targets='{"FR_hip": 5.0}'))
    results.check(result["results"][0].get("error") is not None, "out-of-range returns error per joint")

    # Unknown joint
    result = json.loads(await robot_joints_fn(targets='{"FAKE_joint": 0.1}'))
    results.check(result["results"][0].get("error") is not None, "unknown joint returns error")

    # --- Test: robot_sensors tool ---
    print("\n--- Test: robot_sensors ---")
    result = json.loads(await robot_sensors_fn())
    results.check("joints" in result, "has joints section")
    results.check("body" in result, "has body section")
    results.check("imu" in result, "has imu section")
    results.check("foot_contacts" in result, "has foot_contacts section")
    results.check(len(result["joints"]) == 12, "12 joints in sensors")
    results.check("position" in result["body"], "body has position")
    results.check("FR" in result["foot_contacts"], "foot_contacts has FR")

    # --- Test: scene not loaded error ---
    print("\n--- Test: Error when scene not loaded ---")
    adapter2 = MockMuJoCoAdapter()
    mcp_app2 = FastMCP("test2")
    register_robot_tools(mcp_app2, adapter2, sandbox)
    tools2 = mcp_app2._tool_manager._tools
    result = json.loads(await tools2["robot_move"].fn(action="stand"))
    results.check("error" in result, "error when scene not loaded")

    # === Summary ===
    print(f"\n{'='*60}")
    print(f"Results: {results.passed}/{results.passed + results.failed} passed, {results.failed} failed")
    print(f"{'='*60}")
    return results.failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
