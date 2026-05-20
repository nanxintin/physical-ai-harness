#!/usr/bin/env python3
"""Real AI2-THOR integration tests.

Tests actual Unity-rendered scenes with physical device interactions.
Run with: python tests/test_ai2thor_real.py

Requires:
- AI2-THOR binary downloaded (~769MB in ~/.ai2thor/releases/)
- Display available (DISPLAY=:0 or xvfb-run)
"""

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.adapters.ai2thor_adapter import AI2ThorAdapter
from harness.events import EventBus
from harness.models import SafetyLevel
from harness.safety import SafetySandbox

OUTPUT_DIR = Path(__file__).parent / "ai2thor_results"
OUTPUT_DIR.mkdir(exist_ok=True)


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results: list[dict] = []
        self.perf: dict[str, float] = {}

    def record(self, name: str, passed: bool, detail: str = ""):
        self.results.append({"name": name, "passed": passed, "detail": detail})
        if passed:
            self.passed += 1
            print(f"  ✅ {name}" + (f" ({detail})" if detail else ""))
        else:
            self.failed += 1
            print(f"  ❌ {name}: {detail}")

    def time_it(self, label: str):
        return _Timer(self, label)


class _Timer:
    def __init__(self, results: TestResults, label: str):
        self.results = results
        self.label = label

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        elapsed = time.time() - self.start
        self.results.perf[self.label] = elapsed


async def test_scene_loading(results: TestResults):
    """Test loading multiple scenes and measuring startup time."""
    print("\n{'='*60}")
    print("TEST: Scene Loading")
    print("{'='*60}")

    event_bus = EventBus()
    adapter = AI2ThorAdapter(event_bus=event_bus)

    # FloorPlan1 - Kitchen
    with results.time_it("scene_load_FloorPlan1"):
        meta = await adapter.initialize("FloorPlan1")

    results.record("FloorPlan1 loads", meta["device_count"] > 0, f"{meta['device_count']} devices")
    results.record("has device types", len(meta["device_types"]) > 0, f"types: {meta['device_types']}")
    print(f"  ⏱️ Load time: {results.perf['scene_load_FloorPlan1']:.1f}s")

    return adapter, event_bus


async def test_device_discovery(results: TestResults, adapter: AI2ThorAdapter):
    """Test device discovery in detail."""
    print(f"\n{'='*60}")
    print("TEST: Device Discovery (FloorPlan1 - Kitchen)")
    print(f"{'='*60}")

    with results.time_it("list_devices"):
        devices = await adapter.list_devices()

    results.record("devices found", len(devices) > 0, f"{len(devices)} total")

    # Categorize by type
    type_counts: dict[str, int] = {}
    safety_counts: dict[str, int] = {}
    for d in devices:
        type_counts[d.device_type] = type_counts.get(d.device_type, 0) + 1
        safety_counts[d.safety_class.value] = safety_counts.get(d.safety_class.value, 0) + 1

    print(f"\n  Device types ({len(type_counts)}):")
    for t, count in sorted(type_counts.items()):
        print(f"    {t}: {count}")

    print(f"\n  Safety distribution:")
    for level, count in sorted(safety_counts.items()):
        print(f"    {level}: {count}")

    results.record("has toggleable devices", any(
        any(c.name == "isToggled" for c in d.capabilities) for d in devices
    ))
    results.record("has openable devices", any(
        any(c.name == "isOpen" for c in d.capabilities) for d in devices
    ))

    # Save device catalog
    catalog = [d.to_dict() for d in devices]
    (OUTPUT_DIR / "device_catalog.json").write_text(json.dumps(catalog, indent=2))
    results.record("device catalog saved", True)

    return devices


