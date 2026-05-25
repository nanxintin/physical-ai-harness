"""End-to-end demo simulating Agent conversation with MuJoCo robot."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["HARNESS_BACKEND"] = "mujoco_mock"

from harness.adapters.mujoco_go1.mock_adapter import MockMuJoCoAdapter
from harness.adapters.mujoco_go1.robot_config import DEVICE_ID
from harness.events import EventBus
from harness.models import SafetyLevel
from harness.safety import SafetySandbox
from harness.mcp_tools_robot import register_robot_tools
from mcp.server.fastmcp import FastMCP


async def main():
    print("=" * 60)
    print("MuJoCo Robot E2E Demo - Simulated Agent Conversation")
    print("=" * 60)

    # Setup
    event_bus = EventBus()
    adapter = MockMuJoCoAdapter(event_bus=event_bus)
    sandbox = SafetySandbox(max_allowed=SafetyLevel.HIGH)
    mcp_app = FastMCP("harness")

    @mcp_app.tool()
    async def scene_load(scene: str = "flat_ground") -> str:
        result = await adapter.initialize(scene)
        return json.dumps(result, indent=2)

    @mcp_app.tool()
    async def devices_list() -> str:
        devices = await adapter.list_devices()
        return json.dumps({
            "count": len(devices),
            "devices": [{"id": d.device_id, "type": d.device_type, "name": d.display_name,
                         "capabilities": len(d.capabilities)} for d in devices]
        }, indent=2)

    @mcp_app.tool()
    async def scene_capture() -> str:
        img = await adapter.capture_image()
        return json.dumps({"status": "success", "format": "png", "image_length": len(img)})

    register_robot_tools(mcp_app, adapter, sandbox)
    tools = mcp_app._tool_manager._tools

    turns = [
        ("Load the robot simulation scene", "scene_load", {"scene": "flat_ground"}),
        ("What robots are available?", "devices_list", {}),
        ("Read sensor data", "robot_sensors", {}),
        ("Make the robot stand up", "robot_move", {"action": "stand"}),
        ("Walk forward for 3 seconds", "robot_move", {"action": "walk_forward", "speed": 0.4, "duration": 3.0}),
        ("Set FR_hip joint to 0.2 rad", "robot_joints", {"targets": '{"FR_hip": 0.2}'}),
        ("Take a picture of the scene", "scene_capture", {}),
        ("Make the robot trot (fast)", "robot_move", {"action": "trot"}),
        ("Emergency stop!", "robot_move", {"action": "stop"}),
    ]

    all_passed = True
    for i, (user_msg, tool_name, kwargs) in enumerate(turns, 1):
        print(f"\n{'─'*50}")
        print(f"Turn {i}: User says: \"{user_msg}\"")
        print(f"  → Tool: {tool_name}({kwargs})")

        t0 = time.time()
        tool_fn = tools[tool_name].fn
        result_str = await tool_fn(**kwargs)
        elapsed_ms = (time.time() - t0) * 1000

        result = json.loads(result_str)
        status = "✅" if "error" not in result or (tool_name == "robot_move" and kwargs.get("action") == "trot") else "❌"

        # Special case: trot should be blocked
        if tool_name == "robot_move" and kwargs.get("action") == "trot":
            if result.get("error") == "blocked_by_safety":
                status = "✅ (correctly blocked)"
            else:
                status = "❌ (should have been blocked)"
                all_passed = False

        print(f"  ← Result ({elapsed_ms:.1f}ms): {status}")

        # Print key fields from result
        if "body_position" in result:
            print(f"     Position: {result['body_position']}")
        if "action" in result and "status" in result:
            print(f"     Action: {result['action']}, Status: {result['status']}")
        if "error" in result:
            print(f"     Error: {result['error']}")
        if "joints" in result:
            print(f"     Joints (sample): FR_hip={result['joints'].get('FR_hip', '?')}")
        if "count" in result:
            print(f"     Devices: {result['count']}")

    # Final state
    print(f"\n{'─'*50}")
    print("Final State:")
    state = await adapter.get_device_state(DEVICE_ID)
    print(f"  Position: {state.properties['body_position']}")
    print(f"  Action: {state.properties['current_action']}")
    print(f"  Velocity: {state.properties['body_velocity']}")

    # Event history
    history = event_bus.get_history()
    print(f"\n  Events recorded: {len(history)}")
    for e in history[-3:]:
        print(f"    - {e['type']}: {e.get('action', e.get('property', ''))}")

    print(f"\n{'='*60}")
    print(f"E2E Demo: {'PASSED' if all_passed else 'FAILED'}")
    print(f"{'='*60}")
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
