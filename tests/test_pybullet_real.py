#!/usr/bin/env python3
"""Real PyBullet integration tests.

Tests actual physics simulation with Franka Panda robot arm.
Run with: python tests/test_pybullet_real.py

Requires:
- pybullet>=3.2.0
- numpy
- Pillow
"""

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.adapters.pybullet_arm.adapter import PyBulletArmAdapter
from harness.adapters.pybullet_arm.config import (
    DEVICE_ID,
    GRIPPER_RANGE,
    HOME_POSITION,
    JOINT_NAMES,
    JOINT_RANGES,
)
from harness.events import EventBus
from harness.models import SafetyLevel
from harness.safety import SafetySandbox

OUTPUT_DIR = Path(__file__).parent / "pybullet_results"
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


async def test_initialization(results: TestResults):
    """Test loading Franka Panda URDF and initializing physics."""
    print(f"\n{'='*60}")
    print("TEST: Initialization (table_top scene)")
    print(f"{'='*60}")

    event_bus = EventBus()
    adapter = PyBulletArmAdapter(event_bus=event_bus, render_mode="DIRECT")

    with results.time_it("initialize"):
        meta = await adapter.initialize("table_top")

    results.record("initialize succeeds", meta is not None)
    results.record("engine is pybullet", meta.get("engine") == "pybullet",
                   f"got: {meta.get('engine')}")
    results.record("model is franka_panda", meta.get("model") == "franka_panda")
    results.record("7 joints reported", meta.get("joints") == 7, f"got: {meta.get('joints')}")
    results.record("1 device", meta.get("device_count") == 1)
    print(f"  ⏱️ Init time: {results.perf['initialize']:.3f}s")

    return adapter, event_bus


async def test_device_discovery(results: TestResults, adapter: PyBulletArmAdapter):
    """Test device listing."""
    print(f"\n{'='*60}")
    print("TEST: Device Discovery")
    print(f"{'='*60}")

    with results.time_it("list_devices"):
        devices = await adapter.list_devices()

    results.record("one device returned", len(devices) == 1, f"got {len(devices)}")

    device = devices[0]
    results.record("device_id is franka_panda", device.device_id == DEVICE_ID)
    results.record("device_type is robot_arm", device.device_type == "robot_arm")

    cap_names = [c.name for c in device.capabilities]
    for jname in JOINT_NAMES:
        results.record(f"has joint cap: {jname}", jname in cap_names)

    results.record("has gripper_width cap", "gripper_width" in cap_names)
    results.record("has end_effector_position cap", "end_effector_position" in cap_names)
    results.record("has home action", "home" in cap_names)
    results.record("has pick action", "pick" in cap_names)
    results.record("has place action", "place" in cap_names)

    return device


async def test_state_reading(results: TestResults, adapter: PyBulletArmAdapter):
    """Test reading joint states from physics simulation."""
    print(f"\n{'='*60}")
    print("TEST: State Reading (physics-backed)")
    print(f"{'='*60}")

    with results.time_it("get_state"):
        state = await adapter.get_device_state(DEVICE_ID)

    props = state.properties
    results.record("has all joint states", all(j in props for j in JOINT_NAMES))

    # Joints should be at home position (approximately)
    for i, jname in enumerate(JOINT_NAMES):
        diff = abs(props[jname] - HOME_POSITION[i])
        results.record(f"{jname} near home", diff < 0.1,
                       f"value={props[jname]:.4f}, home={HOME_POSITION[i]:.4f}, diff={diff:.4f}")

    results.record("has gripper_width", "gripper_width" in props,
                   f"value={props.get('gripper_width', 'missing')}")
    results.record("has end_effector_position", "end_effector_position" in props)

    ee_pos = props.get("end_effector_position", [])
    if ee_pos:
        results.record("end_effector is 3D", len(ee_pos) == 3,
                       f"pos={[f'{v:.3f}' for v in ee_pos]}")

    print(f"  ⏱️ State read time: {results.perf['get_state']*1000:.1f}ms")
    return props


