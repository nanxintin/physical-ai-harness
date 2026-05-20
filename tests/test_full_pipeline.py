#!/usr/bin/env python3
"""Full pipeline tests using MockAdapter.

Tests the complete flow: Adapter → Safety → Events → MCP tools
Run with: python tests/test_full_pipeline.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.adapters.mock_adapter import MockAdapter
from harness.events import EventBus
from harness.models import SafetyLevel
from harness.safety import SafetySandbox


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results: list[dict] = []

    def record(self, name: str, passed: bool, detail: str = ""):
        self.results.append({"name": name, "passed": passed, "detail": detail})
        if passed:
            self.passed += 1
            print(f"  ✅ {name}")
        else:
            self.failed += 1
            print(f"  ❌ {name}: {detail}")

    def summary(self) -> str:
        total = self.passed + self.failed
        return f"\n{'='*60}\nResults: {self.passed}/{total} passed, {self.failed} failed\n{'='*60}"


async def test_adapter_initialization(results: TestResults):
    """Test: Adapter can initialize and discover devices."""
    print("\n--- Test: Adapter Initialization ---")
    event_bus = EventBus()
    adapter = MockAdapter(event_bus=event_bus)

    meta = await adapter.initialize("FloorPlan1")
    results.record("scene loads", meta["scene"] == "FloorPlan1")
    results.record("devices discovered", meta["device_count"] == 10, f"got {meta['device_count']}")
    results.record("device types present", len(meta["device_types"]) > 0)

    devices = await adapter.list_devices()
    results.record("list_devices returns CDDs", len(devices) == 10, f"got {len(devices)}")

    types = {d.device_type for d in devices}
    results.record("has FloorLamp", "FloorLamp" in types)
    results.record("has Fridge", "Fridge" in types)
    results.record("has Safe", "Safe" in types)

    return adapter, event_bus


async def test_device_state_query(results: TestResults, adapter: MockAdapter):
    """Test: Can query device states."""
    print("\n--- Test: Device State Query ---")

    state = await adapter.get_device_state("FloorLamp|+01.32|+00.00|+00.45")
    results.record("get lamp state", state.properties.get("isToggled") is False)

    state = await adapter.get_device_state("Television|+00.50|+01.20|+03.00")
    results.record("TV is initially on", state.properties.get("isToggled") is True)

    try:
        await adapter.get_device_state("NonExistent|+00.00|+00.00|+00.00")
        results.record("nonexistent device raises", False, "no exception raised")
    except ValueError:
        results.record("nonexistent device raises", True)


async def test_device_control(results: TestResults, adapter: MockAdapter):
    """Test: Can control device properties."""
    print("\n--- Test: Device Control ---")

    # Turn on lamp
    state = await adapter.set_property("FloorLamp|+01.32|+00.00|+00.45", "isToggled", True)
    results.record("turn on lamp", state.properties["isToggled"] is True)

    # Turn off TV
    state = await adapter.set_property("Television|+00.50|+01.20|+03.00", "isToggled", False)
    results.record("turn off TV", state.properties["isToggled"] is False)

    # Open fridge
    state = await adapter.set_property("Fridge|+03.00|+00.00|+02.50", "isOpen", True)
    results.record("open fridge", state.properties["isOpen"] is True)

    # Close fridge
    state = await adapter.set_property("Fridge|+03.00|+00.00|+02.50", "isOpen", False)
    results.record("close fridge", state.properties["isOpen"] is False)

    # Invalid property
    try:
        await adapter.set_property("FloorLamp|+01.32|+00.00|+00.45", "nonexistent", True)
        results.record("invalid property raises", False)
    except ValueError:
        results.record("invalid property raises", True)


async def test_safety_sandbox(results: TestResults, adapter: MockAdapter):
    """Test: Safety sandbox correctly blocks/allows actions."""
    print("\n--- Test: Safety Sandbox ---")

    sandbox = SafetySandbox(max_allowed=SafetyLevel.HIGH)
    devices = await adapter.list_devices()
    device_map = {d.device_id: d for d in devices}

    # LOW: lamp should be allowed
    lamp = device_map["FloorLamp|+01.32|+00.00|+00.45"]
    check = sandbox.check(lamp, "isToggled")
    results.record("LOW device allowed", check.allowed)

    # MEDIUM: fridge should be allowed
    fridge = device_map["Fridge|+03.00|+00.00|+02.50"]
    check = sandbox.check(fridge, "isOpen")
    results.record("MEDIUM device allowed", check.allowed)

    # HIGH: stove should be allowed (max_allowed=HIGH)
    stove = device_map["StoveBurner|+01.80|+00.90|+02.80"]
    check = sandbox.check(stove, "isToggled")
    results.record("HIGH device allowed", check.allowed)

    # CRITICAL: safe should be BLOCKED
    safe = device_map["Safe|+03.50|+00.00|+00.20"]
    check = sandbox.check(safe, "isOpen")
    results.record("CRITICAL device blocked", not check.allowed)
    results.record("CRITICAL requires confirmation", check.requires_confirmation)

    # Test with stricter sandbox (max=MEDIUM)
    strict_sandbox = SafetySandbox(max_allowed=SafetyLevel.MEDIUM)
    check = strict_sandbox.check(stove, "isToggled")
    results.record("HIGH blocked by strict sandbox", not check.allowed)


async def test_event_bus(results: TestResults, adapter: MockAdapter, event_bus: EventBus):
    """Test: Events are emitted on state changes."""
    print("\n--- Test: Event Bus ---")

    events_received = []
    event_bus.subscribe("state_changed", lambda e: events_received.append(e))

    await adapter.set_property("DeskLamp|+02.10|+00.78|+01.20", "isToggled", False)
    results.record("event emitted on control", len(events_received) > 0)
    results.record("event has device_id", events_received[-1].get("device_id") == "DeskLamp|+02.10|+00.78|+01.20")
    results.record("event has value", events_received[-1].get("value") is False)

    history = event_bus.get_history()
    results.record("history recorded", len(history) > 0)


async def test_image_capture(results: TestResults, adapter: MockAdapter):
    """Test: Can capture scene image."""
    print("\n--- Test: Image Capture ---")

    img_b64 = await adapter.capture_image()
    results.record("image is base64 string", isinstance(img_b64, str) and len(img_b64) > 100)

    import base64
    img_bytes = base64.b64decode(img_b64)
    results.record("image decodes to bytes", len(img_bytes) > 0)

    # Verify it's a valid PNG
    results.record("image is valid PNG", img_bytes[:4] == b'\x89PNG')

    # Save for inspection
    output_path = Path(__file__).parent / "test_output_mock_scene.png"
    output_path.write_bytes(img_bytes)
    results.record(f"image saved to {output_path.name}", output_path.exists())


async def test_multi_device_orchestration(results: TestResults, adapter: MockAdapter):
    """Test: Multi-device scenario (simulating 'going to sleep')."""
    print("\n--- Test: Multi-Device Orchestration ---")

    # Scenario: "I'm going to sleep" → turn off all lights + TV
    targets = [
        ("FloorLamp|+01.32|+00.00|+00.45", "isToggled", False),
        ("DeskLamp|+02.10|+00.78|+01.20", "isToggled", False),
        ("Television|+00.50|+01.20|+03.00", "isToggled", False),
    ]

    # First make sure some are on
    await adapter.set_property("FloorLamp|+01.32|+00.00|+00.45", "isToggled", True)
    await adapter.set_property("Television|+00.50|+01.20|+03.00", "isToggled", True)

    # Execute batch
    success_count = 0
    for device_id, prop, value in targets:
        state = await adapter.set_property(device_id, prop, value)
        if state.properties.get(prop) == value:
            success_count += 1

    results.record("all 3 devices controlled", success_count == 3)

    # Verify final states
    for device_id, prop, expected in targets:
        state = await adapter.get_device_state(device_id)
        if state.properties.get(prop) != expected:
            results.record(f"{device_id} final state", False)
            return

    results.record("all final states correct", True)


async def test_cdd_format(results: TestResults, adapter: MockAdapter):
    """Test: CDD serialization format matches spec."""
    print("\n--- Test: CDD Format ---")

    devices = await adapter.list_devices()
    lamp = next(d for d in devices if d.device_type == "FloorLamp")
    cdd_dict = lamp.to_dict()

    results.record("has device_id", "device_id" in cdd_dict)
    results.record("has device_type", "device_type" in cdd_dict)
    results.record("has safety_class", cdd_dict.get("safety_class") == "low")
    results.record("has capabilities list", isinstance(cdd_dict.get("capabilities"), list))
    results.record("capability has name", cdd_dict["capabilities"][0].get("name") == "isToggled")


async def main():
    results = TestResults()

    adapter, event_bus = await test_adapter_initialization(results)
    await test_device_state_query(results, adapter)
    await test_device_control(results, adapter)
    await test_safety_sandbox(results, adapter)
    await test_event_bus(results, adapter, event_bus)
    await test_image_capture(results, adapter)
    await test_multi_device_orchestration(results, adapter)
    await test_cdd_format(results, adapter)

    print(results.summary())

    # Save results as JSON for documentation
    output = {
        "test_run": "mock_adapter_full_pipeline",
        "total": results.passed + results.failed,
        "passed": results.passed,
        "failed": results.failed,
        "details": results.results,
    }
    output_path = Path(__file__).parent / "test_results.json"
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to: {output_path}")

    return results.failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
