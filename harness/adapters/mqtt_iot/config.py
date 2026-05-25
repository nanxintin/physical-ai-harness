"""MQTT IoT Smart Home device configuration.

Defines a virtual smart home with diverse devices that expose real-world IoT
communication challenges: async messaging, device timeouts, message delays,
OTA states, and batch operations.
"""

from harness.models import SafetyLevel

# ---------------------------------------------------------------------------
# Device Definitions
# ---------------------------------------------------------------------------

DEVICES = {
    "bedroom_light": {
        "type": "smart_light",
        "protocol": "mqtt",
        "topic_prefix": "home/bedroom/light_01",
        "location": "bedroom",
        "display_name": "Bedroom Smart Light",
        "capabilities": [
            ("power", "boolean", True, SafetyLevel.LOW, None, "Power on/off"),
            ("brightness", "float", True, SafetyLevel.LOW, {"min": 0, "max": 100}, "Brightness percentage"),
            ("color_temp", "float", True, SafetyLevel.LOW, {"min": 2700, "max": 6500}, "Color temperature (K)"),
        ],
        "sensors": [
            ("online", "boolean", "Device connectivity status"),
            ("signal_strength", "float", "Wi-Fi RSSI in dBm"),
            ("firmware_version", "string", "Current firmware version"),
        ],
        "actions": {},
        "battery_powered": False,
        "initial_state": {
            "power": False,
            "brightness": 80.0,
            "color_temp": 4000.0,
            "online": True,
            "signal_strength": -45.0,
            "firmware_version": "2.1.3",
        },
    },
    "living_room_ac": {
        "type": "air_conditioner",
        "protocol": "mqtt",
        "topic_prefix": "home/living_room/ac_01",
        "location": "living_room",
        "display_name": "Living Room AC",
        "capabilities": [
            ("power", "boolean", True, SafetyLevel.LOW, None, "Power on/off"),
            ("target_temp", "float", True, SafetyLevel.MEDIUM, {"min": 16, "max": 30}, "Target temperature (C)"),
            ("mode", "enum", True, SafetyLevel.LOW, {"values": ["cool", "heat", "fan", "auto"]}, "Operation mode"),
            ("fan_speed", "enum", True, SafetyLevel.LOW, {"values": ["low", "medium", "high", "auto"]}, "Fan speed"),
        ],
        "sensors": [
            ("current_temp", "float", "Room temperature reading"),
            ("humidity", "float", "Room humidity percentage"),
            ("power_consumption", "float", "Current power in watts"),
            ("online", "boolean", "Device connectivity status"),
            ("signal_strength", "float", "Wi-Fi RSSI in dBm"),
            ("firmware_version", "string", "Current firmware version"),
        ],
        "actions": {},
        "battery_powered": False,
        "initial_state": {
            "power": False,
            "target_temp": 24.0,
            "mode": "cool",
            "fan_speed": "auto",
            "current_temp": 26.5,
            "humidity": 55.0,
            "power_consumption": 0.0,
            "online": True,
            "signal_strength": -52.0,
            "firmware_version": "1.4.7",
        },
    },
    "front_door_lock": {
        "type": "smart_lock",
        "protocol": "mqtt",
        "topic_prefix": "home/front_door/lock_01",
        "location": "front_door",
        "display_name": "Front Door Lock",
        "capabilities": [
            ("locked", "boolean", True, SafetyLevel.CRITICAL, None, "Lock/unlock state"),
        ],
        "sensors": [
            ("battery", "float", "Battery level percentage"),
            ("last_unlock_time", "string", "ISO timestamp of last unlock"),
            ("tamper_alert", "boolean", "Tamper detection"),
            ("online", "boolean", "Device connectivity status"),
            ("signal_strength", "float", "Wi-Fi RSSI in dBm"),
            ("firmware_version", "string", "Current firmware version"),
        ],
        "actions": {},
        "battery_powered": True,
        "initial_state": {
            "locked": True,
            "battery": 78.0,
            "last_unlock_time": "2026-05-25T08:30:00+08:00",
            "tamper_alert": False,
            "online": True,
            "signal_strength": -60.0,
            "firmware_version": "3.0.1",
        },
    },
    "kitchen_sensor": {
        "type": "multi_sensor",
        "protocol": "mqtt",
        "topic_prefix": "home/kitchen/sensor_01",
        "location": "kitchen",
        "display_name": "Kitchen Multi-Sensor",
        "capabilities": [],  # Read-only device
        "sensors": [
            ("temperature", "float", "Temperature in Celsius"),
            ("humidity", "float", "Relative humidity %"),
            ("smoke_detected", "boolean", "Smoke alarm state"),
            ("motion_detected", "boolean", "PIR motion detection"),
            ("online", "boolean", "Device connectivity status"),
            ("signal_strength", "float", "Wi-Fi RSSI in dBm"),
            ("battery", "float", "Battery level percentage"),
            ("firmware_version", "string", "Current firmware version"),
        ],
        "actions": {},
        "battery_powered": True,
        "initial_state": {
            "temperature": 23.5,
            "humidity": 45.0,
            "smoke_detected": False,
            "motion_detected": False,
            "online": True,
            "signal_strength": -55.0,
            "battery": 92.0,
            "firmware_version": "1.2.0",
        },
    },
    "robot_vacuum": {
        "type": "robot_vacuum",
        "protocol": "mqtt",
        "topic_prefix": "home/vacuum_01",
        "location": "living_room",
        "display_name": "Robot Vacuum",
        "capabilities": [
            ("power", "boolean", True, SafetyLevel.MEDIUM, None, "Power on/off"),
        ],
        "sensors": [
            ("battery", "float", "Battery percentage"),
            ("status", "string", "idle/cleaning/charging/error/ota_updating"),
            ("area_cleaned", "float", "Square meters cleaned"),
            ("error_code", "string", "Error code if any"),
            ("online", "boolean", "Device connectivity status"),
            ("signal_strength", "float", "Wi-Fi RSSI in dBm"),
            ("firmware_version", "string", "Current firmware version"),
        ],
        "actions": {
            "start_clean": {
                "safety": SafetyLevel.MEDIUM,
                "description": "Start cleaning",
                "params": {"mode": ["standard", "turbo", "quiet"]},
            },
            "return_dock": {
                "safety": SafetyLevel.LOW,
                "description": "Return to charging dock",
            },
            "pause": {
                "safety": SafetyLevel.LOW,
                "description": "Pause cleaning",
            },
        },
        "battery_powered": True,
        "initial_state": {
            "power": True,
            "battery": 85.0,
            "status": "idle",
            "area_cleaned": 0.0,
            "error_code": "",
            "online": True,
            "signal_strength": -48.0,
            "firmware_version": "4.2.1",
        },
    },
}

