#!/usr/bin/env python3
"""Test MCP Server tool invocations using mock adapter.

Run with: python tests/test_mcp_server.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["HARNESS_MOCK"] = "1"

from harness.mcp_server import (
    device_control,
    device_state,
    devices_list,
    events_history,
    scene_capture,
    scene_describe,
    scene_load,
)


async def main():
    print("=" * 60)
    print("MCP Server Tool Tests (Mock Mode)")
    print("=" * 60)
    passed = 0
    failed = 0

    # Test 1: scene_load
    print("\n--- scene_load ---")
    result = json.loads(await scene_load("FloorPlan1"))
    assert result["status"] == "success", f"Expected success, got: {result}"
    assert result["device_count"] == 10
    print(f"  ✅ Loaded scene with {result['device_count']} devices")
    print(f"     Types: {result['device_types']}")
    passed += 1

    # Test 2: devices_list
    print("\n--- devices_list ---")
    result = json.loads(await devices_list())
    assert result["count"] == 10
    print(f"  ✅ Listed {result['count']} devices")
    for d in result["devices"][:3]:
        print(f"     {d['type']:15s} | safety={d['safety']:8s} | caps={d['capabilities']}")
    passed += 1

    # Test 3: devices_list with filter
    print("\n--- devices_list (filter=Lamp) ---")
    result = json.loads(await devices_list(filter_type="Lamp"))
    assert result["count"] == 2, f"Expected 2 lamps, got {result['count']}"
    print(f"  ✅ Filtered to {result['count']} lamps")
    passed += 1

    # Test 4: device_state
    print("\n--- device_state ---")
    result = json.loads(await device_state("FloorLamp|+01.32|+00.00|+00.45"))
    assert "properties" in result
    assert result["properties"]["isToggled"] is False
    print(f"  ✅ FloorLamp state: {result['properties']}")
    passed += 1

    # Test 5: device_control - turn on lamp
    print("\n--- device_control (turn on lamp) ---")
    result = json.loads(await device_control("FloorLamp|+01.32|+00.00|+00.45", "isToggled", "true"))
    assert result["status"] == "success"
    assert result["new_value"] is True
    print(f"  ✅ Lamp turned on: {result['full_state']['properties']}")
    passed += 1

    # Test 6: device_control - open fridge
    print("\n--- device_control (open fridge) ---")
    result = json.loads(await device_control("Fridge|+03.00|+00.00|+02.50", "isOpen", "true"))
    assert result["status"] == "success"
    print(f"  ✅ Fridge opened: {result['full_state']['properties']}")
    passed += 1

    # Test 7: device_control - CRITICAL blocked
    print("\n--- device_control (safe - should be blocked) ---")
    result = json.loads(await device_control("Safe|+03.50|+00.00|+00.20", "isOpen", "true"))
    assert result.get("error") == "blocked_by_safety"
    assert result.get("requires_confirmation") is True
    print(f"  ✅ Safe correctly blocked: {result['reason']}")
    passed += 1

    # Test 8: scene_capture
    print("\n--- scene_capture ---")
    result = json.loads(await scene_capture())
    assert result["status"] == "success"
    assert result["format"] == "png"
    assert len(result["image"]) > 100
    print(f"  ✅ Captured image ({len(result['image'])} chars base64)")
    passed += 1

    # Test 9: scene_describe
    print("\n--- scene_describe ---")
    result = json.loads(await scene_describe())
    assert result["device_count"] == 10
    assert len(result["description"]) > 50
    print(f"  ✅ Scene described ({result['device_count']} devices)")
    lines = result["description"].split("\n")[:5]
    for line in lines:
        print(f"     {line}")
    passed += 1

    # Test 10: events_history
    print("\n--- events_history ---")
    result = json.loads(await events_history(limit=5))
    assert len(result["events"]) >= 2  # from our control actions above
    print(f"  ✅ {len(result['events'])} events in history")
    for e in result["events"][:3]:
        print(f"     {e.get('type')}: {e.get('device_id', '')[:30]} → {e.get('value')}")
    passed += 1

    # Test 11: error handling - device not found
    print("\n--- error handling ---")
    result = json.loads(await device_state("NonExistent|+00.00"))
    assert "error" in result
    print(f"  ✅ Error handled: {result['error'][:50]}")
    passed += 1

    # Test 12: scene not loaded error
    print("\n--- scene not loaded (fresh adapter check) ---")
    # This tests the guard in devices_list when adapter is initialized
    # (already loaded above, so this should work)
    result = json.loads(await devices_list())
    assert result["count"] > 0
    print(f"  ✅ Confirmed scene persistence across calls")
    passed += 1

    print(f"\n{'='*60}")
    print(f"MCP Server Tests: {passed}/{passed + failed} passed")
    print(f"{'='*60}")

    # Save results
    output = {
        "test_run": "mcp_server_tools",
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "mock_mode": True,
    }
    Path(__file__).parent.joinpath("test_mcp_results.json").write_text(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
