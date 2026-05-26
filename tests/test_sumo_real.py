#!/usr/bin/env python3
"""Real SUMO Traffic integration tests.

Tests actual SUMO simulation via TraCI protocol with intersection scenario.
Run with: python tests/test_sumo_real.py

Requires:
- eclipse-sumo (pip) with working binary
- OR: sumo system package (apt install sumo)
- traci, sumolib Python packages
"""

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Ensure libatomic is findable (for eclipse-sumo pip package on systems without it)
_LIB_DIR = str(Path(__file__).parent.parent.parent / "lib")
os.environ["LD_LIBRARY_PATH"] = _LIB_DIR + ":" + os.environ.get("LD_LIBRARY_PATH", "")

from harness.adapters.sumo.config import SCENES, SUMO_BINARY, VEHICLE_PROPERTIES
from harness.events import EventBus

OUTPUT_DIR = Path(__file__).parent / "sumo_results"
OUTPUT_DIR.mkdir(exist_ok=True)

SCENARIO_DIR = Path(__file__).parent.parent / "harness" / "adapters" / "sumo" / "scenarios"


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


def test_prerequisites(results: TestResults) -> bool:
    """Check all prerequisites for SUMO testing."""
    print(f"\n{'='*60}")
    print("TEST: Prerequisites")
    print(f"{'='*60}")

    # Check Python packages
    try:
        import traci
        results.record("traci importable", True, f"version={traci.constants.TRACI_VERSION}")
    except ImportError as e:
        results.record("traci importable", False, str(e))
        return False

    try:
        import sumolib
        results.record("sumolib importable", True)
    except ImportError as e:
        results.record("sumolib importable", False, str(e))
        return False

    # Check SUMO binary
    sumo_path = shutil.which("sumo")
    results.record("sumo binary found", sumo_path is not None,
                   f"path={sumo_path}" if sumo_path else "not in PATH")

    if sumo_path:
        import subprocess
        proc = subprocess.run([sumo_path, "--version"], capture_output=True, text=True)
        if proc.returncode == 0:
            version_line = proc.stdout.strip().split("\n")[0]
            results.record("sumo binary works", True, version_line)
        else:
            error = proc.stderr.strip()[:100]
            results.record("sumo binary works", False, error)
            return False
    else:
        return False

    # Check scenario files
    cfg_path = SCENARIO_DIR / "intersection.sumocfg"
    results.record("intersection.sumocfg exists", cfg_path.exists())
    net_path = SCENARIO_DIR / "intersection.net.xml"
    results.record("intersection.net.xml exists", net_path.exists())
    rou_path = SCENARIO_DIR / "intersection.rou.xml"
    results.record("intersection.rou.xml exists", rou_path.exists())

    return True


async def test_traci_connection(results: TestResults):
    """Test raw TraCI connection to SUMO."""
    print(f"\n{'='*60}")
    print("TEST: TraCI Connection")
    print(f"{'='*60}")

    import traci
    import sumolib

    sumo_binary = sumolib.checkBinary("sumo")
    cfg_path = str(SCENARIO_DIR / "intersection.sumocfg")

    with results.time_it("traci_start"):
        traci.start([sumo_binary, "-c", cfg_path, "--no-step-log", "--no-warnings"])

    results.record("traci connected", traci.isLoaded())
    print(f"  ⏱️ SUMO start: {results.perf['traci_start']*1000:.0f}ms")

    return True


async def test_simulation_step(results: TestResults):
    """Test stepping the simulation."""
    print(f"\n{'='*60}")
    print("TEST: Simulation Stepping")
    print(f"{'='*60}")

    import traci

    # Step to time=1.0 (10 steps at 0.1s step length)
    with results.time_it("step_10"):
        for _ in range(10):
            traci.simulationStep()

    sim_time = traci.simulation.getTime()
    results.record("simulation advanced", sim_time >= 1.0, f"time={sim_time:.1f}s")
    print(f"  ⏱️ 10 steps: {results.perf['step_10']*1000:.0f}ms")


