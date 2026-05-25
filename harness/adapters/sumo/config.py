"""SUMO traffic simulation configuration: vehicles, traffic lights, actions."""

from harness.models import SafetyLevel

# --- Vehicle Properties ---
VEHICLE_PROPERTIES = {
    "speed": {"type": "float", "min": 0.0, "max": 50.0, "unit": "m/s"},
    "lane": {"type": "int", "min": 0, "max": 3},
    "acceleration": {"type": "float", "min": -5.0, "max": 5.0, "unit": "m/s^2"},
}

# --- Traffic Light Phases ---
TRAFFIC_LIGHT_PHASES = ["red", "yellow", "green"]

# --- Vehicle Actions ---
VEHICLE_ACTIONS = {
    "change_lane": {
        "safety": SafetyLevel.HIGH,
        "description": "Change lane (params: direction='left'|'right')",
        "params": {"direction": {"type": "enum", "values": ["left", "right"]}},
    },
    "emergency_stop": {
        "safety": SafetyLevel.CRITICAL,
        "description": "Emergency stop: immediately set speed to 0",
    },
    "set_route": {
        "safety": SafetyLevel.HIGH,
        "description": "Set vehicle route (params: edges=[list of edge IDs])",
        "params": {"edges": {"type": "list"}},
    },
}

# --- Traffic Light Actions ---
TRAFFIC_LIGHT_ACTIONS = {
    "next_phase": {
        "safety": SafetyLevel.CRITICAL,
        "description": "Advance traffic light to next phase in cycle",
    },
    "set_phase": {
        "safety": SafetyLevel.CRITICAL,
        "description": "Set traffic light phase directly (params: phase='red'|'yellow'|'green')",
        "params": {"phase": {"type": "enum", "values": ["red", "yellow", "green"]}},
    },
}

# --- Safety Classes ---
VEHICLE_SAFETY_CLASS = SafetyLevel.HIGH
TRAFFIC_LIGHT_SAFETY_CLASS = SafetyLevel.CRITICAL

# --- Scene Definitions ---
SCENES = {
    "intersection": {
        "description": "Simple 4-way intersection with traffic lights",
        "config_file": "intersection.sumocfg",
    },
    "highway": {
        "description": "Multi-lane highway segment",
        "config_file": "highway.sumocfg",
    },
    "urban_grid": {
        "description": "Urban grid with multiple intersections",
        "config_file": "urban_grid.sumocfg",
    },
}

# --- Default Device IDs ---
DEFAULT_VEHICLES = ["ego_vehicle", "vehicle_1", "vehicle_2"]
DEFAULT_TRAFFIC_LIGHTS = ["tl_north", "tl_east"]

# --- SUMO Connection ---
SUMO_BINARY = "sumo"
SUMO_GUI_BINARY = "sumo-gui"
DEFAULT_PORT = 8813
STEP_LENGTH = 0.1  # seconds per simulation step
