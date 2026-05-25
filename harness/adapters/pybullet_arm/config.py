"""PyBullet Franka Panda 7-DOF robot arm configuration."""

from harness.models import SafetyLevel

# --- Device ---
DEVICE_ID = "franka_panda"
DEVICE_TYPE = "robot_arm"
DISPLAY_NAME = "Franka Panda"

# --- Joint Configuration ---
JOINT_NAMES = [
    "panda_joint1",
    "panda_joint2",
    "panda_joint3",
    "panda_joint4",
    "panda_joint5",
    "panda_joint6",
    "panda_joint7",
]

# Joint ranges in radians (min, max) per DOF
JOINT_RANGES = {
    "panda_joint1": (-2.8973, 2.8973),
    "panda_joint2": (-1.7628, 1.7628),
    "panda_joint3": (-2.8973, 2.8973),
    "panda_joint4": (-3.0718, -0.0698),
    "panda_joint5": (-2.8973, 2.8973),
    "panda_joint6": (-0.0175, 3.7525),
    "panda_joint7": (-2.8973, 2.8973),
}

# Gripper range in meters (open, close)
GRIPPER_RANGE = (0.0, 0.04)

# --- Poses ---
HOME_POSITION = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]

# --- Actions ---
ACTIONS = {
    "home": {
        "safety": SafetyLevel.HIGH,
        "description": "Move all joints to the home position",
    },
    "pick": {
        "safety": SafetyLevel.HIGH,
        "description": "Execute pick motion at given position (params: x, y, z)",
    },
    "place": {
        "safety": SafetyLevel.HIGH,
        "description": "Execute place motion at given position (params: x, y, z)",
    },
    "open_gripper": {
        "safety": SafetyLevel.MEDIUM,
        "description": "Open the gripper to maximum width",
    },
    "close_gripper": {
        "safety": SafetyLevel.MEDIUM,
        "description": "Close the gripper fully",
    },
}

# --- Safety ---
JOINT_SAFETY_LEVEL = SafetyLevel.HIGH
GRIPPER_SAFETY_LEVEL = SafetyLevel.MEDIUM

# --- PyBullet Config ---
PANDA_URDF = "franka_panda/panda.urdf"
PANDA_NUM_JOINTS = 7
PANDA_END_EFFECTOR_INDEX = 11
PANDA_GRIPPER_INDICES = [9, 10]
SIM_TIMESTEP = 1.0 / 240.0