async def test_device_control(results: TestResults, adapter: AI2ThorAdapter, devices):
    """Test controlling various device types."""
    print(f"\n{'='*60}")
    print("TEST: Device Control")
    print(f"{'='*60}")

    sandbox = SafetySandbox(max_allowed=SafetyLevel.HIGH)
    control_log = []

    # Find devices by capability
    toggleable = [d for d in devices if any(c.name == "isToggled" for c in d.capabilities)]
    openable = [d for d in devices if any(c.name == "isOpen" for c in d.capabilities)]

    # Test toggle operations
    toggle_success = 0
    toggle_fail = 0
    print(f"\n  --- Toggle Tests ({len(toggleable)} devices) ---")
    for device in toggleable[:8]:
        check = sandbox.check(device, "isToggled")
        if not check.allowed:
            print(f"    ⚠️ {device.device_type} ({device.safety_class.value}) - blocked by safety")
            control_log.append({"device": device.device_id, "action": "toggle_on", "result": "blocked", "safety": device.safety_class.value})
            continue

        try:
            with results.time_it(f"toggle_{device.device_type}"):
                state = await adapter.set_property(device.device_id, "isToggled", True)
            toggle_success += 1
            print(f"    ✅ {device.device_type}: isToggled → {state.properties.get('isToggled')}")
            control_log.append({"device": device.device_id, "type": device.device_type, "action": "toggle_on", "result": "success", "new_state": state.properties})

            # Toggle back off
            await adapter.set_property(device.device_id, "isToggled", False)
        except Exception as e:
            toggle_fail += 1
            print(f"    ❌ {device.device_type}: {e}")
            control_log.append({"device": device.device_id, "type": device.device_type, "action": "toggle_on", "result": "error", "error": str(e)})

    results.record("toggle operations", toggle_success > 0, f"{toggle_success} success, {toggle_fail} failed")

    # Test open operations
    open_success = 0
    open_fail = 0
    print(f"\n  --- Open Tests ({len(openable)} devices) ---")
    for device in openable[:8]:
        check = sandbox.check(device, "isOpen")
        if not check.allowed:
            print(f"    ⚠️ {device.device_type} ({device.safety_class.value}) - blocked by safety")
            control_log.append({"device": device.device_id, "action": "open", "result": "blocked"})
            continue

        try:
            with results.time_it(f"open_{device.device_type}"):
                state = await adapter.set_property(device.device_id, "isOpen", True)
            open_success += 1
            print(f"    ✅ {device.device_type}: isOpen → {state.properties.get('isOpen')}")
            control_log.append({"device": device.device_id, "type": device.device_type, "action": "open", "result": "success", "new_state": state.properties})

            # Close back
            await adapter.set_property(device.device_id, "isOpen", False)
        except Exception as e:
            open_fail += 1
            print(f"    ❌ {device.device_type}: {e}")
            control_log.append({"device": device.device_id, "type": device.device_type, "action": "open", "result": "error", "error": str(e)})

    results.record("open operations", open_success > 0, f"{open_success} success, {open_fail} failed")

    # Save control log
    (OUTPUT_DIR / "control_log.json").write_text(json.dumps(control_log, indent=2))
    return control_log


async def test_image_capture(results: TestResults, adapter: AI2ThorAdapter):
    """Test scene image capture."""
    print(f"\n{'='*60}")
    print("TEST: Image Capture")
    print(f"{'='*60}")

    with results.time_it("capture_image"):
        img_b64 = await adapter.capture_image()

    img_bytes = base64.b64decode(img_b64)
    results.record("image captured", len(img_bytes) > 1000, f"{len(img_bytes)} bytes")
    results.record("valid PNG", img_bytes[:4] == b'\x89PNG')

    # Save image
    img_path = OUTPUT_DIR / "scene_capture_FloorPlan1.png"
    img_path.write_bytes(img_bytes)
    results.record(f"saved to {img_path.name}", img_path.exists())
    print(f"  ⏱️ Capture time: {results.perf['capture_image']:.3f}s")


async def test_multi_device_scenario(results: TestResults, adapter: AI2ThorAdapter, devices):
    """Test multi-device orchestration scenario."""
    print(f"\n{'='*60}")
    print("TEST: Multi-Device Orchestration")
    print(f"{'='*60}")

    sandbox = SafetySandbox(max_allowed=SafetyLevel.HIGH)
    toggleable = [d for d in devices if any(c.name == "isToggled" for c in d.capabilities)]
    safe_toggleable = [d for d in toggleable if sandbox.check(d).allowed]

    if len(safe_toggleable) < 2:
        results.record("multi-device scenario", False, "not enough safe toggleable devices")
        return

    print(f"\n  Scenario: 'Turn off everything' ({len(safe_toggleable)} devices)")
    with results.time_it("multi_device_off"):
        success_count = 0
        for device in safe_toggleable:
            try:
                await adapter.set_property(device.device_id, "isToggled", False)
                success_count += 1
            except Exception:
                pass

    results.record("batch off", success_count == len(safe_toggleable),
                   f"{success_count}/{len(safe_toggleable)}")
    print(f"  ⏱️ Total time: {results.perf['multi_device_off']:.2f}s "
          f"({results.perf['multi_device_off']/max(success_count,1)*1000:.0f}ms per device)")

    # Scenario: turn on specific devices
    print(f"\n  Scenario: 'Turn on lights only'")
    lights = [d for d in safe_toggleable if "Lamp" in d.device_type or "Light" in d.device_type]
    with results.time_it("lights_on"):
        light_success = 0
        for device in lights:
            try:
                await adapter.set_property(device.device_id, "isToggled", True)
                light_success += 1
            except Exception:
                pass

    results.record("lights on", light_success == len(lights) if lights else True,
                   f"{light_success}/{len(lights)} lights")


