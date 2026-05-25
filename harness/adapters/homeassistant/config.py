"""Home Assistant adapter configuration."""

from harness.models import SafetyLevel

# --- Default HA connection ---
HA_URL = "http://localhost:8123"
HA_TOKEN_ENV = "HA_TOKEN"  # environment variable name

# --- Mock entities (simulating a typical HA installation) ---
MOCK_ENTITIES = {
    "light.living_room": {
        "state": "off",
        "attributes": {
            "brightness": 0,
            "color_temp": 370,
            "friendly_name": "Living Room Light",
        },
    },
    "light.bedroom": {
        "state": "off",
        "attributes": {
            "brightness": 0,
            "color_temp": 300,
            "friendly_name": "Bedroom Light",
        },
    },
    "climate.main_ac": {
        "state": "off",
        "attributes": {
            "temperature": 24,
            "current_temperature": 27,
            "hvac_modes": ["off", "cool", "heat", "auto"],
            "fan_modes": ["low", "medium", "high"],
            "friendly_name": "Main AC",
        },
    },
    "lock.front_door": {
        "state": "locked",
        "attributes": {
            "battery": 85,
            "friendly_name": "Front Door Lock",
        },
    },
    "cover.curtain_living": {
        "state": "closed",
        "attributes": {
            "current_position": 0,
            "friendly_name": "Living Room Curtain",
        },
    },
    "media_player.tv": {
        "state": "off",
        "attributes": {
            "volume_level": 0.5,
            "source_list": ["HDMI1", "HDMI2", "Netflix", "YouTube"],
            "friendly_name": "Living Room TV",
        },
    },
    "sensor.temperature_outdoor": {
        "state": "32",
        "attributes": {
            "unit_of_measurement": "°C",
            "friendly_name": "Outdoor Temperature",
        },
    },
    "sensor.humidity_indoor": {
        "state": "55",
        "attributes": {
            "unit_of_measurement": "%",
            "friendly_name": "Indoor Humidity",
        },
    },
    "binary_sensor.motion_hallway": {
        "state": "off",
        "attributes": {
            "friendly_name": "Hallway Motion",
        },
    },
    "vacuum.roborock": {
        "state": "docked",
        "attributes": {
            "battery_level": 100,
            "status": "idle",
            "friendly_name": "Robot Vacuum",
        },
    },
    "switch.water_heater": {
        "state": "off",
        "attributes": {
            "friendly_name": "Water Heater",
        },
    },
    "fan.bedroom": {
        "state": "off",
        "attributes": {
            "percentage": 0,
            "friendly_name": "Bedroom Fan",
        },
    },
}

# --- HA entity domain -> safety level mapping ---
SAFETY_MAP = {
    "light": SafetyLevel.LOW,
    "switch": SafetyLevel.LOW,
    "fan": SafetyLevel.LOW,
    "media_player": SafetyLevel.LOW,
    "climate": SafetyLevel.MEDIUM,
    "cover": SafetyLevel.MEDIUM,
    "vacuum": SafetyLevel.MEDIUM,
    "lock": SafetyLevel.CRITICAL,
    "sensor": SafetyLevel.LOW,
    "binary_sensor": SafetyLevel.LOW,
}

# --- HA services mapped to harness actions ---
SERVICE_MAP = {
    "light": ["turn_on", "turn_off", "toggle"],
    "climate": ["set_temperature", "set_hvac_mode", "set_fan_mode", "turn_off"],
    "lock": ["lock", "unlock"],
    "cover": ["open_cover", "close_cover", "set_cover_position"],
    "media_player": ["turn_on", "turn_off", "volume_set", "select_source", "media_play", "media_pause"],
    "vacuum": ["start", "pause", "return_to_base", "stop"],
    "switch": ["turn_on", "turn_off"],
    "fan": ["turn_on", "turn_off", "set_percentage"],
}

# --- Scene presets ---
SCENES = {
    "full_home": "All 12 entities",
    "bedroom_only": "Bedroom light + fan + curtain",
    "security": "Lock + motion sensor + camera",
}
