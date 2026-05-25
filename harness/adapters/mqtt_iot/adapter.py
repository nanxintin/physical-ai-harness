"""Real MQTT IoT adapter using paho-mqtt client.

Connects to a real MQTT broker and communicates with actual IoT devices.
Publishes commands to device topics and subscribes to state responses.
Handles connection errors and timeouts gracefully.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import time
from typing import Any

from harness.adapter import Adapter
from harness.adapters.mqtt_iot.config import COMM_CONFIG, DEVICES, SCENES
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore


class MqttIotAdapter(Adapter):
    """Real MQTT adapter connecting to an MQTT broker for IoT device control.

    Requires paho-mqtt: pip install paho-mqtt

    Default broker: localhost:1883 (configurable via constructor params).
    Protocol: publishes to {topic_prefix}/set, subscribes to {topic_prefix}/state.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        timeout_ms: int | None = None,
    ):
        if mqtt is None:
            raise ImportError(
                "paho-mqtt is required for MqttIotAdapter. "
                "Install with: pip install paho-mqtt"
            )

        self._event_bus = event_bus or EventBus()
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._username = username
        self._password = password
        self._timeout_s = (timeout_ms or COMM_CONFIG["timeout_ms"]) / 1000.0

        self._client: mqtt.Client | None = None
        self._connected = False
        self._scene = ""
        self._active_devices: list[str] = []

        # Response tracking: topic -> asyncio.Future
        self._pending_responses: dict[str, asyncio.Future] = {}
        self._device_states: dict[str, dict[str, Any]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_initialized(self) -> bool:
        return self._connected and bool(self._active_devices)

    # ------------------------------------------------------------------
    # Adapter Interface
    # ------------------------------------------------------------------

    async def initialize(self, scene: str = "smart_home") -> dict[str, Any]:
        """Connect to broker and subscribe to device state topics."""
        if scene not in SCENES:
            raise ValueError(f"Unknown scene: {scene}. Available: {list(SCENES.keys())}")

        self._scene = scene
        scene_config = SCENES[scene]
        self._active_devices = scene_config["devices"]
        self._loop = asyncio.get_event_loop()

        # Setup MQTT client
        self._client = mqtt.Client(
            client_id=f"harness-mqtt-adapter-{int(time.time())}",
            protocol=mqtt.MQTTv311,
        )

        if self._username:
            self._client.username_pw_set(self._username, self._password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        # Connect (blocking, then hand off to loop)
        try:
            await asyncio.to_thread(
                self._client.connect, self._broker_host, self._broker_port, keepalive=60
            )
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to MQTT broker at "
                f"{self._broker_host}:{self._broker_port}: {e}"
            ) from e

        # Start network loop in background thread
        self._client.loop_start()
        self._connected = True

        # Subscribe to all device state topics
        for device_id in self._active_devices:
            topic_prefix = DEVICES[device_id]["topic_prefix"]
            self._client.subscribe(f"{topic_prefix}/state", qos=1)

        # Initialize device states as empty (will be populated from broker)
        for device_id in self._active_devices:
            self._device_states[device_id] = {}

        return {
            "scene": scene,
            "description": scene_config["description"],
            "device_count": len(self._active_devices),
            "device_types": [DEVICES[d]["type"] for d in self._active_devices],
            "engine": "mqtt_real",
            "broker": f"{self._broker_host}:{self._broker_port}",
        }

    async def list_devices(self) -> list[CDD]:
        """Return CDDs for all active devices."""
        return [self._build_cdd(device_id) for device_id in self._active_devices]

    async def get_device_state(self, device_id: str) -> DeviceState:
        """Request device state via MQTT and wait for response."""
        self._validate_device(device_id)
        self._ensure_connected()

        topic_prefix = DEVICES[device_id]["topic_prefix"]
        request_topic = f"{topic_prefix}/get"
        response_topic = f"{topic_prefix}/state"

        # Create a future to wait for the response
        future: asyncio.Future = self._loop.create_future()
        self._pending_responses[response_topic] = future

        # Publish get request
        self._client.publish(request_topic, json.dumps({"action": "get_state"}), qos=1)

        try:
            response = await asyncio.wait_for(future, timeout=self._timeout_s)
        except asyncio.TimeoutError:
            self._pending_responses.pop(response_topic, None)
            raise ValueError(
                f"Communication timeout: No response from {device_id} within "
                f"{self._timeout_s}s. Device may be offline."
            )
        finally:
            self._pending_responses.pop(response_topic, None)

        self._device_states[device_id] = response
        return DeviceState(
            device_id=device_id,
            properties=response,
            timestamp=time.time(),
        )

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        """Publish property change command and wait for state confirmation."""
        self._validate_device(device_id)
        self._ensure_connected()

        # Validate property exists
        dev_config = DEVICES[device_id]
        cap_names = [c[0] for c in dev_config["capabilities"]]
        if property_name not in cap_names:
            raise ValueError(
                f"Unknown or read-only property: '{property_name}' on {device_id}. "
                f"Writable properties: {cap_names}"
            )

        topic_prefix = dev_config["topic_prefix"]
        set_topic = f"{topic_prefix}/set"
        response_topic = f"{topic_prefix}/state"

        # Create future for response
        future: asyncio.Future = self._loop.create_future()
        self._pending_responses[response_topic] = future

        # Publish set command
        payload = json.dumps({"property": property_name, "value": value})
        self._client.publish(set_topic, payload, qos=1)

        try:
            response = await asyncio.wait_for(future, timeout=self._timeout_s)
        except asyncio.TimeoutError:
            self._pending_responses.pop(response_topic, None)
            raise ValueError(
                f"Communication timeout: Set command for {device_id}.{property_name} "
                f"not acknowledged within {self._timeout_s}s."
            )
        finally:
            self._pending_responses.pop(response_topic, None)

        self._device_states[device_id] = response

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": value,
        })

        return DeviceState(
            device_id=device_id,
            properties=response,
            timestamp=time.time(),
        )

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        """Publish action command and wait for acknowledgment."""
        self._validate_device(device_id)
        self._ensure_connected()
        params = params or {}

        dev_config = DEVICES[device_id]
        actions = dev_config.get("actions", {})
        if action not in actions and action != "trigger_ota":
            available = list(actions.keys()) + ["trigger_ota"]
            raise ValueError(
                f"Unknown action: '{action}' on {device_id}. Available: {available}"
            )

        topic_prefix = dev_config["topic_prefix"]
        action_topic = f"{topic_prefix}/action"
        response_topic = f"{topic_prefix}/action/response"

        # Subscribe to action response topic
        self._client.subscribe(response_topic, qos=1)

        # Create future
        future: asyncio.Future = self._loop.create_future()
        self._pending_responses[response_topic] = future

        # Publish action
        payload = json.dumps({"action": action, "params": params})
        self._client.publish(action_topic, payload, qos=1)

        try:
            response = await asyncio.wait_for(future, timeout=self._timeout_s)
        except asyncio.TimeoutError:
            self._pending_responses.pop(response_topic, None)
            raise ValueError(
                f"Communication timeout: Action '{action}' on {device_id} "
                f"not acknowledged within {self._timeout_s}s."
            )
        finally:
            self._pending_responses.pop(response_topic, None)

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })

        return {"success": True, "action": action, "params": params, "response": response}

    async def capture_image(self) -> str:
        """Capture is not supported on real MQTT adapter (no visual feed).

        Returns a placeholder status image.
        """
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return ""

        img = Image.new("RGB", (640, 480), color=(240, 240, 245))
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), "MQTT IoT Adapter (Real Broker)", fill=(30, 30, 30))
        draw.text((20, 50), f"Broker: {self._broker_host}:{self._broker_port}", fill=(60, 60, 80))
        draw.text((20, 80), f"Connected: {self._connected}", fill=(60, 60, 80))
        draw.text((20, 110), f"Devices: {len(self._active_devices)}", fill=(60, 60, 80))

        y = 150
        for device_id in self._active_devices:
            state = self._device_states.get(device_id, {})
            online = state.get("online", "unknown")
            draw.text((20, y), f"  {device_id}: online={online}", fill=(80, 80, 100))
            y += 20

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    async def shutdown(self) -> None:
        """Disconnect from MQTT broker."""
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False

    # ------------------------------------------------------------------
    # Private: MQTT Callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):
        """Called when connected to MQTT broker."""
        if rc == 0:
            self._connected = True
        else:
            self._connected = False

    def _on_message(self, client, userdata, msg):
        """Called when a message is received on a subscribed topic."""
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {"raw": msg.payload.decode(errors="replace")}

        # Resolve any pending future for this topic
        if topic in self._pending_responses:
            future = self._pending_responses.pop(topic)
            if not future.done() and self._loop:
                self._loop.call_soon_threadsafe(future.set_result, payload)

    def _on_disconnect(self, client, userdata, rc):
        """Called when disconnected from MQTT broker."""
        self._connected = False

    # ------------------------------------------------------------------
    # Private: Helpers
    # ------------------------------------------------------------------

    def _validate_device(self, device_id: str) -> None:
        if device_id not in self._active_devices:
            raise ValueError(
                f"Device not found: {device_id}. Active devices: {self._active_devices}"
            )

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise ConnectionError(
                f"Not connected to MQTT broker at {self._broker_host}:{self._broker_port}. "
                f"Call initialize() first or check broker availability."
            )

    def _build_cdd(self, device_id: str) -> CDD:
        """Build CDD from device config."""
        dev_config = DEVICES[device_id]
        capabilities = []

        for cap_tuple in dev_config["capabilities"]:
            name, cap_type, writable, safety, value_range, description = cap_tuple
            vr = None
            if value_range is not None and isinstance(value_range, dict):
                vr = value_range
            capabilities.append(DeviceCapability(
                name=name,
                cap_type=cap_type,
                readable=True,
                writable=writable,
                safety_level=safety,
                value_range=vr,
                description=description,
            ))

        for sensor_tuple in dev_config["sensors"]:
            name, sensor_type, description = sensor_tuple
            capabilities.append(DeviceCapability(
                name=name,
                cap_type=sensor_type,
                readable=True,
                writable=False,
                safety_level=SafetyLevel.LOW,
                description=description,
            ))

        for action_name, action_info in dev_config.get("actions", {}).items():
            capabilities.append(DeviceCapability(
                name=action_name,
                cap_type="action",
                readable=False,
                writable=True,
                safety_level=action_info["safety"],
                description=action_info["description"],
            ))

        # Determine safety class
        safety_levels = [c.safety_level for c in capabilities if c.writable]
        if safety_levels:
            order = [SafetyLevel.LOW, SafetyLevel.MEDIUM, SafetyLevel.HIGH, SafetyLevel.CRITICAL]
            max_safety = max(safety_levels, key=lambda s: order.index(s))
        else:
            max_safety = SafetyLevel.LOW

        return CDD(
            device_id=device_id,
            device_type=dev_config["type"],
            display_name=dev_config["display_name"],
            location=dev_config["location"],
            capabilities=capabilities,
            safety_class=max_safety,
            metadata={
                "engine": "mqtt_real",
                "protocol": "mqtt",
                "topic_prefix": dev_config["topic_prefix"],
                "broker": f"{self._broker_host}:{self._broker_port}",
            },
        )
