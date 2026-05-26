#!/usr/bin/env python3
"""Virtual MQTT devices that simulate real IoT device responses.

Runs alongside a MQTT broker. Subscribes to device command topics and
responds with state updates, simulating real smart home devices.

Usage:
    python tests/mqtt_virtual_devices.py [--broker localhost] [--port 1883]
"""

from __future__ import annotations

import json
import sys
import time
import threading
from copy import deepcopy

import paho.mqtt.client as mqtt

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from harness.adapters.mqtt_iot.config import DEVICES


class VirtualDeviceSimulator:
    """Simulates all configured MQTT IoT devices."""

    def __init__(self, broker_host: str = "localhost", broker_port: int = 1883):
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._states: dict[str, dict] = {}
        self._client: mqtt.Client | None = None
        self._running = False

        for device_id, config in DEVICES.items():
            self._states[device_id] = deepcopy(config["initial_state"])

    def start(self):
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            client_id=f"virtual-devices-{int(time.time())}",
            protocol=mqtt.MQTTv311,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.connect(self._broker_host, self._broker_port, keepalive=60)
        self._running = True
        self._client.loop_start()

    def stop(self):
        self._running = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            return
        for device_id, config in DEVICES.items():
            prefix = config["topic_prefix"]
            client.subscribe(f"{prefix}/get", qos=1)
            client.subscribe(f"{prefix}/set", qos=1)
            client.subscribe(f"{prefix}/action", qos=1)

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        device_id = self._find_device_by_topic(topic)
        if not device_id:
            return

        config = DEVICES[device_id]
        prefix = config["topic_prefix"]

        if topic == f"{prefix}/get":
            self._handle_get(client, device_id, prefix)
        elif topic == f"{prefix}/set":
            self._handle_set(client, device_id, prefix, payload)
        elif topic == f"{prefix}/action":
            self._handle_action(client, device_id, prefix, payload)

    def _handle_get(self, client, device_id: str, prefix: str):
        state = self._states[device_id]
        client.publish(f"{prefix}/state", json.dumps(state), qos=1)

    def _handle_set(self, client, device_id: str, prefix: str, payload: dict):
        prop = payload.get("property")
        value = payload.get("value")
        if prop and prop in self._states[device_id]:
            self._states[device_id][prop] = value
        client.publish(f"{prefix}/state", json.dumps(self._states[device_id]), qos=1)

    def _handle_action(self, client, device_id: str, prefix: str, payload: dict):
        action = payload.get("action", "")
        response = {"success": True, "action": action, "device": device_id}
        client.publish(f"{prefix}/action/response", json.dumps(response), qos=1)

    def _find_device_by_topic(self, topic: str) -> str | None:
        for device_id, config in DEVICES.items():
            prefix = config["topic_prefix"]
            if topic.startswith(prefix):
                return device_id
        return None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()

    sim = VirtualDeviceSimulator(args.broker, args.port)
    print(f"Starting virtual devices (broker={args.broker}:{args.port})...")
    sim.start()
    print(f"  Simulating {len(DEVICES)} devices. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sim.stop()
        print("\nStopped.")