async def test_joint_control(results: TestResults, adapter: PyBulletArmAdapter):
    """Test setting individual joint angles with physics stepping."""
    print(f"\n{'='*60}")
    print("TEST: Joint Control (real physics)")
    print(f"{'='*60}")

    # Move joint 1 to 0.5 rad
    target = 0.5
    with results.time_it("set_joint1"):
        state = await adapter.set_property(DEVICE_ID, "panda_joint1", target)

    actual = state.properties["panda_joint1"]
    diff = abs(actual - target)
    results.record("joint1 moved to target", diff < 0.05,
                   f"target={target}, actual={actual:.4f}, err={diff:.4f}")
    print(f"  ⏱️ Joint move time: {results.perf['set_joint1']*1000:.0f}ms")

    # Move joint 4 to mid-range
    j4_low, j4_high = JOINT_RANGES["panda_joint4"]
    j4_target = (j4_low + j4_high) / 2
    with results.time_it("set_joint4"):
        state = await adapter.set_property(DEVICE_ID, "panda_joint4", j4_target)

    actual4 = state.properties["panda_joint4"]
    diff4 = abs(actual4 - j4_target)
    results.record("joint4 moved to mid-range", diff4 < 0.1,
                   f"target={j4_target:.3f}, actual={actual4:.4f}")

    # Test range validation
    try:
        await adapter.set_property(DEVICE_ID, "panda_joint1", 99.0)
        results.record("rejects out-of-range", False, "no error raised")
    except ValueError as e:
        results.record("rejects out-of-range", True, str(e)[:60])


async def test_gripper_control(results: TestResults, adapter: PyBulletArmAdapter):
    """Test gripper open/close with physics."""
    print(f"\n{'='*60}")
    print("TEST: Gripper Control")
    print(f"{'='*60}")

    # Open gripper fully
    with results.time_it("open_gripper"):
        result = await adapter.invoke_action(DEVICE_ID, "open_gripper")
    results.record("open_gripper succeeds", result["success"])

    state = await adapter.get_device_state(DEVICE_ID)
    gw = state.properties["gripper_width"]
    results.record("gripper is open", gw > GRIPPER_RANGE[1] * 0.7,
                   f"width={gw:.4f}, max={GRIPPER_RANGE[1]}")

    # Close gripper
    with results.time_it("close_gripper"):
        result = await adapter.invoke_action(DEVICE_ID, "close_gripper")
    results.record("close_gripper succeeds", result["success"])

    state = await adapter.get_device_state(DEVICE_ID)
    gw = state.properties["gripper_width"]
    results.record("gripper is closed", gw < GRIPPER_RANGE[1] * 0.3,
                   f"width={gw:.4f}")
    print(f"  ⏱️ Open: {results.perf['open_gripper']*1000:.0f}ms, "
          f"Close: {results.perf['close_gripper']*1000:.0f}ms")


async def test_home_action(results: TestResults, adapter: PyBulletArmAdapter):
    """Test return-to-home action."""
    print(f"\n{'='*60}")
    print("TEST: Home Action")
    print(f"{'='*60}")

    # First move away from home
    await adapter.set_property(DEVICE_ID, "panda_joint1", 1.0)
    await adapter.set_property(DEVICE_ID, "panda_joint2", -0.3)

    # Return home
    with results.time_it("home_action"):
        result = await adapter.invoke_action(DEVICE_ID, "home")
    results.record("home action succeeds", result["success"])

    state = await adapter.get_device_state(DEVICE_ID)
    max_diff = 0.0
    for i, jname in enumerate(JOINT_NAMES):
        diff = abs(state.properties[jname] - HOME_POSITION[i])
        max_diff = max(max_diff, diff)

    results.record("all joints near home", max_diff < 0.1, f"max_diff={max_diff:.4f}")
    print(f"  ⏱️ Home action: {results.perf['home_action']*1000:.0f}ms")


async def test_pick_place_sequence(results: TestResults, adapter: PyBulletArmAdapter):
    """Test pick and place IK-based actions."""
    print(f"\n{'='*60}")
    print("TEST: Pick & Place (IK + physics)")
    print(f"{'='*60}")

    # Return home first
    await adapter.invoke_action(DEVICE_ID, "home")

    # Pick action
    pick_params = {"x": 0.4, "y": 0.0, "z": 0.05}
    with results.time_it("pick_action"):
        result = await adapter.invoke_action(DEVICE_ID, "pick", pick_params)
    results.record("pick action succeeds", result["success"])

    state_after_pick = await adapter.get_device_state(DEVICE_ID)
    ee_pos = state_after_pick.properties["end_effector_position"]
    results.record("end_effector moved", ee_pos is not None,
                   f"pos=[{ee_pos[0]:.3f}, {ee_pos[1]:.3f}, {ee_pos[2]:.3f}]")

    # Gripper should be closed after pick
    gw = state_after_pick.properties["gripper_width"]
    results.record("gripper closed after pick", gw < GRIPPER_RANGE[1] * 0.3,
                   f"width={gw:.4f}")

    # Place action
    place_params = {"x": 0.4, "y": 0.2, "z": 0.05}
    with results.time_it("place_action"):
        result = await adapter.invoke_action(DEVICE_ID, "place", place_params)
    results.record("place action succeeds", result["success"])

    state_after_place = await adapter.get_device_state(DEVICE_ID)
    gw = state_after_place.properties["gripper_width"]
    results.record("gripper open after place", gw > GRIPPER_RANGE[1] * 0.7,
                   f"width={gw:.4f}")

    print(f"  ⏱️ Pick: {results.perf['pick_action']*1000:.0f}ms, "
          f"Place: {results.perf['place_action']*1000:.0f}ms")


