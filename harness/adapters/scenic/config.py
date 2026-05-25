"""Scenic autonomous driving scenario configuration."""

from harness.models import SafetyLevel

DEVICE_ID = "ego_vehicle"
DEVICE_TYPE = "autonomous_vehicle"
DISPLAY_NAME = "Ego Vehicle (Scenic)"

# Vehicle property ranges
SPEED_RANGE = (0.0, 30.0)        # m/s
STEERING_RANGE = (-1.0, 1.0)     # normalized
THROTTLE_RANGE = (0.0, 1.0)      # normalized
BRAKE_RANGE = (0.0, 1.0)         # normalized

# Scenarios available
SCENARIOS = [
    "intersection_crossing",
    "highway_merge",
    "pedestrian_crossing",
    "lane_follow",
]

# Actions
ACTIONS = {
    "start_scenario": {
        "safety": SafetyLevel.HIGH,
        "description": "Start or restart the current scenario simulation",
    },
    "step_scenario": {
        "safety": SafetyLevel.HIGH,
        "description": "Advance the scenario simulation by one timestep",
    },
    "reset_scenario": {
        "safety": SafetyLevel.HIGH,
        "description": "Reset scenario to initial state",
    },
    "change_lane": {
        "safety": SafetyLevel.CRITICAL,
        "description": "Execute lane change maneuver (params: direction='left'|'right')",
    },
    "emergency_brake": {
        "safety": SafetyLevel.CRITICAL,
        "description": "Apply emergency braking (full brake, zero throttle)",
    },
}

# Simulation parameters
SIM_TIMESTEP = 0.05  # 50ms (20 Hz)
LANE_WIDTH = 3.7     # meters (standard US lane)
ROAD_LENGTH = 200.0  # meters

# Default scenario file
DEFAULT_SCENARIO_FILE = "lane_follow.scenic"