# ---------------------------------------------------------------------------
# Communication Simulation Parameters
# ---------------------------------------------------------------------------

COMM_CONFIG = {
    "default_latency_ms": (50, 200),      # min, max simulated network latency
    "timeout_ms": 5000,                    # response timeout
    "offline_probability": 0.05,           # 5% chance device goes offline spontaneously
    "message_loss_probability": 0.02,      # 2% message drop rate
    "ota_update_duration_s": 30,           # seconds a device is uncontrollable during OTA
    "battery_drain_per_hour": 0.5,         # % battery drain per simulated hour
    "sensor_update_interval_s": 10,        # sensor readings refresh interval
    "reconnect_probability": 0.3,          # 30% chance an offline device comes back per check
}

# ---------------------------------------------------------------------------
# Scene Presets
# ---------------------------------------------------------------------------

SCENES = {
    "smart_home": {
        "description": "Full smart home (5 devices)",
        "devices": list(DEVICES.keys()),
        "offline_probability_override": None,
        "message_loss_override": None,
    },
    "minimal": {
        "description": "Bedroom light + kitchen sensor only",
        "devices": ["bedroom_light", "kitchen_sensor"],
        "offline_probability_override": None,
        "message_loss_override": None,
    },
    "unreliable": {
        "description": "All devices with high failure rate (20% offline, 10% message loss)",
        "devices": list(DEVICES.keys()),
        "offline_probability_override": 0.20,
        "message_loss_override": 0.10,
    },
}
