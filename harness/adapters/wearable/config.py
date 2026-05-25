"""Wearable sensor stream configuration."""

from harness.models import SafetyLevel

# --- Device ---
DEVICE_ID = "smart_band_01"
DEVICE_TYPE = "wearable_band"
DISPLAY_NAME = "Smart Band Pro"

# --- Sensor specifications ---
SENSORS = {
    "heart_rate": {"type": "float", "range": (40, 200), "unit": "bpm", "update_hz": 1.0},
    "blood_oxygen": {"type": "float", "range": (70, 100), "unit": "%", "update_hz": 0.2},
    "step_count": {"type": "float", "range": (0, 50000), "unit": "steps", "update_hz": 0.1},
    "calories_burned": {"type": "float", "range": (0, 5000), "unit": "kcal", "update_hz": 0.1},
    "sleep_state": {
        "type": "enum",
        "values": ["awake", "light_sleep", "deep_sleep", "rem"],
        "update_hz": 0.01,
    },
    "stress_level": {"type": "float", "range": (0, 100), "unit": "score", "update_hz": 0.05},
    "skin_temperature": {"type": "float", "range": (30, 40), "unit": "celsius", "update_hz": 0.1},
    "battery": {"type": "float", "range": (0, 100), "unit": "%", "update_hz": 0.001},
}

# --- Actions ---
ACTIONS = {
    "display_message": {
        "safety": SafetyLevel.LOW,
        "description": "Show notification on band screen",
    },
    "vibrate": {
        "safety": SafetyLevel.LOW,
        "description": "Trigger vibration alert",
        "params": {"pattern": ["short", "long", "sos"]},
    },
    "start_workout": {
        "safety": SafetyLevel.LOW,
        "description": "Begin workout tracking",
        "params": {"type": ["running", "walking", "cycling", "swimming"]},
    },
    "stop_workout": {
        "safety": SafetyLevel.LOW,
        "description": "End workout tracking",
    },
    "set_alarm": {
        "safety": SafetyLevel.LOW,
        "description": "Set a vibration alarm",
        "params": {"time": "HH:MM"},
    },
}

# --- Activity profiles for data generation ---
PROFILES = {
    "resting": {"hr_base": 65, "hr_var": 5, "spo2_base": 97, "steps_per_min": 0},
    "walking": {"hr_base": 90, "hr_var": 10, "spo2_base": 96, "steps_per_min": 100},
    "running": {"hr_base": 145, "hr_var": 15, "spo2_base": 95, "steps_per_min": 170},
    "sleeping": {"hr_base": 55, "hr_var": 3, "spo2_base": 97, "steps_per_min": 0},
    "stressed": {"hr_base": 95, "hr_var": 20, "spo2_base": 96, "steps_per_min": 10},
}

# --- Anomaly events (for training LLM health reasoning) ---
ANOMALIES = {
    "tachycardia": {"hr_spike_to": 180, "duration_s": 30, "desc": "Sudden heart rate spike"},
    "hypoxia": {"spo2_drop_to": 85, "duration_s": 60, "desc": "Blood oxygen drop"},
    "fall_detected": {"desc": "Sudden acceleration spike indicating fall"},
    "irregular_rhythm": {"desc": "Irregular heartbeat pattern detected"},
}
