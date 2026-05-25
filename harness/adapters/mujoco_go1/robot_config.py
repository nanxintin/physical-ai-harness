"""Unitree Go1 robot configuration: joints, ranges, poses, actions."""

from harness.models import SafetyLevel

ACTUATOR_NAMES = [
    "FR_hip", "FR_thigh", "FR_calf",
    "FL_hip", "FL_thigh", "FL_calf",
    "RR_hip", "RR_thigh", "RR_calf",
    "RL_hip", "RL_thigh", "RL_calf",
]

JOINT_NAMES = [
    "FR_hip_joint", "FR_thigh_joint", "FR_calf_joint",
    "FL_hip_joint", "FL_thigh_joint", "FL_calf_joint",
    "RR_hip_joint", "RR_thigh_joint", "RR_calf_joint",
    "RL_hip_joint", "RL_thigh_joint", "RL_calf_joint",
]

JOINT_RANGES = {
    "hip": (-0.863, 0.863),
    "thigh": (-0.686, 4.501),
    "calf": (-2.818, -0.888),
}

def get_joint_range(joint_name: str) -> tuple[float, float]:
    for key, rng in JOINT_RANGES.items():
        if key in joint_name.lower():
            return rng
    return (-3.14, 3.14)

STAND_POSE = [0.0, 0.8, -1.6] * 4
SIT_POSE = [0.0, 1.5, -2.5] * 4
REST_POSE = [0.0, 1.2, -2.4] * 4

ACTIONS = {
    "stand": {"safety": SafetyLevel.HIGH, "description": "Stand up from any position"},
    "sit": {"safety": SafetyLevel.HIGH, "description": "Sit down"},
    "walk_forward": {"safety": SafetyLevel.HIGH, "description": "Walk forward at given speed"},
    "walk_backward": {"safety": SafetyLevel.HIGH, "description": "Walk backward"},
    "turn_left": {"safety": SafetyLevel.HIGH, "description": "Turn left ~45 degrees"},
    "turn_right": {"safety": SafetyLevel.HIGH, "description": "Turn right ~45 degrees"},
    "trot": {"safety": SafetyLevel.CRITICAL, "description": "Fast trotting gait (dangerous)"},
    "stop": {"safety": SafetyLevel.MEDIUM, "description": "Emergency stop"},
}

DEVICE_ID = "unitree_go1"
DEVICE_TYPE = "quadruped_robot"
DISPLAY_NAME = "Unitree Go1"