async def test_vehicle_discovery(results: TestResults):
    """Test discovering vehicles in the simulation."""
    print(f"\n{'='*60}")
    print("TEST: Vehicle Discovery")
    print(f"{'='*60}")

    import traci

    # Step a few more times to let vehicles enter
    for _ in range(50):
        traci.simulationStep()

    vehicle_ids = traci.vehicle.getIDList()
    results.record("vehicles present", len(vehicle_ids) > 0, f"count={len(vehicle_ids)}")

    for vid in vehicle_ids:
        speed = traci.vehicle.getSpeed(vid)
        pos = traci.vehicle.getPosition(vid)
        lane = traci.vehicle.getLaneID(vid)
        results.record(f"vehicle {vid} readable",
                       speed >= 0 and pos is not None,
                       f"speed={speed:.1f}m/s, pos=({pos[0]:.1f},{pos[1]:.1f}), lane={lane}")

    return vehicle_ids


async def test_traffic_light_discovery(results: TestResults):
    """Test discovering traffic lights."""
    print(f"\n{'='*60}")
    print("TEST: Traffic Light Discovery")
    print(f"{'='*60}")

    import traci

    tl_ids = traci.trafficlight.getIDList()
    results.record("traffic lights found", len(tl_ids) > 0, f"count={len(tl_ids)}")

    for tl_id in tl_ids:
        phase = traci.trafficlight.getPhase(tl_id)
        state = traci.trafficlight.getRedYellowGreenState(tl_id)
        program = traci.trafficlight.getProgram(tl_id)
        results.record(f"TL {tl_id} readable", True,
                       f"phase={phase}, state={state}, program={program}")

    return tl_ids


async def test_vehicle_control(results: TestResults, vehicle_ids: list):
    """Test controlling vehicle speed."""
    print(f"\n{'='*60}")
    print("TEST: Vehicle Speed Control")
    print(f"{'='*60}")

    import traci

    if not vehicle_ids:
        results.record("vehicle control", False, "no vehicles available")
        return

    target_vid = vehicle_ids[0]
    original_speed = traci.vehicle.getSpeed(target_vid)

    # Set speed
    target_speed = 5.0
    with results.time_it("set_speed"):
        traci.vehicle.setSpeed(target_vid, target_speed)
        for _ in range(20):
            traci.simulationStep()

    new_speed = traci.vehicle.getSpeed(target_vid)
    results.record("speed changed", abs(new_speed - target_speed) < 1.0,
                   f"target={target_speed}, actual={new_speed:.2f}")

    # Reset speed (let SUMO control again)
    traci.vehicle.setSpeed(target_vid, -1)
    print(f"  ⏱️ Set speed: {results.perf['set_speed']*1000:.0f}ms")


async def test_traffic_light_control(results: TestResults, tl_ids: list):
    """Test changing traffic light state."""
    print(f"\n{'='*60}")
    print("TEST: Traffic Light Control")
    print(f"{'='*60}")

    import traci

    if not tl_ids:
        results.record("TL control", False, "no traffic lights")
        return

    tl_id = tl_ids[0]
    original_state = traci.trafficlight.getRedYellowGreenState(tl_id)
    results.record("original state readable", len(original_state) > 0,
                   f"state={original_state}")

    # Set all to red
    target_state = "r" * len(original_state)
    with results.time_it("set_red"):
        traci.trafficlight.setRedYellowGreenState(tl_id, target_state)
        traci.simulationStep()

    new_state = traci.trafficlight.getRedYellowGreenState(tl_id)
    results.record("set all red", new_state == target_state,
                   f"expected={target_state}, actual={new_state}")

    # Set all to green
    green_state = "G" * len(original_state)
    with results.time_it("set_green"):
        traci.trafficlight.setRedYellowGreenState(tl_id, green_state)
        traci.simulationStep()

    new_state = traci.trafficlight.getRedYellowGreenState(tl_id)
    results.record("set all green", new_state == green_state,
                   f"expected={green_state}, actual={new_state}")

    print(f"  ⏱️ Set red: {results.perf['set_red']*1000:.0f}ms")
    print(f"  ⏱️ Set green: {results.perf['set_green']*1000:.0f}ms")


