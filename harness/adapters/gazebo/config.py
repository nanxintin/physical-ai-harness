"""Gazebo Harmonic TurtleBot3 robot configuration."""

from harness.models import SafetyLevel

DEVICE_ID = "turtlebot3"
DEVICE_TYPE = "mobile_robot"
DISPLAY_NAME = "TurtleBot3 Burger"

# Velocity limits
LINEAR_VEL_RANGE = (-0.26, 0.26)   # m/s
ANGULAR_VEL_RANGE = (-1.82, 1.82)  # rad/s

# Sensor definitions
LIDAR_NUM_RAYS = 360
LIDAR_MAX_RANGE = 3.5  # meters

IMU_FIELDS = ["orientation", "angular_velocity"]
ODOM_FIELDS = ["position", "velocity"]

# Actions available
ACTIONS = {
    "navigate_to": {
        "safety": SafetyLevel.HIGH,
        "description": "Navigate to target position [x, y] using path planning",
    },
    "stop": {
        "safety": SafetyLevel.MEDIUM,
        "description": "Immediately stop all movement (zero velocities)",
    },
    "rotate": {
        "safety": SafetyLevel.HIGH,
        "description": "Rotate in place by given angle (radians)",
    },
    "dock": {
        "safety": SafetyLevel.HIGH,
        "description": "Dock to charging station (approach and align)",
    },
}

# ROS2 topics
TOPICS = {
    "cmd_vel": "/cmd_vel",
    "odom": "/odom",
    "scan": "/scan",
    "imu": "/imu",
    "camera": "/camera/image_raw",
}

# Default world file
DEFAULT_WORLD = "empty_world.sdf"
