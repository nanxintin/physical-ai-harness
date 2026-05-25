"""Mock MQTT IoT adapter simulating real-world IoT communication challenges.

This adapter provides a fully functional smart home simulation with:
- Device online/offline status (random disconnections)
- Simulated network latency (50-200ms noted in metadata)
- OTA firmware update states (devices uncontrollable during update)
- Message loss simulation (2% chance of no response)
- Battery drain for battery-powered devices
- Random event generation (sensor changes, smoke/motion triggers)

Only requires PIL as external dependency.
"""

from __future__ import annotations

import base64
import io
import random
import time
from datetime import datetime, timezone
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from harness.adapter import Adapter
from harness.adapters.mqtt_iot.config import COMM_CONFIG, DEVICES, SCENES
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class MockMqttIotAdapter(Adapter):
    """Mock adapter simulating a smart home with realistic IoT communication patterns.

    Simulates MQTT-style pub/sub with unreliable network, device timeouts,
    OTA states, battery drain, and random sensor events. Designed to train
    LLMs on handling real-world IoT error conditions.
    """

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._scene = ""
        self._active_devices: list[str] = []

        # Device simulation state
        self._device_states: dict[str, dict[str, Any]] = {}
        self._device_online: dict[str, bool] = {}
        self._device_battery: dict[str, float] = {}
        self._ota_devices: set[str] = set()
        self._ota_start_times: dict[str, float] = {}

        # Communication simulation
        self._offline_probability: float = COMM_CONFIG["offline_probability"]
        self._message_loss_probability: float = COMM_CONFIG["message_loss_probability"]
        self._latency_range: tuple[int, int] = COMM_CONFIG["default_latency_ms"]

        # Message history (MQTT-style pub/sub log)
        self._message_history: list[dict[str, Any]] = []
        self._event_log: list[dict[str, Any]] = []

        # Timing
        self._init_time: float = 0.0
        self._last_sensor_update: float = 0.0

    @property
    def is_initialized(self) -> bool:
        return bool(self._active_devices)

    # ------------------------------------------------------------------
    # Adapter Interface
    # ------------------------------------------------------------------

    async def initialize(self, scene: str = "smart_home") -> dict[str, Any]:
        """Initialize the smart home scene."""
        if scene not in SCENES:
            raise ValueError(f"Unknown scene: {scene}. Available: {list(SCENES.keys())}")

        self._scene = scene
        scene_config = SCENES[scene]
        self._active_devices = scene_config["devices"]

        # Apply scene overrides
        if scene_config["offline_probability_override"] is not None:
            self._offline_probability = scene_config["offline_probability_override"]
        else:
            self._offline_probability = COMM_CONFIG["offline_probability"]

        if scene_config["message_loss_override"] is not None:
            self._message_loss_probability = scene_config["message_loss_override"]
        else:
            self._message_loss_probability = COMM_CONFIG["message_loss_probability"]

        # Initialize device states from config
        self._device_states = {}
        self._device_online = {}
        self._device_battery = {}
        self._ota_devices = set()
        self._ota_start_times = {}
        self._message_history = []
        self._event_log = []

        for device_id in self._active_devices:
            dev_config = DEVICES[device_id]
            self._device_states[device_id] = dict(dev_config["initial_state"])
            self._device_online[device_id] = True
            if dev_config["battery_powered"]:
                self._device_battery[device_id] = dev_config["initial_state"].get("battery", 100.0)

        self._init_time = time.time()
        self._last_sensor_update = time.time()

        self._log_message("system", "harness/status", "publish", {
            "event": "initialized",
            "scene": scene,
            "devices": self._active_devices,
        })

        return {
            "scene": scene,
            "description": scene_config["description"],
            "device_count": len(self._active_devices),
            "device_types": [DEVICES[d]["type"] for d in self._active_devices],
            "engine": "mqtt_iot_mock",
            "comm_config": {
                "latency_ms": self._latency_range,
                "offline_probability": self._offline_probability,
                "message_loss_probability": self._message_loss_probability,
            },
        }

    async def list_devices(self) -> list[CDD]:
        """Return CDDs for all active devices."""
        cdds = []
        for device_id in self._active_devices:
            cdds.append(self._build_cdd(device_id))
        return cdds

    async def get_device_state(self, device_id: str) -> DeviceState:
        """Read current state of a device, simulating network conditions."""
        self._validate_device(device_id)
        self._maybe_update_sensors()
        self._maybe_toggle_connectivity()
        self._check_ota_completion()

        # Simulate message loss
        if self._simulate_message_loss():
            self._log_message(device_id, f"{DEVICES[device_id]['topic_prefix']}/state", "subscribe", {
                "error": "message_lost",
                "detail": "No response received (message dropped in transit)",
            })
            raise ValueError(
                f"Communication timeout: No response from {device_id} "
                f"(MQTT message lost in transit)"
            )

        # Check online status
        if not self._device_online.get(device_id, False):
            self._log_message(device_id, f"{DEVICES[device_id]['topic_prefix']}/state", "subscribe", {
                "error": "device_offline",
            })
            raise ValueError(
                f"Device offline: {device_id} is not responding. "
                f"Last seen: {self._format_last_seen(device_id)}"
            )

        latency = self._simulate_latency()
        state = dict(self._device_states[device_id])
        state["_metadata"] = {
            "latency_ms": latency,
            "online": True,
            "ota_updating": device_id in self._ota_devices,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._log_message(device_id, f"{DEVICES[device_id]['topic_prefix']}/state", "subscribe", state)

        return DeviceState(
            device_id=device_id,
            properties=state,
            timestamp=time.time(),
        )

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        """Set a device property, simulating IoT communication challenges."""
        self._validate_device(device_id)
        self._maybe_toggle_connectivity()
        self._check_ota_completion()

        # Simulate message loss
        if self._simulate_message_loss():
            self._log_message(device_id, f"{DEVICES[device_id]['topic_prefix']}/set", "publish", {
                "property": property_name,
                "value": value,
                "error": "message_lost",
            })
            raise ValueError(
                f"Communication timeout: Command to {device_id} not acknowledged "
                f"(MQTT publish lost). Retry recommended."
            )

        # Check online status
        if not self._device_online.get(device_id, False):
            self._log_message(device_id, f"{DEVICES[device_id]['topic_prefix']}/set", "publish", {
                "property": property_name,
                "value": value,
                "error": "device_offline",
            })
            raise ValueError(
                f"Device offline: {device_id} cannot receive commands. "
                f"The device may have lost Wi-Fi connectivity or power."
            )

        # Check OTA state
        if device_id in self._ota_devices:
            elapsed = time.time() - self._ota_start_times.get(device_id, 0)
            remaining = max(0, COMM_CONFIG["ota_update_duration_s"] - elapsed)
            self._log_message(device_id, f"{DEVICES[device_id]['topic_prefix']}/set", "publish", {
                "property": property_name,
                "value": value,
                "error": "ota_in_progress",
                "remaining_s": remaining,
            })
            raise ValueError(
                f"Device in OTA update: {device_id} is currently updating firmware. "
                f"Estimated time remaining: {remaining:.0f}s. "
                f"Device will be controllable after update completes."
            )

        # Validate property exists and is writable
        dev_config = DEVICES[device_id]
        cap_names = [c[0] for c in dev_config["capabilities"]]
        if property_name not in cap_names:
            raise ValueError(
                f"Unknown or read-only property: '{property_name}' on {device_id}. "
                f"Writable properties: {cap_names}"
            )

        # Validate value range
        cap_info = next(c for c in dev_config["capabilities"] if c[0] == property_name)
        cap_type = cap_info[1]
        value_range = cap_info[4]

        validated_value = self._validate_value(property_name, value, cap_type, value_range)

        # Apply the change
        latency = self._simulate_latency()
        self._device_states[device_id][property_name] = validated_value

        # Side effects
        self._apply_side_effects(device_id, property_name, validated_value)

        self._log_message(device_id, f"{dev_config['topic_prefix']}/set", "publish", {
            "property": property_name,
            "value": validated_value,
            "latency_ms": latency,
            "success": True,
        })

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": validated_value,
            "latency_ms": latency,
        })

        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        """Invoke a discrete action on a device."""
        self._validate_device(device_id)
        self._maybe_toggle_connectivity()
        self._check_ota_completion()
        params = params or {}

        # Simulate message loss
        if self._simulate_message_loss():
            self._log_message(device_id, f"{DEVICES[device_id]['topic_prefix']}/action", "publish", {
                "action": action,
                "params": params,
                "error": "message_lost",
            })
            raise ValueError(
                f"Communication timeout: Action '{action}' on {device_id} not acknowledged. "
                f"The command may or may not have been received."
            )

        # Check online
        if not self._device_online.get(device_id, False):
            raise ValueError(f"Device offline: {device_id} cannot execute action '{action}'.")

        # Check OTA
        if device_id in self._ota_devices:
            elapsed = time.time() - self._ota_start_times.get(device_id, 0)
            remaining = max(0, COMM_CONFIG["ota_update_duration_s"] - elapsed)
            raise ValueError(
                f"Device in OTA update: {device_id} cannot execute '{action}'. "
                f"Remaining: {remaining:.0f}s."
            )

        # Check action exists
        dev_config = DEVICES[device_id]
        actions = dev_config.get("actions", {})

        # Special built-in action: trigger_ota
        if action == "trigger_ota":
            ota_result = self._start_ota(device_id)
            latency = self._simulate_latency()
            self._log_message(device_id, f"{dev_config['topic_prefix']}/action", "publish", {
                "action": action,
                "result": ota_result,
                "latency_ms": latency,
            })
            await self._event_bus.emit("action_executed", {
                "device_id": device_id,
                "action": action,
                "params": params,
            })
            return {
                "success": True,
                "action": action,
                "params": params,
                "result": ota_result,
                "latency_ms": latency,
                "mock": True,
            }

        if action not in actions:
            available = list(actions.keys()) + ["trigger_ota"]
            raise ValueError(
                f"Unknown action: '{action}' on {device_id}. Available: {available}"
            )

        # Device-specific action logic
        result = self._execute_action(device_id, action, params)

        latency = self._simulate_latency()
        self._log_message(device_id, f"{dev_config['topic_prefix']}/action", "publish", {
            "action": action,
            "params": params,
            "result": result,
            "latency_ms": latency,
        })

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
            "result": result,
        })

        return {
            "success": True,
            "action": action,
            "params": params,
            "result": result,
            "latency_ms": latency,
            "mock": True,
        }

    async def capture_image(self) -> str:
        """Render a home floor plan showing device statuses."""
        img = Image.new("RGB", (800, 600), color=(245, 245, 250))
        draw = ImageDraw.Draw(img)

        # Title
        draw.text((20, 15), "MQTT IoT Smart Home - Device Status", fill=(30, 30, 30))
        draw.text((20, 35), f"Scene: {self._scene} | Time: {datetime.now().strftime('%H:%M:%S')}",
                  fill=(80, 80, 80))

        # Draw rooms
        rooms = {
            "bedroom": (50, 80, 280, 260),
            "living_room": (300, 80, 550, 260),
            "kitchen": (570, 80, 780, 260),
            "front_door": (300, 290, 550, 420),
        }

        room_labels = {
            "bedroom": "Bedroom",
            "living_room": "Living Room",
            "kitchen": "Kitchen",
            "front_door": "Front Door",
        }

        for room_id, (x1, y1, x2, y2) in rooms.items():
            draw.rectangle([x1, y1, x2, y2], outline=(100, 100, 120), width=2)
            draw.text((x1 + 5, y1 + 5), room_labels[room_id], fill=(60, 60, 80))

        # Draw devices in their rooms
        device_positions = {
            "bedroom_light": (120, 150),
            "living_room_ac": (400, 150),
            "front_door_lock": (400, 340),
            "kitchen_sensor": (650, 150),
            "robot_vacuum": (400, 200),
        }

        for device_id in self._active_devices:
            if device_id not in device_positions:
                continue
            x, y = device_positions[device_id]
            online = self._device_online.get(device_id, False)
            in_ota = device_id in self._ota_devices

            # Status color: green=online, red=offline, yellow=OTA
            if in_ota:
                color = (220, 180, 0)
                status_text = "OTA"
            elif online:
                color = (0, 180, 0)
                status_text = "OK"
            else:
                color = (220, 0, 0)
                status_text = "OFFLINE"

            # Device icon (circle)
            draw.ellipse([x - 12, y - 12, x + 12, y + 12], fill=color, outline=(40, 40, 40))
            draw.text((x - 8, y - 6), status_text[:3], fill=(255, 255, 255))

            # Device name
            short_name = DEVICES[device_id]["display_name"]
            draw.text((x - 30, y + 16), short_name, fill=(30, 30, 30))

            # Battery indicator for battery-powered devices
            if device_id in self._device_battery:
                batt = self._device_battery[device_id]
                batt_color = (0, 180, 0) if batt > 30 else (220, 100, 0) if batt > 10 else (220, 0, 0)
                draw.text((x - 20, y + 30), f"Batt: {batt:.0f}%", fill=batt_color)

        # Legend
        legend_y = 450
        draw.text((20, legend_y), "Legend:", fill=(30, 30, 30))
        draw.ellipse([20, legend_y + 20, 32, legend_y + 32], fill=(0, 180, 0))
        draw.text((38, legend_y + 22), "Online", fill=(30, 30, 30))
        draw.ellipse([120, legend_y + 20, 132, legend_y + 32], fill=(220, 0, 0))
        draw.text((138, legend_y + 22), "Offline", fill=(30, 30, 30))
        draw.ellipse([220, legend_y + 20, 232, legend_y + 32], fill=(220, 180, 0))
        draw.text((238, legend_y + 22), "OTA Update", fill=(30, 30, 30))

        # Communication stats
        stats_y = 500
        total_msgs = len(self._message_history)
        lost_msgs = sum(1 for m in self._message_history if m.get("payload", {}).get("error") == "message_lost")
        draw.text((20, stats_y), f"Messages: {total_msgs} total, {lost_msgs} lost", fill=(60, 60, 80))
        draw.text((20, stats_y + 18),
                  f"Offline prob: {self._offline_probability*100:.0f}% | "
                  f"Loss prob: {self._message_loss_probability*100:.0f}%",
                  fill=(60, 60, 80))

        # Recent events
        draw.text((400, stats_y), "Recent Events:", fill=(30, 30, 30))
        for i, event in enumerate(self._event_log[-3:]):
            draw.text((400, stats_y + 18 + i * 16),
                      f"  {event.get('summary', '')[:50]}", fill=(80, 80, 100))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    # ------------------------------------------------------------------
    # Public: Event Simulation (for training rollouts)
    # ------------------------------------------------------------------

    async def simulate_event(self, event_type: str | None = None) -> dict[str, Any]:
        """Inject a random or specified IoT event for training scenarios.

        Event types:
            - temperature_change: Kitchen sensor temperature drifts
            - motion_detected: PIR sensor triggers
            - smoke_alarm: Smoke detected (critical event)
            - battery_low: Battery drops below threshold
            - device_offline: Random device goes offline
            - device_reconnect: Offline device comes back
            - ota_available: Firmware update starts on a device
            - tamper_alert: Door lock tamper detected
        """
        if event_type is None:
            event_type = random.choice([
                "temperature_change",
                "motion_detected",
                "battery_low",
                "device_offline",
                "device_reconnect",
            ])

        event_data = self._generate_event(event_type)

        self._event_log.append({
            "type": event_type,
            "data": event_data,
            "timestamp": time.time(),
            "summary": event_data.get("summary", event_type),
        })

        await self._event_bus.emit(f"iot_{event_type}", event_data)
        return event_data

    def get_message_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return MQTT message history for analysis."""
        return self._message_history[-limit:]

    def get_communication_stats(self) -> dict[str, Any]:
        """Return communication statistics."""
        total = len(self._message_history)
        lost = sum(1 for m in self._message_history if m.get("payload", {}).get("error") == "message_lost")
        offline_errors = sum(
            1 for m in self._message_history if m.get("payload", {}).get("error") == "device_offline"
        )
        return {
            "total_messages": total,
            "messages_lost": lost,
            "offline_errors": offline_errors,
            "loss_rate": lost / total if total > 0 else 0.0,
            "devices_online": sum(1 for v in self._device_online.values() if v),
            "devices_offline": sum(1 for v in self._device_online.values() if not v),
            "devices_in_ota": len(self._ota_devices),
        }

    # ------------------------------------------------------------------
    # Private: Validation
    # ------------------------------------------------------------------

    def _validate_device(self, device_id: str) -> None:
        if device_id not in self._active_devices:
            raise ValueError(
                f"Device not found: {device_id}. "
                f"Active devices: {self._active_devices}"
            )

    def _validate_value(self, prop_name: str, value: Any, cap_type: str, value_range: Any) -> Any:
        """Validate and coerce a value for the given capability type."""
        if cap_type == "boolean":
            if isinstance(value, str):
                value = value.lower() in ("true", "1", "on", "yes")
            return bool(value)
        elif cap_type == "float":
            fval = float(value)
            if value_range:
                vmin = value_range.get("min")
                vmax = value_range.get("max")
                if vmin is not None and fval < vmin:
                    raise ValueError(f"Value {fval} below minimum {vmin} for {prop_name}")
                if vmax is not None and fval > vmax:
                    raise ValueError(f"Value {fval} above maximum {vmax} for {prop_name}")
            return fval
        elif cap_type == "enum":
            if value_range and "values" in value_range:
                allowed = value_range["values"]
                if value not in allowed:
                    raise ValueError(f"Invalid value '{value}' for {prop_name}. Allowed: {allowed}")
            return value
        return value

    # ------------------------------------------------------------------
    # Private: Communication Simulation
    # ------------------------------------------------------------------

    def _simulate_latency(self) -> int:
        """Return simulated network latency in milliseconds."""
        return random.randint(self._latency_range[0], self._latency_range[1])

    def _simulate_message_loss(self) -> bool:
        """Return True if this message should be 'lost'."""
        return random.random() < self._message_loss_probability

    def _maybe_toggle_connectivity(self) -> None:
        """Randomly toggle device connectivity based on configured probability."""
        for device_id in self._active_devices:
            if self._device_online.get(device_id, True):
                # Online device might go offline
                if random.random() < self._offline_probability * 0.1:
                    self._device_online[device_id] = False
                    self._device_states[device_id]["online"] = False
                    self._event_log.append({
                        "type": "device_offline",
                        "data": {"device_id": device_id},
                        "timestamp": time.time(),
                        "summary": f"{device_id} went offline",
                    })
            else:
                # Offline device might reconnect
                if random.random() < COMM_CONFIG["reconnect_probability"] * 0.1:
                    self._device_online[device_id] = True
                    self._device_states[device_id]["online"] = True
                    self._event_log.append({
                        "type": "device_reconnect",
                        "data": {"device_id": device_id},
                        "timestamp": time.time(),
                        "summary": f"{device_id} reconnected",
                    })

    def _check_ota_completion(self) -> None:
        """Check if any OTA updates have completed."""
        completed = []
        for device_id in list(self._ota_devices):
            start_time = self._ota_start_times.get(device_id, 0)
            if time.time() - start_time >= COMM_CONFIG["ota_update_duration_s"]:
                completed.append(device_id)

        for device_id in completed:
            self._ota_devices.discard(device_id)
            self._ota_start_times.pop(device_id, None)
            # Bump firmware version
            old_ver = self._device_states[device_id].get("firmware_version", "1.0.0")
            parts = old_ver.split(".")
            parts[-1] = str(int(parts[-1]) + 1)
            new_ver = ".".join(parts)
            self._device_states[device_id]["firmware_version"] = new_ver
            self._device_states[device_id]["status"] = "idle"
            self._event_log.append({
                "type": "ota_complete",
                "data": {"device_id": device_id, "new_version": new_ver},
                "timestamp": time.time(),
                "summary": f"{device_id} OTA complete -> {new_ver}",
            })

    def _maybe_update_sensors(self) -> None:
        """Periodically drift sensor readings to simulate a live environment."""
        now = time.time()
        if now - self._last_sensor_update < 2.0:  # Only update every 2s
            return
        self._last_sensor_update = now

        for device_id in self._active_devices:
            if not self._device_online.get(device_id, False):
                continue
            dev_config = DEVICES[device_id]

            # Temperature drift
            if "temperature" in self._device_states[device_id]:
                drift = random.uniform(-0.3, 0.3)
                self._device_states[device_id]["temperature"] += drift
                self._device_states[device_id]["temperature"] = round(
                    self._device_states[device_id]["temperature"], 1
                )

            # Humidity drift
            if "humidity" in self._device_states[device_id]:
                drift = random.uniform(-0.5, 0.5)
                val = self._device_states[device_id]["humidity"] + drift
                self._device_states[device_id]["humidity"] = round(max(20, min(95, val)), 1)

            # Current temp for AC (drifts toward target when AC is on)
            if device_id == "living_room_ac" and self._device_states[device_id].get("power"):
                current = self._device_states[device_id]["current_temp"]
                target = self._device_states[device_id]["target_temp"]
                diff = target - current
                step = min(0.2, abs(diff)) * (1 if diff > 0 else -1)
                self._device_states[device_id]["current_temp"] = round(current + step, 1)

            # Signal strength jitter
            if "signal_strength" in self._device_states[device_id]:
                jitter = random.uniform(-2, 2)
                val = self._device_states[device_id]["signal_strength"] + jitter
                self._device_states[device_id]["signal_strength"] = round(max(-90, min(-20, val)), 1)

            # Battery drain for battery-powered devices
            if dev_config["battery_powered"] and device_id in self._device_battery:
                drain = COMM_CONFIG["battery_drain_per_hour"] / 3600.0 * 2.0  # per 2s tick
                self._device_battery[device_id] = max(0.0, self._device_battery[device_id] - drain)
                self._device_states[device_id]["battery"] = round(self._device_battery[device_id], 1)

    # ------------------------------------------------------------------
    # Private: Side Effects
    # ------------------------------------------------------------------

    def _apply_side_effects(self, device_id: str, prop_name: str, value: Any) -> None:
        """Apply side effects when a property changes."""
        if device_id == "living_room_ac":
            if prop_name == "power":
                if value:
                    self._device_states[device_id]["power_consumption"] = 1200.0
                else:
                    self._device_states[device_id]["power_consumption"] = 0.0

        elif device_id == "front_door_lock":
            if prop_name == "locked" and not value:
                # Record unlock time
                self._device_states[device_id]["last_unlock_time"] = (
                    datetime.now(timezone.utc).isoformat()
                )

        elif device_id == "robot_vacuum":
            if prop_name == "power":
                if not value:
                    self._device_states[device_id]["status"] = "idle"

    # ------------------------------------------------------------------
    # Private: Action Execution
    # ------------------------------------------------------------------

    def _execute_action(self, device_id: str, action: str, params: dict) -> dict[str, Any]:
        """Execute device-specific action logic."""
        if device_id == "robot_vacuum":
            return self._execute_vacuum_action(action, params)
        return {"executed": action, "device": device_id}

    def _execute_vacuum_action(self, action: str, params: dict) -> dict[str, Any]:
        """Execute robot vacuum actions with realistic constraints."""
        device_id = "robot_vacuum"
        state = self._device_states[device_id]
        battery = self._device_battery.get(device_id, 0)

        if action == "start_clean":
            # Check battery level
            if battery < 20:
                raise ValueError(
                    f"Cannot start cleaning: Battery too low ({battery:.0f}%). "
                    f"Minimum 20% required. Send robot to dock to charge."
                )
            # Check current status
            if state["status"] == "cleaning":
                raise ValueError("Robot is already cleaning. Use 'pause' to stop.")
            if state["status"] == "error":
                raise ValueError(
                    f"Robot is in error state (code: {state['error_code']}). "
                    f"Please resolve the error first."
                )

            mode = params.get("mode", "standard")
            if mode not in ["standard", "turbo", "quiet"]:
                raise ValueError(f"Invalid cleaning mode: '{mode}'. Use: standard, turbo, quiet")

            state["status"] = "cleaning"
            state["area_cleaned"] = 0.0
            return {"status": "cleaning", "mode": mode, "battery": battery}

        elif action == "return_dock":
            if state["status"] == "charging":
                return {"status": "already_at_dock", "battery": battery}
            state["status"] = "charging"
            return {"status": "returning_to_dock", "battery": battery}

        elif action == "pause":
            if state["status"] != "cleaning":
                raise ValueError(f"Cannot pause: Robot is not cleaning (status: {state['status']})")
            state["status"] = "idle"
            return {"status": "paused", "area_cleaned": state["area_cleaned"]}

        return {"executed": action}

    def _start_ota(self, device_id: str) -> dict[str, Any]:
        """Start OTA firmware update on a device."""
        if device_id in self._ota_devices:
            elapsed = time.time() - self._ota_start_times.get(device_id, 0)
            remaining = max(0, COMM_CONFIG["ota_update_duration_s"] - elapsed)
            return {
                "success": False,
                "error": "OTA already in progress",
                "remaining_s": remaining,
            }

        self._ota_devices.add(device_id)
        self._ota_start_times[device_id] = time.time()

        if "status" in self._device_states[device_id]:
            self._device_states[device_id]["status"] = "ota_updating"

        self._event_log.append({
            "type": "ota_started",
            "data": {"device_id": device_id},
            "timestamp": time.time(),
            "summary": f"{device_id} OTA update started",
        })

        return {
            "success": True,
            "action": "trigger_ota",
            "device": device_id,
            "duration_s": COMM_CONFIG["ota_update_duration_s"],
            "message": f"Firmware update started. Device will be uncontrollable for "
                       f"~{COMM_CONFIG['ota_update_duration_s']}s.",
            "mock": True,
        }

    # ------------------------------------------------------------------
    # Private: Event Generation
    # ------------------------------------------------------------------

    def _generate_event(self, event_type: str) -> dict[str, Any]:
        """Generate event data for a given event type."""
        if event_type == "temperature_change":
            if "kitchen_sensor" in self._active_devices:
                delta = random.uniform(-2, 2)
                old = self._device_states["kitchen_sensor"]["temperature"]
                new = round(old + delta, 1)
                self._device_states["kitchen_sensor"]["temperature"] = new
                return {
                    "device_id": "kitchen_sensor",
                    "property": "temperature",
                    "old_value": old,
                    "new_value": new,
                    "summary": f"Kitchen temp changed: {old}C -> {new}C",
                }
            return {"summary": "No kitchen sensor in scene"}

        elif event_type == "motion_detected":
            if "kitchen_sensor" in self._active_devices:
                self._device_states["kitchen_sensor"]["motion_detected"] = True
                return {
                    "device_id": "kitchen_sensor",
                    "property": "motion_detected",
                    "value": True,
                    "summary": "Motion detected in kitchen",
                }
            return {"summary": "No kitchen sensor in scene"}

        elif event_type == "smoke_alarm":
            if "kitchen_sensor" in self._active_devices:
                self._device_states["kitchen_sensor"]["smoke_detected"] = True
                return {
                    "device_id": "kitchen_sensor",
                    "property": "smoke_detected",
                    "value": True,
                    "severity": "critical",
                    "summary": "SMOKE DETECTED in kitchen! Critical alert.",
                }
            return {"summary": "No kitchen sensor in scene"}

        elif event_type == "battery_low":
            battery_devices = [d for d in self._active_devices if d in self._device_battery]
            if battery_devices:
                device_id = random.choice(battery_devices)
                # Force battery low
                self._device_battery[device_id] = random.uniform(5, 15)
                self._device_states[device_id]["battery"] = round(self._device_battery[device_id], 1)
                return {
                    "device_id": device_id,
                    "property": "battery",
                    "value": self._device_battery[device_id],
                    "severity": "warning",
                    "summary": f"{device_id} battery low: {self._device_battery[device_id]:.0f}%",
                }
            return {"summary": "No battery-powered devices in scene"}

        elif event_type == "device_offline":
            online_devices = [d for d in self._active_devices if self._device_online.get(d, False)]
            if online_devices:
                device_id = random.choice(online_devices)
                self._device_online[device_id] = False
                self._device_states[device_id]["online"] = False
                return {
                    "device_id": device_id,
                    "summary": f"{device_id} went offline",
                }
            return {"summary": "All devices already offline"}

        elif event_type == "device_reconnect":
            offline_devices = [d for d in self._active_devices if not self._device_online.get(d, True)]
            if offline_devices:
                device_id = random.choice(offline_devices)
                self._device_online[device_id] = True
                self._device_states[device_id]["online"] = True
                return {
                    "device_id": device_id,
                    "summary": f"{device_id} reconnected",
                }
            return {"summary": "All devices already online"}

        elif event_type == "ota_available":
            non_ota = [d for d in self._active_devices if d not in self._ota_devices]
            if non_ota:
                device_id = random.choice(non_ota)
                return self._start_ota(device_id)
            return {"summary": "All devices already in OTA"}

        elif event_type == "tamper_alert":
            if "front_door_lock" in self._active_devices:
                self._device_states["front_door_lock"]["tamper_alert"] = True
                return {
                    "device_id": "front_door_lock",
                    "property": "tamper_alert",
                    "value": True,
                    "severity": "critical",
                    "summary": "TAMPER ALERT on front door lock!",
                }
            return {"summary": "No front door lock in scene"}

        return {"summary": f"Unknown event type: {event_type}"}

    # ------------------------------------------------------------------
    # Private: Message Logging
    # ------------------------------------------------------------------

    def _log_message(self, device_id: str, topic: str, direction: str, payload: dict[str, Any]) -> None:
        """Log an MQTT-style message to history."""
        self._message_history.append({
            "timestamp": time.time(),
            "device_id": device_id,
            "topic": topic,
            "direction": direction,  # "publish" or "subscribe"
            "payload": payload,
        })

    def _format_last_seen(self, device_id: str) -> str:
        """Format the last time a device was seen online."""
        # Find last successful message for this device
        for msg in reversed(self._message_history):
            if msg["device_id"] == device_id and not msg["payload"].get("error"):
                elapsed = time.time() - msg["timestamp"]
                if elapsed < 60:
                    return f"{elapsed:.0f}s ago"
                elif elapsed < 3600:
                    return f"{elapsed/60:.0f}m ago"
                return f"{elapsed/3600:.1f}h ago"
        return "unknown"

    # ------------------------------------------------------------------
    # Private: CDD Builder
    # ------------------------------------------------------------------

    def _build_cdd(self, device_id: str) -> CDD:
        """Build a Capability Description Document for a device."""
        dev_config = DEVICES[device_id]
        capabilities = []

        # Writable capabilities
        for cap_tuple in dev_config["capabilities"]:
            name, cap_type, writable, safety, value_range, description = cap_tuple
            vr = None
            if value_range is not None:
                if isinstance(value_range, dict):
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

        # Read-only sensors
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

        # Actions as capabilities
        for action_name, action_info in dev_config.get("actions", {}).items():
            capabilities.append(DeviceCapability(
                name=action_name,
                cap_type="action",
                readable=False,
                writable=True,
                safety_level=action_info["safety"],
                description=action_info["description"],
            ))

        # Always include trigger_ota as available action
        capabilities.append(DeviceCapability(
            name="trigger_ota",
            cap_type="action",
            readable=False,
            writable=True,
            safety_level=SafetyLevel.HIGH,
            description="Trigger firmware OTA update (device uncontrollable during update)",
        ))

        # Determine overall safety class
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
                "engine": "mqtt_iot_mock",
                "protocol": "mqtt",
                "topic_prefix": dev_config["topic_prefix"],
                "battery_powered": dev_config["battery_powered"],
                "online": self._device_online.get(device_id, True),
            },
        )
