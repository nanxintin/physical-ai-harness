"""Webots R2025a e-puck differential drive robot configuration."""

from harness.models import SafetyLevel

DEVICE_ID = "epuck"
DEVICE_TYPE = "differential_drive_robot"
DISPLAY_NAME = "e-puck Robot"

# Motor speed range (rad/s)
MOTOR_SPEED_RANGE = (-6.28, 6.28)

# Distance sensors (8 infrared proximity sensors)
DISTANCE_SENSOR_NAMES = [f"ps{i}" for i in range(8)]
DISTANCE_SENSOR_RANGE = (0, 4095)  # raw ADC values

# Light sensors (8 ambient light sensors)
LIGHT_SENSOR_NAMES = [f"ls{i}" for i in range(8)]
LIGHT_SENSOR_RANGE = (0, 4095)

# e-puck sensor angles (radians from front, counterclockwise)
DISTANCE_SENSOR_ANGLES = [
    1.27,    # ps0: front-right
    0.77,    # ps1: right-front
    0.00,    # ps2: right
    -1.21,   # ps3: right-back
    -1.92,   # ps4: back-left (approx)
    -2.37,   # ps5: left-back
    3.14,    # ps6: left
    2.37,    # ps7: left-front
]

# Robot physical parameters
WHEEL_RADIUS = 0.0205  # meters
AXLE_LENGTH = 0.052    # meters (distance between wheels)
MAX_LINEAR_SPEED = WHEEL_RADIUS * 6.28  # ~0.129 m/s

# Actions
ACTIONS = {
    "forward": {
        "safety": SafetyLevel.MEDIUM,
        "description": "Move forward at specified speed for duration",
    },
    "backward": {
        "safety": SafetyLevel.MEDIUM,
        "description": "Move backward at specified speed for duration",
    },
    "turn_left": {
        "safety": SafetyLevel.MEDIUM,
        "description": "Turn left in place by specified angle",
    },
    "turn_right": {
        "safety": SafetyLevel.MEDIUM,
        "description": "Turn right in place by specified angle",
    },
    "stop": {
        "safety": SafetyLevel.LOW,
        "description": "Stop both motors immediately",
    },
    "wall_follow": {
        "safety": SafetyLevel.MEDIUM,
        "description": "Follow wall on specified side (left/right)",
    },
}

# Webots controller connection
WEBOTS_HOST = "localhost"
WEBOTS_PORT = 1234
TIMESTEP = 64  # ms (simulation timestep)
