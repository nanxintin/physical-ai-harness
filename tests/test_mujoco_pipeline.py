"""Test suite for MuJoCo Go1 adapter (uses MockMuJoCoAdapter, no GPU needed)."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.adapters.mujoco_go1.mock_adapter import MockMuJoCoAdapter
from harness.adapters.mujoco_go1.robot_config import ACTUATOR_NAMES, ACTIONS, DEVICE_ID
from harness.events import EventBus
from harness.models import SafetyLevel
from harness.safety import SafetySandbox


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []

    def check(self, condition: bool, name: str):
        if condition:
            self.passed += 1
            print(f"  ✅ {name}")
        else:
            self.failed += 1
            print(f"  ❌ {name}")
        self.results.append({"name": name, "passed": condition})


async def main():
    results = TestResults()

    # --- Test: Adapter Initialization ---
    print("\n--- Test: Adapter Initialization ---")
    event_bus = EventBus()
    adapter = MockMuJoCoAdapter(event_bus=event_bus)

    init_result = await adapter.initialize("flat_ground")
    results.check(init_result["device_count"] == 1, "device_count is 1")
    results.check(init_result["device_types"] == ["quadruped_robot"], "device_type is quadruped_robot")
    results.check(init_result["engine"] == "mujoco_mock", "engine is mujoco_mock")
    results.check(init_result["actuators"] == 12, "12 actuators")
    results.check(adapter.is_initialized, "adapter is initialized")

    # --- Test: CDD Structure ---
    print("\n--- Test: CDD Structure ---")
    devices = await adapter.list_devices()
    results.check(len(devices) == 1, "single device (robot)")
    cdd = devices[0]
    results.check(cdd.device_id == DEVICE_ID, "device_id is unitree_go1")
    results.check(cdd.device_type == "quadruped_robot", "device_type correct")
    results.check(cdd.safety_class == SafetyLevel.HIGH, "safety_class is HIGH")
    results.check(len(cdd.capabilities) == 25, f"25 capabilities (got {len(cdd.capabilities)})")

    # Check capability types
    joint_caps = [c for c in cdd.capabilities if c.cap_type == "float" and c.writable]
    sensor_caps = [c for c in cdd.capabilities if c.cap_type == "float" and not c.writable]
    action_caps = [c for c in cdd.capabilities if c.cap_type == "action"]
    results.check(len(joint_caps) == 12, f"12 joint capabilities (got {len(joint_caps)})")
    results.check(len(sensor_caps) == 4, f"4 sensor capabilities (got {len(sensor_caps)})")
    results.check(len(action_caps) == 8, f"8 action capabilities (got {len(action_caps)})")

    # Check value_range on joints
    fr_hip = next(c for c in cdd.capabilities if c.name == "joint_FR_hip")
    results.check(fr_hip.value_range is not None, "joint has value_range")
    results.check(fr_hip.value_range["min"] == -0.863, "hip min range correct")
    results.check(fr_hip.value_range["max"] == 0.863, "hip max range correct")

    # Check CDD serialization includes value_range
    cdd_dict = cdd.to_dict()
    cap_dict = next(c for c in cdd_dict["capabilities"] if c["name"] == "joint_FR_hip")
    results.check("value_range" in cap_dict, "value_range serialized in to_dict()")

    # --- Test: Device State Query ---
    print("\n--- Test: Device State Query ---")
    state = await adapter.get_device_state(DEVICE_ID)
    results.check(state.device_id == DEVICE_ID, "state has correct device_id")
    results.check("joint_FR_hip" in state.properties, "has joint_FR_hip")
    results.check("body_position" in state.properties, "has body_position")
    results.check("body_orientation" in state.properties, "has body_orientation")
    results.check("foot_contacts" in state.properties, "has foot_contacts")
    results.check(state.properties["current_action"] == "stand", "initial action is stand")

    # Error on invalid device
    try:
        await adapter.get_device_state("nonexistent")
        results.check(False, "should raise on invalid device_id")
    except ValueError:
        results.check(True, "raises ValueError on invalid device_id")

    # --- Test: Joint Control ---
    print("\n--- Test: Joint Control ---")
    new_state = await adapter.set_property(DEVICE_ID, "joint_FR_hip", 0.5)
    results.check(new_state.properties["joint_FR_hip"] == 0.5, "joint set to 0.5")

    new_state = await adapter.set_property(DEVICE_ID, "joint_FR_hip", -0.5)
    results.check(new_state.properties["joint_FR_hip"] == -0.5, "joint set to -0.5")

    # Out of range
    try:
        await adapter.set_property(DEVICE_ID, "joint_FR_hip", 5.0)
        results.check(False, "should reject out-of-range value")
    except ValueError:
        results.check(True, "rejects out-of-range value")

    # Invalid property
    try:
        await adapter.set_property(DEVICE_ID, "body_position", 1.0)
        results.check(False, "should reject non-joint property")
    except ValueError:
        results.check(True, "rejects non-joint property")

    # Invalid actuator
    try:
        await adapter.set_property(DEVICE_ID, "joint_FAKE", 0.0)
        results.check(False, "should reject unknown actuator")
    except ValueError:
        results.check(True, "rejects unknown actuator")

    # --- Test: High-Level Actions ---
    print("\n--- Test: High-Level Actions ---")
    result = await adapter.invoke_action(DEVICE_ID, "walk_forward", {"speed": 0.5, "duration": 2.0})
    results.check(result["success"] is True, "walk_forward succeeds")
    state = await adapter.get_device_state(DEVICE_ID)
    results.check(state.properties["body_position"][0] == 1.0, "position advanced by speed*duration")

    result = await adapter.invoke_action(DEVICE_ID, "turn_left")
    results.check(result["success"] is True, "turn_left succeeds")
    state = await adapter.get_device_state(DEVICE_ID)
    results.check(abs(state.properties["body_orientation"][2] - 0.785) < 0.01, "turned ~45 degrees")

    result = await adapter.invoke_action(DEVICE_ID, "sit")
    results.check(result["success"] is True, "sit succeeds")
    state = await adapter.get_device_state(DEVICE_ID)
    results.check(state.properties["body_position"][2] == 0.15, "body lowered for sit")

    result = await adapter.invoke_action(DEVICE_ID, "stop")
    results.check(result["success"] is True, "stop succeeds")
    state = await adapter.get_device_state(DEVICE_ID)
    results.check(state.properties["body_velocity"] == [0.0, 0.0, 0.0], "velocity zeroed on stop")

    # Invalid action
    try:
        await adapter.invoke_action(DEVICE_ID, "fly")
        results.check(False, "should reject unknown action")
    except ValueError:
        results.check(True, "rejects unknown action")

    # --- Test: Safety Sandbox ---
    print("\n--- Test: Safety Sandbox ---")
    sandbox = SafetySandbox(max_allowed=SafetyLevel.HIGH)
    cdd = (await adapter.list_devices())[0]

    # HIGH actions should pass
    check = sandbox.check(cdd, "stand")
    results.check(check.allowed, "stand (HIGH) allowed by sandbox")

    check = sandbox.check(cdd, "walk_forward")
    results.check(check.allowed, "walk_forward (HIGH) allowed")

    # CRITICAL action (trot) should be blocked
    # Need to find trot capability and set its safety level
    trot_cap = next(c for c in cdd.capabilities if c.name == "trot")
    results.check(trot_cap.safety_level == SafetyLevel.CRITICAL, "trot is CRITICAL")

    # MEDIUM (stop) should be allowed
    stop_cap = next(c for c in cdd.capabilities if c.name == "stop")
    results.check(stop_cap.safety_level == SafetyLevel.MEDIUM, "stop is MEDIUM")

    # --- Test: Event Bus ---
    print("\n--- Test: Event Bus ---")
    event_bus_test = EventBus()
    adapter2 = MockMuJoCoAdapter(event_bus=event_bus_test)
    await adapter2.initialize("flat_ground")

    await adapter2.set_property(DEVICE_ID, "joint_FR_hip", 0.1)
    history = event_bus_test.get_history()
    results.check(len(history) >= 1, "event emitted on joint control")
    results.check(history[-1]["type"] == "state_changed", "event type is state_changed")

    await adapter2.invoke_action(DEVICE_ID, "walk_forward")
    history = event_bus_test.get_history()
    action_events = [e for e in history if e["type"] == "action_executed"]
    results.check(len(action_events) >= 1, "event emitted on action")
    results.check(action_events[-1]["action"] == "walk_forward", "action event has correct action")

    # --- Test: Image Capture ---
    print("\n--- Test: Image Capture ---")
    img_b64 = await adapter.capture_image()
    results.check(isinstance(img_b64, str), "image is string")
    results.check(len(img_b64) > 100, "image has content")
    img_bytes = base64.b64decode(img_b64)
    results.check(img_bytes[:4] == b'\x89PNG', "valid PNG header")

    # === Summary ===
    print(f"\n{'='*60}")
    print(f"Results: {results.passed}/{results.passed + results.failed} passed, {results.failed} failed")
    print(f"{'='*60}")

    # Save results
    output = {
        "suite": "mujoco_pipeline",
        "total": results.passed + results.failed,
        "passed": results.passed,
        "failed": results.failed,
        "results": results.results,
    }
    output_path = os.path.join(os.path.dirname(__file__), "test_mujoco_results.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to: {output_path}")

    return results.failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