async def test_image_capture(results: TestResults, adapter: PyBulletArmAdapter):
    """Test scene rendering in DIRECT mode."""
    print(f"\n{'='*60}")
    print("TEST: Image Capture (software render)")
    print(f"{'='*60}")

    with results.time_it("capture_image"):
        img_b64 = await adapter.capture_image()

    results.record("image returned", len(img_b64) > 100, f"{len(img_b64)} chars base64")

    img_bytes = base64.b64decode(img_b64)
    results.record("valid PNG", img_bytes[:4] == b'\x89PNG', f"{len(img_bytes)} bytes")

    img_path = OUTPUT_DIR / "pybullet_scene.png"
    img_path.write_bytes(img_bytes)
    results.record(f"saved to {img_path.name}", img_path.exists())
    print(f"  ⏱️ Render time: {results.perf['capture_image']*1000:.0f}ms")


async def test_event_tracking(results: TestResults, adapter: PyBulletArmAdapter, event_bus: EventBus):
    """Test event emission during control."""
    print(f"\n{'='*60}")
    print("TEST: Event Bus Integration")
    print(f"{'='*60}")

    events_before = len(event_bus.get_history(limit=1000))

    await adapter.set_property(DEVICE_ID, "panda_joint1", 0.3)
    await adapter.invoke_action(DEVICE_ID, "open_gripper")

    events_after = len(event_bus.get_history(limit=1000))
    new_events = events_after - events_before

    results.record("events emitted", new_events >= 2, f"{new_events} new events")

    history = event_bus.get_history(limit=5)
    has_state_changed = any(e.get("type") == "state_changed" for e in history)
    has_action = any(e.get("type") == "action_executed" for e in history)
    results.record("has state_changed event", has_state_changed)
    results.record("has action_executed event", has_action)


async def test_shutdown(results: TestResults, adapter: PyBulletArmAdapter):
    """Test clean shutdown."""
    print(f"\n{'='*60}")
    print("TEST: Shutdown")
    print(f"{'='*60}")

    await adapter.shutdown()
    results.record("shutdown completes", not adapter.is_initialized)


async def main():
    results = TestResults()
    start_time = time.time()

    print("=" * 60)
    print("PYBULLET REAL INTEGRATION TESTS")
    print("=" * 60)
    print(f"Python: {sys.version.split()[0]}")

    try:
        import pybullet
        print(f"PyBullet: {pybullet.getAPIVersion()}")
    except Exception as e:
        print(f"PyBullet import failed: {e}")
        return False

    try:
        adapter, event_bus = await test_initialization(results)
        await test_device_discovery(results, adapter)
        await test_state_reading(results, adapter)
        await test_joint_control(results, adapter)
        await test_gripper_control(results, adapter)
        await test_home_action(results, adapter)
        await test_pick_place_sequence(results, adapter)
        await test_image_capture(results, adapter)
        await test_event_tracking(results, adapter, event_bus)
        await test_shutdown(results, adapter)
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

    if results.perf:
        print("\n  Performance:")
        for label, elapsed in sorted(results.perf.items()):
            print(f"    {label}: {elapsed:.3f}s")

    report = {
        "test_run": "pybullet_real_integration",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "pybullet_version": str(pybullet.getAPIVersion()),
            "render_mode": "DIRECT",
        },
        "total_time_seconds": total_time,
        "passed": results.passed,
        "failed": results.failed,
        "total": results.passed + results.failed,
        "performance": results.perf,
        "details": results.results,
    }
    report_path = OUTPUT_DIR / "real_test_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nFull report: {report_path}")

    return results.failed == 0


if __name__ == "__main__":
    import pybullet
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