async def test_adapter_integration(results: TestResults):
    """Test the full SUMOAdapter (if SUMO works)."""
    print(f"\n{'='*60}")
    print("TEST: Full Adapter Integration")
    print(f"{'='*60}")

    import traci
    # Close existing connection first (may already be closed)
    try:
        traci.close()
    except Exception:
        pass
    await asyncio.sleep(0.3)

    from harness.adapters.sumo.adapter import SUMOAdapter

    event_bus = EventBus()
    adapter = SUMOAdapter(event_bus=event_bus)

    with results.time_it("adapter_init"):
        meta = await adapter.initialize("intersection")

    results.record("adapter init succeeds", meta is not None)
    results.record("engine is sumo", meta.get("engine") == "sumo",
                   f"got: {meta.get('engine')}")
    results.record("device_count >= 0", meta.get("device_count", -1) >= 0,
                   f"count={meta.get('device_count')}")

    # Allow simulation loop to step and discover vehicles
    await asyncio.sleep(1.0)

    devices = await adapter.list_devices()
    results.record("devices found", len(devices) > 0, f"count={len(devices)}")

    device_types = set(d.device_type for d in devices)
    results.record("has traffic_light type", "traffic_light" in device_types)
    # Vehicles may or may not be present depending on sim time
    has_vehicles = "vehicle" in device_types
    results.record("has vehicle type (after step)", has_vehicles,
                   f"types={device_types}" if not has_vehicles else "")

    # Get a traffic light state
    tl_devices = [d for d in devices if d.device_type == "traffic_light"]
    if tl_devices:
        tl = tl_devices[0]
        state = await adapter.get_device_state(tl.device_id)
        results.record("TL state readable", state is not None,
                       f"props={list(state.properties.keys())}")

    await adapter.shutdown()
    results.record("adapter shutdown", True)
    print(f"  ⏱️ Adapter init: {results.perf['adapter_init']*1000:.0f}ms")


async def main():
    results = TestResults()
    start_time = time.time()

    print("=" * 60)
    print("SUMO TRAFFIC REAL INTEGRATION TESTS")
    print("=" * 60)
    print(f"Python: {sys.version.split()[0]}")
    print(f"SUMO_HOME: {os.environ.get('SUMO_HOME', 'not set')}")

    import traci
    can_run = test_prerequisites(results)

    if not can_run:
        print(f"\n⚠️  SUMO binary not functional. Skipping simulation tests.")
        print("   Fix: install libatomic1 (sudo apt install libatomic1)")
        print("   Or: sudo apt install sumo")
    else:
        try:
            await test_traci_connection(results)
            await test_simulation_step(results)
            vehicle_ids = await test_vehicle_discovery(results)
            tl_ids = await test_traffic_light_discovery(results)
            await test_vehicle_control(results, vehicle_ids)
            await test_traffic_light_control(results, tl_ids)

            # Close raw traci before adapter test
            traci.close()
            await asyncio.sleep(0.2)

            await test_adapter_integration(results)
        except Exception as e:
            print(f"\n💥 FATAL ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.record("test execution", False, str(e))
        finally:
            try:
                traci.close()
            except Exception:
                pass

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
        "test_run": "sumo_real_integration",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "sumo_binary": shutil.which("sumo"),
            "sumo_home": os.environ.get("SUMO_HOME", ""),
            "traci_version": traci.constants.TRACI_VERSION,
        },
        "sumo_binary_functional": can_run,
        "total_time_seconds": total_time,
        "passed": results.passed,
        "failed": results.failed,
        "total": results.passed + results.failed,
        "performance": results.perf,
        "details": results.results,
        "blockers": [] if can_run else [
            "libatomic.so.1 missing (SUMO binary cannot load)",
            "Fix: sudo apt install libatomic1, or use system sumo package",
        ],
    }
    report_path = OUTPUT_DIR / "real_test_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nFull report: {report_path}")

    return results.failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