async def test_event_tracking(results: TestResults, adapter: AI2ThorAdapter, event_bus: EventBus):
    """Test event emission during control."""
    print(f"\n{'='*60}")
    print("TEST: Event Tracking")
    print(f"{'='*60}")

    events_before = len(event_bus.get_history(limit=1000))

    devices = await adapter.list_devices()
    toggleable = [d for d in devices if any(c.name == "isToggled" for c in d.capabilities)
                  and d.safety_class != SafetyLevel.CRITICAL]

    if toggleable:
        target = toggleable[0]
        await adapter.set_property(target.device_id, "isToggled", True)
        await adapter.set_property(target.device_id, "isToggled", False)

    events_after = len(event_bus.get_history(limit=1000))
    new_events = events_after - events_before

    results.record("events emitted", new_events >= 2, f"{new_events} new events")

    history = event_bus.get_history(limit=5)
    (OUTPUT_DIR / "event_history.json").write_text(json.dumps(history, indent=2, default=str))
    results.record("event history saved", True)


async def test_safety_in_practice(results: TestResults, adapter: AI2ThorAdapter, devices):
    """Test safety sandbox with real devices."""
    print(f"\n{'='*60}")
    print("TEST: Safety Sandbox (Real Devices)")
    print(f"{'='*60}")

    sandbox = SafetySandbox(max_allowed=SafetyLevel.HIGH)

    blocked_count = 0
    allowed_count = 0
    for device in devices:
        check = sandbox.check(device)
        if check.allowed:
            allowed_count += 1
        else:
            blocked_count += 1
            print(f"  🛑 {device.device_type} ({device.safety_class.value}): {check.reason}")

    results.record("safety allows most devices", allowed_count > blocked_count)
    results.record("safety summary", True, f"{allowed_count} allowed, {blocked_count} blocked")


async def main():
    results = TestResults()
    start_time = time.time()

    print("=" * 60)
    print("AI2-THOR REAL INTEGRATION TESTS")
    print("=" * 60)
    print(f"Environment: DISPLAY={os.environ.get('DISPLAY', 'unset')}")
    print(f"Python: {sys.version.split()[0]}")

    try:
        adapter, event_bus = await test_scene_loading(results)
        devices = await test_device_discovery(results, adapter)
        await test_device_control(results, adapter, devices)
        await test_image_capture(results, adapter)
        await test_multi_device_scenario(results, adapter, devices)
        await test_event_tracking(results, adapter, event_bus)
        await test_safety_in_practice(results, adapter, devices)
    except Exception as e:
        print(f"\n💥 FATAL ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        results.record("test execution", False, str(e))

    total_time = time.time() - start_time

    print(f"\n{'='*60}")
    print(f"RESULTS: {results.passed}/{results.passed + results.failed} passed")
    print(f"TOTAL TIME: {total_time:.1f}s")
    print(f"{'='*60}")

    # Performance summary
    if results.perf:
        print("\n  Performance:")
        for label, elapsed in sorted(results.perf.items()):
            print(f"    {label}: {elapsed:.3f}s")

    # Save full report
    report = {
        "test_run": "ai2thor_real_integration",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "environment": {
            "display": os.environ.get("DISPLAY", "unset"),
            "python": sys.version.split()[0],
            "platform": sys.platform,
        },
        "total_time_seconds": total_time,
        "passed": results.passed,
        "failed": results.failed,
        "total": results.passed + results.failed,
        "performance": results.perf,
        "details": results.results,
    }
    (OUTPUT_DIR / "test_report.json").write_text(json.dumps(report, indent=2))
    print(f"\nFull report saved to: {OUTPUT_DIR}/test_report.json")

    return results.failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
