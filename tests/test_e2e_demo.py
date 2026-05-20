#!/usr/bin/env python3
"""End-to-end demo test: simulates an Agent conversation with Harness.

Tests the full scenario flow that a real LLM Agent would follow:
1. Load scene
2. Discover devices
3. Query device states
4. Control devices (with safety checks)
5. Verify multi-device orchestration
6. Capture scene image

Run with: python tests/test_e2e_demo.py
"""

import asyncio
import json
import os
import sys
import time
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


async def simulate_agent_conversation():
    """Simulate a realistic Agent conversation with Harness."""
    print("=" * 70)
    print("END-TO-END DEMO: Simulating Agent ↔ Harness Conversation")
    print("=" * 70)
    total_start = time.time()

    # --- Turn 1: Agent loads scene ---
    print("\n🤖 Agent: \"Load the kitchen scene\"")
    print("─" * 50)
    t = time.time()
    result = json.loads(await scene_load("FloorPlan1"))
    print(f"   → scene_load('FloorPlan1') [{(time.time()-t)*1000:.0f}ms]")
    print(f"   ← {result['message']}")
    assert result["status"] == "success"

    # --- Turn 2: Agent discovers devices ---
    print("\n🤖 Agent: \"What devices are in this room?\"")
    print("─" * 50)
    t = time.time()
    result = json.loads(await devices_list())
    print(f"   → devices_list() [{(time.time()-t)*1000:.0f}ms]")
    print(f"   ← Found {result['count']} devices:")
    for d in result["devices"]:
        safety_icon = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "⛔"}.get(d["safety"], "?")
        print(f"      {safety_icon} {d['type']:15s} | {d['capabilities']}")

    # --- Turn 3: Agent checks specific device ---
    print("\n🤖 Agent: \"What's the status of the floor lamp?\"")
    print("─" * 50)
    lamp_id = next(d["device_id"] for d in result["devices"] if d["type"] == "FloorLamp")
    t = time.time()
    state = json.loads(await device_state(lamp_id))
    print(f"   → device_state('{lamp_id[:30]}...') [{(time.time()-t)*1000:.0f}ms]")
    print(f"   ← State: {state['properties']}")

    # --- Turn 4: Agent controls device ---
    print("\n🤖 Agent: \"Turn on the floor lamp\"")
    print("─" * 50)
    t = time.time()
    result = json.loads(await device_control(lamp_id, "isToggled", "true"))
    print(f"   → device_control(..., isToggled, true) [{(time.time()-t)*1000:.0f}ms]")
    print(f"   ← {result['status']}: isToggled={result['new_value']}")
    assert result["status"] == "success"

    # --- Turn 5: Agent tries unsafe action ---
    print("\n🤖 Agent: \"Open the safe\"")
    print("─" * 50)
    safe_id = "Safe|+03.50|+00.00|+00.20"
    t = time.time()
    result = json.loads(await device_control(safe_id, "isOpen", "true"))
    print(f"   → device_control(Safe, isOpen, true) [{(time.time()-t)*1000:.0f}ms]")
    print(f"   ← BLOCKED: {result['reason']}")
    assert result["error"] == "blocked_by_safety"

    # --- Turn 6: Multi-device scenario ---
    print("\n🤖 Agent: \"I'm leaving, turn off everything\"")
    print("─" * 50)
    all_devices = json.loads(await devices_list())
    t = time.time()
    controlled = 0
    blocked = 0
    for d in all_devices["devices"]:
        if "isToggled" in d["capabilities"]:
            r = json.loads(await device_control(d["device_id"], "isToggled", "false"))
            if r.get("status") == "success":
                controlled += 1
            elif r.get("error") == "blocked_by_safety":
                blocked += 1
    elapsed = (time.time() - t) * 1000
    print(f"   → Batch control [{elapsed:.0f}ms total]")
    print(f"   ← Turned off {controlled} devices, {blocked} blocked by safety")

    # --- Turn 7: Scene overview ---
    print("\n🤖 Agent: \"Describe the current scene\"")
    print("─" * 50)
    t = time.time()
    result = json.loads(await scene_describe())
    print(f"   → scene_describe() [{(time.time()-t)*1000:.0f}ms]")
    lines = result["description"].split("\n")[:6]
    for line in lines:
        print(f"   ← {line}")

    # --- Turn 8: Capture image ---
    print("\n🤖 Agent: \"Show me the scene\"")
    print("─" * 50)
    t = time.time()
    result = json.loads(await scene_capture())
    elapsed_ms = (time.time() - t) * 1000
    img_size = len(result["image"])
    print(f"   → scene_capture() [{elapsed_ms:.0f}ms]")
    print(f"   ← Image: {img_size} chars base64 (~{img_size*3//4//1024}KB PNG)")

    # Save captured image
    import base64
    img_bytes = base64.b64decode(result["image"])
    output_path = Path(__file__).parent / "ai2thor_results" / "e2e_demo_capture.png"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_bytes(img_bytes)

    # --- Turn 9: Event history ---
    print("\n🤖 Agent: \"What happened recently?\"")
    print("─" * 50)
    t = time.time()
    result = json.loads(await events_history(limit=5))
    print(f"   → events_history(5) [{(time.time()-t)*1000:.0f}ms]")
    print(f"   ← {len(result['events'])} recent events:")
    for e in result["events"][-3:]:
        dev = e.get("device_id", "?").split("|")[0]
        print(f"      • {dev}: {e.get('property')} → {e.get('value')}")

    # --- Summary ---
    total_time = time.time() - total_start
    print(f"\n{'='*70}")
    print(f"✅ END-TO-END DEMO COMPLETE")
    print(f"   Total time: {total_time:.2f}s")
    print(f"   9 turns simulated successfully")
    print(f"   Safety sandbox blocked 1 CRITICAL operation")
    print(f"   Image saved: {output_path}")
    print(f"{'='*70}")

    return True


if __name__ == "__main__":
    success = asyncio.run(simulate_agent_conversation())
    sys.exit(0 if success else 1)
