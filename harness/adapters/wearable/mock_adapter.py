"""Mock wearable sensor stream adapter for testing without hardware."""

from __future__ import annotations

import base64
import io
import math
import random
import time
from typing import Any

from PIL import Image, ImageDraw

from harness.adapter import Adapter
from harness.adapters.wearable.config import (
    ACTIONS,
    ANOMALIES,
    DEVICE_ID,
    DEVICE_TYPE,
    DISPLAY_NAME,
    PROFILES,
    SENSORS,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel


class MockWearableAdapter(Adapter):
    """Mock adapter simulating continuous health/fitness sensor data streams."""

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._devices: dict[str, CDD] = {}
        self._sim_time: float = 0.0
        self._dt: float = 1.0  # seconds per tick

        # Current activity profile
        self._profile_name: str = "resting"

        # Accumulated state
        self._step_count: float = 0.0
        self._calories_burned: float = 0.0
        self._battery: float = 95.0
        self._sleep_state: str = "awake"

        # Workout tracking
        self._workout_active: bool = False
        self._workout_type: str | None = None
        self._workout_start_time: float = 0.0
        self._workout_distance: float = 0.0
        self._workout_hr_samples: list[float] = []

        # Anomaly state
        self._active_anomaly: str | None = None
        self._anomaly_start_time: float = 0.0
        self._anomaly_duration: float = 0.0

        # Notification log
        self._notifications: list[str] = []
        self._alarms: list[str] = []

    @property
    def is_initialized(self) -> bool:
        return bool(self._devices)

    async def initialize(self, scene: str = "daily_activity") -> dict[str, Any]:
        self._sim_time = 0.0
        self._step_count = 0.0
        self._calories_burned = 0.0
        self._battery = 95.0
        self._sleep_state = "awake"
        self._profile_name = "resting"
        self._workout_active = False
        self._workout_type = None
        self._active_anomaly = None
        self._notifications = []
        self._alarms = []
        self._devices = {DEVICE_ID: self._build_cdd()}
        return {
            "scene": scene,
            "device_count": 1,
            "device_types": [DEVICE_TYPE],
            "engine": "wearable_mock",
            "model": DISPLAY_NAME,
            "sensors": list(SENSORS.keys()),
        }

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")

        # Advance simulation time
        self._sim_time += self._dt
        props = self._generate_sensor_data()

        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")

        # Wearable is mostly read-only; only a few properties can be set
        if property_name == "profile":
            if value not in PROFILES:
                raise ValueError(
                    f"Unknown profile: {value}. Available: {list(PROFILES.keys())}"
                )
            self._profile_name = value
        elif property_name == "sleep_state":
            valid_states = SENSORS["sleep_state"]["values"]
            if value not in valid_states:
                raise ValueError(f"Invalid sleep state: {value}. Valid: {valid_states}")
            self._sleep_state = value
            if value != "awake":
                self._profile_name = "sleeping"
            else:
                self._profile_name = "resting"
        else:
            raise ValueError(
                f"Cannot write to property '{property_name}'. "
                "Wearable sensors are mostly read-only."
            )

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": value,
        })
        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")
        if action not in ACTIONS:
            raise ValueError(f"Unknown action: {action}. Available: {list(ACTIONS.keys())}")

        params = params or {}

        if action == "display_message":
            msg = params.get("message", "Notification")
            self._notifications.append(msg)
            result = {"displayed": msg}

        elif action == "vibrate":
            pattern = params.get("pattern", "short")
            valid_patterns = ACTIONS["vibrate"]["params"]["pattern"]
            if pattern not in valid_patterns:
                raise ValueError(f"Invalid pattern: {pattern}. Valid: {valid_patterns}")
            result = {"vibrated": pattern}

        elif action == "start_workout":
            workout_type = params.get("type", "running")
            valid_types = ACTIONS["start_workout"]["params"]["type"]
            if workout_type not in valid_types:
                raise ValueError(f"Invalid workout type: {workout_type}. Valid: {valid_types}")
            self._workout_active = True
            self._workout_type = workout_type
            self._workout_start_time = self._sim_time
            self._workout_distance = 0.0
            self._workout_hr_samples = []
            # Switch profile
            if workout_type == "running":
                self._profile_name = "running"
            elif workout_type in ("walking", "cycling", "swimming"):
                self._profile_name = "walking"
            result = {"workout_started": workout_type}

        elif action == "stop_workout":
            if not self._workout_active:
                result = {"error": "No active workout to stop"}
            else:
                elapsed = self._sim_time - self._workout_start_time
                avg_hr = (
                    sum(self._workout_hr_samples) / len(self._workout_hr_samples)
                    if self._workout_hr_samples
                    else 0
                )
                result = {
                    "workout_stopped": self._workout_type,
                    "elapsed_s": elapsed,
                    "distance_m": self._workout_distance,
                    "avg_hr": round(avg_hr, 1),
                    "calories": round(self._calories_burned, 1),
                }
                self._workout_active = False
                self._workout_type = None
                self._profile_name = "resting"

        elif action == "set_alarm":
            alarm_time = params.get("time", "07:00")
            self._alarms.append(alarm_time)
            result = {"alarm_set": alarm_time}

        else:
            result = {"error": f"Unhandled action: {action}"}

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params, "result": result, "mock": True}

    def inject_anomaly(self, anomaly_type: str) -> dict[str, Any]:
        """Trigger a health anomaly event for training purposes."""
        if anomaly_type not in ANOMALIES:
            raise ValueError(
                f"Unknown anomaly: {anomaly_type}. Available: {list(ANOMALIES.keys())}"
            )
        anomaly = ANOMALIES[anomaly_type]
        self._active_anomaly = anomaly_type
        self._anomaly_start_time = self._sim_time
        self._anomaly_duration = anomaly.get("duration_s", 30)
        return {"anomaly_injected": anomaly_type, "description": anomaly.get("desc", "")}

    async def capture_image(self) -> str:
        """Draw a wearable dashboard showing sensor readings."""
        img = Image.new("RGB", (400, 300), color=(20, 20, 30))
        draw = ImageDraw.Draw(img)

        # Generate current readings
        props = self._generate_sensor_data()

        # Title bar
        draw.rectangle([0, 0, 400, 35], fill=(40, 40, 60))
        draw.text((10, 10), f"{DISPLAY_NAME}", fill=(255, 255, 255))
        draw.text((300, 10), f"BAT: {props['battery']:.0f}%", fill=(100, 255, 100))

        # Heart rate section
        hr = props["heart_rate"]
        hr_color = (255, 80, 80) if hr > 150 else (255, 150, 80) if hr > 100 else (80, 255, 120)
        draw.text((20, 50), "HR", fill=(180, 180, 180))
        draw.text((20, 70), f"{hr:.0f} bpm", fill=hr_color)

        # Draw a simple heart rate graph (last few seconds simulated)
        graph_x, graph_y, graph_w, graph_h = 120, 45, 260, 50
        draw.rectangle([graph_x, graph_y, graph_x + graph_w, graph_y + graph_h], outline=(60, 60, 80))
        profile = PROFILES[self._profile_name]
        for i in range(graph_w):
            t = self._sim_time - graph_w + i
            val = profile["hr_base"] + profile["hr_var"] * math.sin(t * 0.1)
            normalized = (val - 40) / 160.0
            py = graph_y + graph_h - int(normalized * graph_h)
            py = max(graph_y, min(graph_y + graph_h, py))
            draw.point((graph_x + i, py), fill=hr_color)

        # SpO2
        spo2 = props["blood_oxygen"]
        spo2_color = (255, 80, 80) if spo2 < 90 else (255, 200, 80) if spo2 < 95 else (80, 200, 255)
        draw.text((20, 110), "SpO2", fill=(180, 180, 180))
        draw.text((20, 130), f"{spo2:.1f}%", fill=spo2_color)

        # Steps
        draw.text((150, 110), "Steps", fill=(180, 180, 180))
        draw.text((150, 130), f"{props['step_count']:.0f}", fill=(200, 200, 255))

        # Calories
        draw.text((280, 110), "Cal", fill=(180, 180, 180))
        draw.text((280, 130), f"{props['calories_burned']:.0f}", fill=(255, 180, 100))

        # Stress / Temperature
        draw.text((20, 170), "Stress", fill=(180, 180, 180))
        draw.text((20, 190), f"{props['stress_level']:.0f}/100", fill=(255, 255, 150))
        draw.text((150, 170), "Temp", fill=(180, 180, 180))
        draw.text((150, 190), f"{props['skin_temperature']:.1f} C", fill=(200, 200, 200))

        # Sleep state
        draw.text((280, 170), "Sleep", fill=(180, 180, 180))
        draw.text((280, 190), props["sleep_state"], fill=(150, 150, 255))

        # Workout bar
        if self._workout_active:
            draw.rectangle([0, 230, 400, 265], fill=(30, 80, 30))
            elapsed = self._sim_time - self._workout_start_time
            draw.text(
                (20, 237),
                f"WORKOUT: {self._workout_type}  |  {elapsed:.0f}s  |  {self._workout_distance:.0f}m",
                fill=(100, 255, 100),
            )

        # Anomaly indicator
        if self._active_anomaly:
            draw.rectangle([0, 270, 400, 300], fill=(120, 20, 20))
            desc = ANOMALIES[self._active_anomaly].get("desc", self._active_anomaly)
            draw.text((20, 277), f"ALERT: {desc}", fill=(255, 255, 80))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    # --- Private helpers ---

    def _generate_sensor_data(self) -> dict[str, Any]:
        """Generate realistic sensor readings based on current profile and anomalies."""
        profile = PROFILES[self._profile_name]
        t = self._sim_time

        # Check if anomaly has expired
        if self._active_anomaly:
            if t - self._anomaly_start_time > self._anomaly_duration:
                self._active_anomaly = None

        # Heart rate
        hr = profile["hr_base"] + profile["hr_var"] * math.sin(t * 0.1) + random.gauss(0, 2)
        if self._active_anomaly == "tachycardia":
            hr = ANOMALIES["tachycardia"]["hr_spike_to"] + random.gauss(0, 5)
        elif self._active_anomaly == "irregular_rhythm":
            hr += random.choice([-20, 0, 0, 30]) * random.random()
        hr = max(SENSORS["heart_rate"]["range"][0], min(SENSORS["heart_rate"]["range"][1], hr))

        # Blood oxygen
        spo2 = profile["spo2_base"] + random.gauss(0, 0.5)
        if self._active_anomaly == "hypoxia":
            spo2 = ANOMALIES["hypoxia"]["spo2_drop_to"] + random.gauss(0, 1)
        spo2 = max(SENSORS["blood_oxygen"]["range"][0], min(SENSORS["blood_oxygen"]["range"][1], spo2))

        # Steps (accumulate)
        steps_increment = profile["steps_per_min"] / 60.0 * self._dt
        self._step_count += steps_increment

        # Calories (rough MET-based estimate)
        met_factor = 1.0
        if self._profile_name == "walking":
            met_factor = 3.5
        elif self._profile_name == "running":
            met_factor = 8.0
        elif self._profile_name == "stressed":
            met_factor = 1.5
        # ~1 kcal per kg per hour per MET, assume 70kg, convert to per-second
        cal_increment = (met_factor * 70.0 / 3600.0) * self._dt
        self._calories_burned += cal_increment

        # Sleep state
        if self._profile_name == "sleeping":
            # Cycle through sleep stages
            cycle_pos = (t % 5400) / 5400.0  # 90 min sleep cycle
            if cycle_pos < 0.1:
                self._sleep_state = "light_sleep"
            elif cycle_pos < 0.4:
                self._sleep_state = "deep_sleep"
            elif cycle_pos < 0.6:
                self._sleep_state = "light_sleep"
            elif cycle_pos < 0.8:
                self._sleep_state = "rem"
            else:
                self._sleep_state = "light_sleep"
        else:
            self._sleep_state = "awake"

        # Stress level
        stress_base = 30 if self._profile_name != "stressed" else 75
        stress = stress_base + 10 * math.sin(t * 0.02) + random.gauss(0, 3)
        stress = max(0, min(100, stress))

        # Skin temperature
        temp_base = 36.5 if self._profile_name != "running" else 37.2
        skin_temp = temp_base + 0.3 * math.sin(t * 0.005) + random.gauss(0, 0.1)
        skin_temp = max(SENSORS["skin_temperature"]["range"][0], min(SENSORS["skin_temperature"]["range"][1], skin_temp))

        # Battery (slow drain)
        self._battery -= 0.001 * self._dt
        if self._workout_active:
            self._battery -= 0.005 * self._dt  # Faster drain during workout
        self._battery = max(0, self._battery)

        # Update workout tracking
        if self._workout_active:
            self._workout_hr_samples.append(hr)
            # Approximate distance based on steps
            stride_m = 0.75 if self._workout_type == "running" else 0.6
            self._workout_distance += steps_increment * stride_m

        props = {
            "heart_rate": round(hr, 1),
            "blood_oxygen": round(spo2, 1),
            "step_count": round(self._step_count),
            "calories_burned": round(self._calories_burned, 1),
            "sleep_state": self._sleep_state,
            "stress_level": round(stress, 1),
            "skin_temperature": round(skin_temp, 2),
            "battery": round(self._battery, 1),
        }

        # Include workout info if active
        if self._workout_active:
            props["workout"] = {
                "active": True,
                "type": self._workout_type,
                "elapsed_s": round(self._sim_time - self._workout_start_time, 1),
                "distance_m": round(self._workout_distance, 1),
                "avg_hr": round(
                    sum(self._workout_hr_samples) / len(self._workout_hr_samples), 1
                ) if self._workout_hr_samples else 0,
            }

        # Include anomaly info if active
        if self._active_anomaly:
            props["anomaly"] = {
                "type": self._active_anomaly,
                "description": ANOMALIES[self._active_anomaly].get("desc", ""),
                "remaining_s": round(
                    self._anomaly_duration - (t - self._anomaly_start_time), 1
                ),
            }

        return props

    def _build_cdd(self) -> CDD:
        capabilities = []

        # Sensor capabilities (read-only)
        for sensor_name, spec in SENSORS.items():
            if spec["type"] == "float":
                capabilities.append(DeviceCapability(
                    name=sensor_name,
                    cap_type="float",
                    readable=True,
                    writable=False,
                    safety_level=SafetyLevel.LOW,
                    value_range={"min": spec["range"][0], "max": spec["range"][1]},
                    description=f"{sensor_name.replace('_', ' ').title()} ({spec['unit']}, {spec['update_hz']} Hz)",
                ))
            elif spec["type"] == "enum":
                capabilities.append(DeviceCapability(
                    name=sensor_name,
                    cap_type="enum",
                    readable=True,
                    writable=False,
                    safety_level=SafetyLevel.LOW,
                    value_range={"values": spec["values"]},
                    description=f"{sensor_name.replace('_', ' ').title()} ({spec['update_hz']} Hz)",
                ))

        # Action capabilities
        for action_name, action_info in ACTIONS.items():
            capabilities.append(DeviceCapability(
                name=action_name,
                cap_type="action",
                readable=False,
                writable=True,
                safety_level=action_info["safety"],
                description=action_info["description"],
            ))

        return CDD(
            device_id=DEVICE_ID,
            device_type=DEVICE_TYPE,
            display_name=DISPLAY_NAME,
            location="wrist",
            capabilities=capabilities,
            safety_class=SafetyLevel.LOW,
            metadata={
                "engine": "wearable_mock",
                "profiles": list(PROFILES.keys()),
                "anomalies": list(ANOMALIES.keys()),
            },
        )
