"""Pre-defined evaluation tasks covering robot and IoT scenarios.

Each task specifies a natural language prompt, available tools context,
expected outcome, and execution constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    """A single evaluation task definition."""

    id: str
    type: str  # "robot_control", "device_control", "navigation", "multi_device", "traffic"
    prompt: str  # Natural language instruction
    system_prompt: str  # Context about available tools
    ground_truth: dict[str, Any]  # Expected outcome
    max_steps: int  # Maximum tool call turns
    backend: str  # Which mock adapter to use
    optimal_steps: int = 1  # Minimum steps a perfect agent needs
    metadata: dict[str, Any] = field(default_factory=dict)


# --- System prompts for different backends ---

ROBOT_SYSTEM_PROMPT = (
    "You are controlling a Unitree Go1 quadruped robot in simulation. "
    "Available tools:\n"
    "- scene_load(scene): Initialize the simulation environment\n"
    "- robot_move(action, speed, duration): Command locomotion. "
    "Actions: stand, sit, walk_forward, walk_backward, turn_left, turn_right, trot, stop\n"
    "- robot_joints(targets): Set joint positions as JSON object\n"
    "- robot_sensors(): Read all sensor data (joints, body pose, IMU, foot contacts)\n"
    "- devices_list(): List all devices in scene\n"
    "- device_state(device_id): Get device state\n\n"
    "Always call scene_load first to initialize. Use robot_sensors to observe state. "
    "Issue commands step by step and verify results."
)

IOT_SYSTEM_PROMPT = (
    "You are an AI assistant controlling IoT devices in a smart home. "
    "Available tools:\n"
    "- scene_load(scene): Initialize a room scene\n"
    "- devices_list(filter_type): List available devices\n"
    "- device_state(device_id): Get current state of a device\n"
    "- device_control(device_id, property_name, value): Set a device property\n\n"
    "Always call scene_load first. Use devices_list to discover devices, "
    "then device_control to change states. Verify changes with device_state."
)

TRAFFIC_SYSTEM_PROMPT = (
    "You are controlling a traffic simulation with vehicles and traffic lights. "
    "Available tools:\n"
    "- scene_load(scene): Initialize the traffic scenario\n"
    "- devices_list(filter_type): List vehicles and traffic lights\n"
    "- device_state(device_id): Get vehicle/traffic light state\n"
    "- device_control(device_id, property_name, value): Set speed, lane, or traffic light phase\n\n"
    "Always call scene_load first. Use devices_list to find controllable entities. "
    "Vehicle properties: speed (0-50 m/s), lane (0-3), acceleration (-5 to 5). "
    "Traffic light phases: red, yellow, green."
)


# --- Task definitions ---

ROBOT_TASKS: list[Task] = [
    Task(
        id="robot_stand_up",
        type="robot_control",
        prompt="Make the robot stand up in a stable position.",
        system_prompt=ROBOT_SYSTEM_PROMPT,
        ground_truth={
            "action_sequence": ["stand"],
            "final_action": "stand",
            "body_height_min": 0.3,
        },
        max_steps=5,
        backend="mujoco_mock",
        optimal_steps=2,  # scene_load + robot_move(stand)
    ),
    Task(
        id="robot_walk_forward_2m",
        type="robot_control",
        prompt="Make the robot walk forward approximately 2 meters.",
        system_prompt=ROBOT_SYSTEM_PROMPT,
        ground_truth={
            "action_sequence": ["stand", "walk_forward"],
            "final_position_x_min": 1.5,
            "final_position_x_max": 2.5,
        },
        max_steps=6,
        backend="mujoco_mock",
        optimal_steps=3,  # scene_load + stand + walk_forward
    ),
    Task(
        id="robot_turn_left_90",
        type="robot_control",
        prompt="Make the robot turn left approximately 90 degrees.",
        system_prompt=ROBOT_SYSTEM_PROMPT,
        ground_truth={
            "action_sequence": ["turn_left"],
            "final_yaw_min": 1.2,  # ~70 degrees in radians
            "final_yaw_max": 2.0,  # ~115 degrees in radians
        },
        max_steps=6,
        backend="mujoco_mock",
        optimal_steps=3,  # scene_load + stand + turn_left x2
    ),
    Task(
        id="robot_sit_down",
        type="robot_control",
        prompt="Make the robot sit down safely.",
        system_prompt=ROBOT_SYSTEM_PROMPT,
        ground_truth={
            "action_sequence": ["sit"],
            "final_action": "sit",
            "body_height_max": 0.2,
        },
        max_steps=5,
        backend="mujoco_mock",
        optimal_steps=2,  # scene_load + robot_move(sit)
    ),
    Task(
        id="robot_walk_and_sit",
        type="robot_control",
        prompt="Make the robot walk forward 1 meter, then sit down.",
        system_prompt=ROBOT_SYSTEM_PROMPT,
        ground_truth={
            "action_sequence": ["walk_forward", "sit"],
            "final_action": "sit",
            "final_position_x_min": 0.5,
        },
        max_steps=8,
        backend="mujoco_mock",
        optimal_steps=4,  # scene_load + stand + walk_forward + sit
    ),
]

IOT_TASKS: list[Task] = [
    Task(
        id="iot_turn_on_lamp",
        type="device_control",
        prompt="Turn on the floor lamp in the room.",
        system_prompt=IOT_SYSTEM_PROMPT,
        ground_truth={
            "device_type": "FloorLamp",
            "property": "isToggled",
            "expected_value": True,
        },
        max_steps=5,
        backend="mock",
        optimal_steps=3,  # scene_load + devices_list + device_control
    ),
    Task(
        id="iot_turn_off_tv",
        type="device_control",
        prompt="Turn off the television.",
        system_prompt=IOT_SYSTEM_PROMPT,
        ground_truth={
            "device_type": "Television",
            "property": "isToggled",
            "expected_value": False,
        },
        max_steps=5,
        backend="mock",
        optimal_steps=3,
    ),
    Task(
        id="iot_sleep_mode",
        type="multi_device",
        prompt="Put the house in sleep mode: turn off all lights and the television.",
        system_prompt=IOT_SYSTEM_PROMPT,
        ground_truth={
            "devices_off": ["FloorLamp", "DeskLamp", "Television"],
            "property": "isToggled",
            "expected_value": False,
        },
        max_steps=10,
        backend="mock",
        optimal_steps=5,  # scene_load + devices_list + 3x device_control
    ),
    Task(
        id="iot_check_temperature",
        type="device_control",
        prompt="Check if the fridge is properly closed.",
        system_prompt=IOT_SYSTEM_PROMPT,
        ground_truth={
            "device_type": "Fridge",
            "property": "isOpen",
            "expected_value": False,
            "check_only": True,
        },
        max_steps=5,
        backend="mock",
        optimal_steps=3,  # scene_load + devices_list + device_state
    ),
]

TRAFFIC_TASKS: list[Task] = [
    Task(
        id="traffic_set_speed_limit",
        type="traffic",
        prompt="Set the ego vehicle speed to 8.3 m/s (approximately 30 km/h).",
        system_prompt=TRAFFIC_SYSTEM_PROMPT,
        ground_truth={
            "device_id": "ego_vehicle",
            "property": "speed",
            "expected_value": 8.3,
            "tolerance": 0.5,
        },
        max_steps=5,
        backend="sumo_mock",
        optimal_steps=3,  # scene_load + devices_list + device_control
    ),
    Task(
        id="traffic_change_traffic_light",
        type="traffic",
        prompt="Change the north traffic light to red for safety.",
        system_prompt=TRAFFIC_SYSTEM_PROMPT,
        ground_truth={
            "device_id": "tl_north",
            "property": "phase",
            "expected_value": "red",
        },
        max_steps=5,
        backend="sumo_mock",
        optimal_steps=3,  # scene_load + devices_list + device_control
    ),
]

# Combined task registry
ALL_TASKS: dict[str, Task] = {}
for _task in ROBOT_TASKS + IOT_TASKS + TRAFFIC_TASKS:
    ALL_TASKS[_task.id] = _task


def get_tasks(task_ids: list[str] | str = "all") -> list[Task]:
    """Retrieve tasks by ID list or 'all'."""
    if task_ids == "all" or task_ids == ["all"]:
        return list(ALL_TASKS.values())
    if isinstance(task_ids, str):
        task_ids = [t.strip() for t in task_ids.split(",")]
    tasks = []
    for tid in task_ids:
        if tid not in ALL_TASKS:
            raise ValueError(f"Unknown task ID: {tid}. Available: {list(ALL_TASKS.keys())}")
        tasks.append(ALL_TASKS[tid])
    return tasks
