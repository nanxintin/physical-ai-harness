#!/usr/bin/env python3
"""Real MQTT IoT integration tests.

Tests actual MQTT pub/sub communication with a real broker and simulated devices.
Runs an in-process mini MQTT broker + virtual device simulator.

Run with: python tests/test_mqtt_real.py

Requires:
- paho-mqtt>=1.6.0
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.mini_mqtt_broker import MiniMQTTBroker
from tests.mqtt_virtual_devices import VirtualDeviceSimulator
from harness.adapters.mqtt_iot.adapter import MqttIotAdapter
from harness.adapters.mqtt_iot.config import DEVICES, SCENES
from harness.events import EventBus

OUTPUT_DIR = Path(__file__).parent / "mqtt_results"
OUTPUT_DIR.mkdir(exist_ok=True)

BROKER_PORT = 18830  # Use non-standard port to avoid conflicts


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


async def setup_infrastructure():
    """Start broker and virtual devices."""
    print("  Starting mini MQTT broker...")
    broker = MiniMQTTBroker(port=BROKER_PORT)
    await broker.start()
    await asyncio.sleep(0.2)

    print("  Starting virtual device simulator...")
    simulator = VirtualDeviceSimulator(broker_host="localhost", broker_port=BROKER_PORT)
    simulator.start()
    await asyncio.sleep(0.3)

    return broker, simulator


async def test_broker_connectivity(results: TestResults):
    """Test basic MQTT broker connectivity."""
    print(f"\n{'='*60}")
    print("TEST: Broker Connectivity")
    print(f"{'='*60}")

    import paho.mqtt.client as mqtt

    connected_event = asyncio.Event()
    loop = asyncio.get_event_loop()

    def on_connect(client, userdata, flags, rc):
        loop.call_soon_threadsafe(connected_event.set)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
        client_id="test-connectivity",
        protocol=mqtt.MQTTv311,
    )
    client.on_connect = on_connect

    with results.time_it("broker_connect"):
        client.connect("localhost", BROKER_PORT, keepalive=10)
        client.loop_start()
        try:
            await asyncio.wait_for(connected_event.wait(), timeout=3.0)
            results.record("broker connection", True)
        except asyncio.TimeoutError:
            results.record("broker connection", False, "timeout connecting to broker")

    client.loop_stop()
    client.disconnect()
    print(f"  ⏱️ Connect time: {results.perf.get('broker_connect', 0)*1000:.0f}ms")


async def test_pubsub_roundtrip(results: TestResults):
    """Test pub/sub message delivery through broker."""
    print(f"\n{'='*60}")
    print("TEST: Pub/Sub Roundtrip")
    print(f"{'='*60}")

    import paho.mqtt.client as mqtt

    received_messages = []
    loop = asyncio.get_event_loop()
    msg_event = asyncio.Event()

    def on_message(client, userdata, msg):
        received_messages.append(msg)
        loop.call_soon_threadsafe(msg_event.set)

    sub_client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
        client_id="test-sub",
        protocol=mqtt.MQTTv311,
    )
    sub_client.on_message = on_message
    sub_client.connect("localhost", BROKER_PORT)
    sub_client.subscribe("test/roundtrip", qos=1)
    sub_client.loop_start()
    await asyncio.sleep(0.2)

    pub_client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
        client_id="test-pub",
        protocol=mqtt.MQTTv311,
    )
    pub_client.connect("localhost", BROKER_PORT)
    pub_client.loop_start()
    await asyncio.sleep(0.1)

    with results.time_it("pubsub_roundtrip"):
        pub_client.publish("test/roundtrip", json.dumps({"test": True}), qos=1)
        try:
            await asyncio.wait_for(msg_event.wait(), timeout=3.0)
            results.record("message delivered", True, f"received {len(received_messages)} msg")
            payload = json.loads(received_messages[0].payload)
            results.record("payload intact", payload == {"test": True})
        except asyncio.TimeoutError:
            results.record("message delivered", False, "timeout waiting for message")

    pub_client.loop_stop()
    pub_client.disconnect()
    sub_client.loop_stop()
    sub_client.disconnect()
    print(f"  ⏱️ Roundtrip: {results.perf.get('pubsub_roundtrip', 0)*1000:.0f}ms")


async def test_adapter_initialization(results: TestResults):
    """Test MqttIotAdapter initialization with real broker."""
    print(f"\n{'='*60}")
    print("TEST: Adapter Initialization (minimal scene)")
    print(f"{'='*60}")

    event_bus = EventBus()
    adapter = MqttIotAdapter(
        event_bus=event_bus,
        broker_host="localhost",
        broker_port=BROKER_PORT,
        timeout_ms=3000,
    )

    with results.time_it("adapter_init"):
        meta = await adapter.initialize("minimal")

    results.record("initialize succeeds", meta is not None)
    results.record("engine is mqtt_real", meta.get("engine") == "mqtt_real",
                   f"got: {meta.get('engine')}")
    results.record("2 devices in minimal", meta.get("device_count") == 2,
                   f"got: {meta.get('device_count')}")
    results.record("correct device types",
                   set(meta.get("device_types", [])) == {"smart_light", "multi_sensor"},
                   f"got: {meta.get('device_types')}")
    results.record("broker info correct",
                   meta.get("broker") == f"localhost:{BROKER_PORT}")

    print(f"  ⏱️ Init time: {results.perf['adapter_init']*1000:.0f}ms")
    return adapter, event_bus


async def test_device_listing(results: TestResults, adapter: MqttIotAdapter):
    """Test listing devices through adapter."""
    print(f"\n{'='*60}")
    print("TEST: Device Listing")
    print(f"{'='*60}")

    with results.time_it("list_devices"):
        devices = await adapter.list_devices()

    results.record("2 devices returned", len(devices) == 2, f"got {len(devices)}")

    device_ids = [d.device_id for d in devices]
    results.record("has bedroom_light", "bedroom_light" in device_ids)
    results.record("has kitchen_sensor", "kitchen_sensor" in device_ids)

    light = next(d for d in devices if d.device_id == "bedroom_light")
    cap_names = [c.name for c in light.capabilities]
    results.record("light has power cap", "power" in cap_names)
    results.record("light has brightness cap", "brightness" in cap_names)
    results.record("light has color_temp cap", "color_temp" in cap_names)

    sensor = next(d for d in devices if d.device_id == "kitchen_sensor")
    sensor_caps = [c.name for c in sensor.capabilities]
    results.record("sensor has temperature", "temperature" in sensor_caps)
    results.record("sensor has humidity", "humidity" in sensor_caps)


async def test_get_device_state(results: TestResults, adapter: MqttIotAdapter):
    """Test getting device state via MQTT pub/sub."""
    print(f"\n{'='*60}")
    print("TEST: Get Device State (MQTT roundtrip)")
    print(f"{'='*60}")

    with results.time_it("get_state_light"):
        state = await adapter.get_device_state("bedroom_light")

    results.record("state returned", state is not None)
    props = state.properties
    results.record("has power", "power" in props, f"power={props.get('power')}")
    results.record("has brightness", "brightness" in props, f"brightness={props.get('brightness')}")
    results.record("has color_temp", "color_temp" in props, f"color_temp={props.get('color_temp')}")
    results.record("has online", "online" in props, f"online={props.get('online')}")

    # Initial values from config
    results.record("power initially off", props.get("power") is False)
    results.record("brightness is 80", props.get("brightness") == 80.0)
    results.record("color_temp is 4000", props.get("color_temp") == 4000.0)

    print(f"  ⏱️ Get state: {results.perf['get_state_light']*1000:.0f}ms")

    # Kitchen sensor
    with results.time_it("get_state_sensor"):
        state = await adapter.get_device_state("kitchen_sensor")

    props = state.properties
    results.record("sensor has temperature", "temperature" in props,
                   f"temp={props.get('temperature')}")
    results.record("sensor temp is 23.5", props.get("temperature") == 23.5)
    results.record("sensor has humidity", "humidity" in props,
                   f"humidity={props.get('humidity')}")
    print(f"  ⏱️ Get sensor state: {results.perf['get_state_sensor']*1000:.0f}ms")


async def test_set_property(results: TestResults, adapter: MqttIotAdapter):
    """Test setting device properties via MQTT."""
    print(f"\n{'='*60}")
    print("TEST: Set Property (MQTT command → response)")
    print(f"{'='*60}")

    # Turn on the light
    with results.time_it("set_power_on"):
        state = await adapter.set_property("bedroom_light", "power", True)

    results.record("set power succeeds", state is not None)
    results.record("power is now True", state.properties.get("power") is True)

    # Change brightness
    with results.time_it("set_brightness"):
        state = await adapter.set_property("bedroom_light", "brightness", 50.0)

    results.record("set brightness succeeds", state is not None)
    results.record("brightness is now 50", state.properties.get("brightness") == 50.0)

    # Change color temperature
    with results.time_it("set_color_temp"):
        state = await adapter.set_property("bedroom_light", "color_temp", 3000.0)

    results.record("set color_temp succeeds", state is not None)
    results.record("color_temp is now 3000", state.properties.get("color_temp") == 3000.0)

    print(f"  ⏱️ Set power: {results.perf['set_power_on']*1000:.0f}ms")
    print(f"  ⏱️ Set brightness: {results.perf['set_brightness']*1000:.0f}ms")
    print(f"  ⏱️ Set color_temp: {results.perf['set_color_temp']*1000:.0f}ms")

    # Verify state persists
    with results.time_it("verify_state"):
        state = await adapter.get_device_state("bedroom_light")
    results.record("state persists", state.properties.get("brightness") == 50.0)


async def test_invalid_operations(results: TestResults, adapter: MqttIotAdapter):
    """Test error handling for invalid operations."""
    print(f"\n{'='*60}")
    print("TEST: Error Handling")
    print(f"{'='*60}")

    # Invalid device
    try:
        await adapter.get_device_state("nonexistent_device")
        results.record("rejects invalid device", False, "no error raised")
    except ValueError as e:
        results.record("rejects invalid device", True, str(e)[:50])

    # Invalid property
    try:
        await adapter.set_property("bedroom_light", "nonexistent_prop", 42)
        results.record("rejects invalid property", False, "no error raised")
    except ValueError as e:
        results.record("rejects invalid property", True, str(e)[:50])


async def test_event_tracking(results: TestResults, adapter: MqttIotAdapter, event_bus: EventBus):
    """Test event emission during MQTT operations."""
    print(f"\n{'='*60}")
    print("TEST: Event Bus (MQTT events)")
    print(f"{'='*60}")

    events_before = len(event_bus.get_history(limit=1000))

    await adapter.set_property("bedroom_light", "power", False)

    events_after = len(event_bus.get_history(limit=1000))
    new_events = events_after - events_before
    results.record("event emitted on set", new_events >= 1, f"{new_events} new events")

    history = event_bus.get_history(limit=3)
    has_state_changed = any(e.get("type") == "state_changed" for e in history)
    results.record("has state_changed event", has_state_changed)


async def test_full_scene(results: TestResults):
    """Test with full smart_home scene (5 devices)."""
    print(f"\n{'='*60}")
    print("TEST: Full Smart Home Scene (5 devices)")
    print(f"{'='*60}")

    event_bus = EventBus()
    adapter = MqttIotAdapter(
        event_bus=event_bus,
        broker_host="localhost",
        broker_port=BROKER_PORT,
        timeout_ms=3000,
    )

    with results.time_it("init_full_scene"):
        meta = await adapter.initialize("smart_home")

    results.record("5 devices in smart_home", meta["device_count"] == 5)

    devices = await adapter.list_devices()
    device_types = [d.device_type for d in devices]
    results.record("has smart_light", "smart_light" in device_types)
    results.record("has air_conditioner", "air_conditioner" in device_types)
    results.record("has smart_lock", "smart_lock" in device_types)
    results.record("has multi_sensor", "multi_sensor" in device_types)
    results.record("has robot_vacuum", "robot_vacuum" in device_types)

    # Quick state check on AC
    with results.time_it("get_ac_state"):
        ac_state = await adapter.get_device_state("living_room_ac")
    results.record("AC target_temp readable",
                   ac_state.properties.get("target_temp") == 24.0)

    # Set AC temperature
    with results.time_it("set_ac_temp"):
        state = await adapter.set_property("living_room_ac", "target_temp", 22.0)
    results.record("AC temp set to 22", state.properties.get("target_temp") == 22.0)

    await adapter.shutdown()
    results.record("full scene shutdown", True)
    print(f"  ⏱️ Full scene init: {results.perf['init_full_scene']*1000:.0f}ms")


async def test_shutdown(results: TestResults, adapter: MqttIotAdapter):
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
    print("MQTT IoT REAL INTEGRATION TESTS")
    print("=" * 60)
    print(f"Python: {sys.version.split()[0]}")
    print(f"Broker port: {BROKER_PORT}")

    try:
        import paho.mqtt
        print(f"paho-mqtt: {paho.mqtt.__version__}")
    except Exception as e:
        print(f"paho-mqtt import failed: {e}")
        return False

    broker = None
    simulator = None

    try:
        print(f"\n{'='*60}")
        print("SETUP: Infrastructure")
        print(f"{'='*60}")
        broker, simulator = await setup_infrastructure()
        print("  ✅ Broker + virtual devices running")

        await test_broker_connectivity(results)
        await test_pubsub_roundtrip(results)
        adapter, event_bus = await test_adapter_initialization(results)
        await test_device_listing(results, adapter)
        await test_get_device_state(results, adapter)
        await test_set_property(results, adapter)
        await test_invalid_operations(results, adapter)
        await test_event_tracking(results, adapter, event_bus)
        await test_shutdown(results, adapter)
        await test_full_scene(results)
    except Exception as e:
        print(f"\n💥 FATAL ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        results.record("test execution", False, str(e))
    finally:
        if simulator:
            simulator.stop()
        if broker:
            await broker.stop()

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
        "test_run": "mqtt_real_integration",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "paho_mqtt_version": paho.mqtt.__version__,
            "broker": f"mini_mqtt_broker (port {BROKER_PORT})",
            "virtual_devices": True,
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
    import paho.mqtt
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
