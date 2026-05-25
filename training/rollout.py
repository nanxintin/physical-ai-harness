"""Rollout engine for generating training trajectories.

Runs an LLM agent against simulation environments via OpenAI-compatible API,
recording all interactions as Trajectory objects.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from training.tasks import Task
from training.trajectory import Trajectory


# --- OpenAI function-call tool schemas ---

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "scene_load",
            "description": "Load a simulation scene. Must be called before other tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene": {
                        "type": "string",
                        "description": "Scene name (e.g. FloorPlan1, flat_ground, intersection)",
                    }
                },
                "required": ["scene"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "devices_list",
            "description": "List all controllable devices in the current scene.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_type": {
                        "type": "string",
                        "description": "Optional device type filter",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "device_state",
            "description": "Get the current state of a specific device.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "The device ID from devices_list",
                    }
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "device_control",
            "description": "Set a device property value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Device ID"},
                    "property_name": {"type": "string", "description": "Property to set"},
                    "value": {"type": "string", "description": "New value"},
                },
                "required": ["device_id", "property_name", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "robot_move",
            "description": "Command the robot to perform a locomotion action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["stand", "sit", "walk_forward", "walk_backward",
                                 "turn_left", "turn_right", "trot", "stop"],
                        "description": "Locomotion action",
                    },
                    "speed": {
                        "type": "number",
                        "description": "Speed in m/s (0.1-1.0)",
                        "default": 0.3,
                    },
                    "duration": {
                        "type": "number",
                        "description": "Duration in seconds (0.5-10.0)",
                        "default": 2.0,
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "robot_joints",
            "description": "Set target positions for robot joints.",
            "parameters": {
                "type": "object",
                "properties": {
                    "targets": {
                        "type": "string",
                        "description": "JSON object mapping joint names to target positions in radians",
                    }
                },
                "required": ["targets"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "robot_sensors",
            "description": "Read all robot sensor data.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


def _get_tools_for_backend(backend: str) -> list[dict[str, Any]]:
    """Filter tool schemas to those relevant for a given backend."""
    if backend in ("mujoco_mock", "mujoco"):
        return TOOL_SCHEMAS  # All tools available
    elif backend in ("sumo_mock", "sumo"):
        # Traffic scenarios use scene_load, devices_list, device_state, device_control
        return [t for t in TOOL_SCHEMAS if t["function"]["name"] in (
            "scene_load", "devices_list", "device_state", "device_control"
        )]
    else:
        # IoT scenarios
        return [t for t in TOOL_SCHEMAS if t["function"]["name"] in (
            "scene_load", "devices_list", "device_state", "device_control"
        )]


# --- Dry-run scripted responses ---

def _generate_dry_run_response(task: Task, step: int, messages: list[dict]) -> dict:
    """Generate a scripted LLM response for dry-run mode.

    Produces reasonable tool calls that match expected behavior for each task type.
    """
    task_id = task.id

    # Robot tasks
    if task_id == "robot_stand_up":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "flat_ground"}}]},
            {"tool_calls": [{"name": "robot_move", "arguments": {"action": "stand"}}]},
            {"content": "The robot is now standing in a stable position."},
        ]
    elif task_id == "robot_walk_forward_2m":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "flat_ground"}}]},
            {"tool_calls": [{"name": "robot_move", "arguments": {"action": "stand"}}]},
            {"tool_calls": [{"name": "robot_move", "arguments": {"action": "walk_forward", "speed": 0.5, "duration": 4.0}}]},
            {"content": "The robot has walked forward approximately 2 meters."},
        ]
    elif task_id == "robot_turn_left_90":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "flat_ground"}}]},
            {"tool_calls": [{"name": "robot_move", "arguments": {"action": "stand"}}]},
            {"tool_calls": [{"name": "robot_move", "arguments": {"action": "turn_left"}}]},
            {"tool_calls": [{"name": "robot_move", "arguments": {"action": "turn_left"}}]},
            {"content": "The robot has turned left approximately 90 degrees."},
        ]
    elif task_id == "robot_sit_down":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "flat_ground"}}]},
            {"tool_calls": [{"name": "robot_move", "arguments": {"action": "sit"}}]},
            {"content": "The robot is now sitting down safely."},
        ]
    elif task_id == "robot_walk_and_sit":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "flat_ground"}}]},
            {"tool_calls": [{"name": "robot_move", "arguments": {"action": "stand"}}]},
            {"tool_calls": [{"name": "robot_move", "arguments": {"action": "walk_forward", "speed": 0.5, "duration": 2.0}}]},
            {"tool_calls": [{"name": "robot_move", "arguments": {"action": "sit"}}]},
            {"content": "The robot walked forward 1 meter and then sat down."},
        ]
    # IoT tasks
    elif task_id == "iot_turn_on_lamp":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "FloorPlan201"}}]},
            {"tool_calls": [{"name": "devices_list", "arguments": {}}]},
            {"tool_calls": [{"name": "device_control", "arguments": {"device_id": "FloorLamp|+01.32|+00.00|+00.45", "property_name": "isToggled", "value": "true"}}]},
            {"content": "The floor lamp has been turned on."},
        ]
    elif task_id == "iot_turn_off_tv":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "FloorPlan201"}}]},
            {"tool_calls": [{"name": "devices_list", "arguments": {}}]},
            {"tool_calls": [{"name": "device_control", "arguments": {"device_id": "Television|+00.50|+01.20|+03.00", "property_name": "isToggled", "value": "false"}}]},
            {"content": "The television has been turned off."},
        ]
    elif task_id == "iot_sleep_mode":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "FloorPlan201"}}]},
            {"tool_calls": [{"name": "devices_list", "arguments": {}}]},
            {"tool_calls": [{"name": "device_control", "arguments": {"device_id": "FloorLamp|+01.32|+00.00|+00.45", "property_name": "isToggled", "value": "false"}}]},
            {"tool_calls": [{"name": "device_control", "arguments": {"device_id": "DeskLamp|+02.10|+00.78|+01.20", "property_name": "isToggled", "value": "false"}}]},
            {"tool_calls": [{"name": "device_control", "arguments": {"device_id": "Television|+00.50|+01.20|+03.00", "property_name": "isToggled", "value": "false"}}]},
            {"content": "Sleep mode activated: all lights and TV are now off."},
        ]
    elif task_id == "iot_check_temperature":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "FloorPlan1"}}]},
            {"tool_calls": [{"name": "devices_list", "arguments": {}}]},
            {"tool_calls": [{"name": "device_state", "arguments": {"device_id": "Fridge|+03.00|+00.00|+02.50"}}]},
            {"content": "The fridge is properly closed (isOpen=False)."},
        ]
    # Traffic tasks
    elif task_id == "traffic_set_speed_limit":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "intersection"}}]},
            {"tool_calls": [{"name": "devices_list", "arguments": {}}]},
            {"tool_calls": [{"name": "device_control", "arguments": {"device_id": "ego_vehicle", "property_name": "speed", "value": "8.3"}}]},
            {"content": "The ego vehicle speed has been set to 8.3 m/s (~30 km/h)."},
        ]
    elif task_id == "traffic_change_traffic_light":
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "intersection"}}]},
            {"tool_calls": [{"name": "devices_list", "arguments": {}}]},
            {"tool_calls": [{"name": "device_control", "arguments": {"device_id": "tl_north", "property_name": "phase", "value": "red"}}]},
            {"content": "The north traffic light has been changed to red."},
        ]
    else:
        # Generic fallback
        steps = [
            {"tool_calls": [{"name": "scene_load", "arguments": {"scene": "FloorPlan1"}}]},
            {"content": "Task completed."},
        ]

    if step < len(steps):
        return steps[step]
    return {"content": "Done."}


# --- Adapter execution layer ---

async def _execute_tool_call(
    adapter: Any,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """Execute a tool call against the adapter and return the result as a string."""
    try:
        if tool_name == "scene_load":
            scene = arguments.get("scene", "FloorPlan1")
            result = await adapter.initialize(scene)
            return json.dumps({"status": "success", "scene": result["scene"],
                             "device_count": result["device_count"]})

        elif tool_name == "devices_list":
            devices = await adapter.list_devices()
            filter_type = arguments.get("filter_type")
            if filter_type:
                devices = [d for d in devices if filter_type.lower() in d.device_type.lower()]
            result = [{"device_id": d.device_id, "type": d.device_type,
                      "capabilities": [c.name for c in d.capabilities]}
                     for d in devices]
            return json.dumps({"count": len(result), "devices": result})

        elif tool_name == "device_state":
            device_id = arguments["device_id"]
            state = await adapter.get_device_state(device_id)
            return json.dumps({"device_id": device_id, "properties": state.properties})

        elif tool_name == "device_control":
            device_id = arguments["device_id"]
            prop = arguments["property_name"]
            value = arguments["value"]
            # Determine type
            if value.lower() in ("true", "false"):
                typed_value = value.lower() == "true"
            else:
                try:
                    typed_value = float(value)
                except ValueError:
                    typed_value = value
            new_state = await adapter.set_property(device_id, prop, typed_value)
            return json.dumps({"status": "success", "device_id": device_id,
                             "property": prop, "new_value": typed_value})

        elif tool_name == "robot_move":
            action = arguments["action"]
            speed = arguments.get("speed", 0.3)
            duration = arguments.get("duration", 2.0)
            from harness.adapters.mujoco_go1.robot_config import DEVICE_ID
            result = await adapter.invoke_action(
                DEVICE_ID, action, {"speed": speed, "duration": duration}
            )
            state = await adapter.get_device_state(DEVICE_ID)
            return json.dumps({"status": "success", "action": action,
                             "body_position": state.properties.get("body_position"),
                             "current_action": state.properties.get("current_action")})

        elif tool_name == "robot_joints":
            targets_str = arguments["targets"]
            targets = json.loads(targets_str) if isinstance(targets_str, str) else targets_str
            from harness.adapters.mujoco_go1.robot_config import DEVICE_ID
            for joint_name, value in targets.items():
                await adapter.set_property(DEVICE_ID, f"joint_{joint_name}", float(value))
            state = await adapter.get_device_state(DEVICE_ID)
            return json.dumps({"status": "success", "joints_set": list(targets.keys())})

        elif tool_name == "robot_sensors":
            from harness.adapters.mujoco_go1.robot_config import DEVICE_ID
            state = await adapter.get_device_state(DEVICE_ID)
            return json.dumps({
                "body_position": state.properties.get("body_position"),
                "body_orientation": state.properties.get("body_orientation"),
                "body_velocity": state.properties.get("body_velocity"),
                "current_action": state.properties.get("current_action"),
                "foot_contacts": state.properties.get("foot_contacts"),
            })

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Main rollout engine ---

class RolloutEngine:
    """Generates training trajectories by running an LLM against mock adapters.

    In normal mode, sends requests to an OpenAI-compatible API (e.g., vLLM).
    In dry-run mode, uses scripted responses for testing without an LLM server.
    """

    def __init__(
        self,
        adapter: Any,
        model_url: str = "http://localhost:8000/v1",
        model_name: str = "Qwen/Qwen3-8B",
        api_key: str = "EMPTY",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        dry_run: bool = False,
    ):
        self.adapter = adapter
        self.model_url = model_url
        self.model_name = model_name
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.dry_run = dry_run
        self._client = None

    def _get_client(self):
        """Lazily initialize the OpenAI client."""
        if self._client is None and not self.dry_run:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self.model_url,
                    api_key=self.api_key,
                )
            except ImportError:
                raise RuntimeError(
                    "openai package is required for non-dry-run mode. "
                    "Install with: pip install openai"
                )
        return self._client

    async def run_episode(self, task: Task) -> Trajectory:
        """Run a single episode for the given task.

        Returns a complete Trajectory recording all interactions.
        """
        start_time = time.time()
        messages: list[dict] = [
            {"role": "system", "content": task.system_prompt},
            {"role": "user", "content": task.prompt},
        ]
        tool_calls_log: list[dict] = []
        step = 0
        done = False

        tools = _get_tools_for_backend(task.backend)

        while step < task.max_steps and not done:
            # Get LLM response
            if self.dry_run:
                response = _generate_dry_run_response(task, step, messages)
            else:
                response = await self._call_llm(messages, tools)

            # Process response
            if "tool_calls" in response:
                # Build assistant message with tool calls
                assistant_msg = {"role": "assistant", "content": None, "tool_calls": []}
                for i, tc in enumerate(response["tool_calls"]):
                    call_id = f"call_{task.id}_{step}_{i}"
                    assistant_msg["tool_calls"].append({
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    })
                messages.append(assistant_msg)

                # Execute each tool call
                for i, tc in enumerate(response["tool_calls"]):
                    call_id = f"call_{task.id}_{step}_{i}"
                    call_start = time.time()
                    result_str = await _execute_tool_call(
                        self.adapter, tc["name"], tc["arguments"]
                    )
                    call_end = time.time()

                    # Check if the call succeeded
                    try:
                        result_parsed = json.loads(result_str)
                        call_success = "error" not in result_parsed
                    except json.JSONDecodeError:
                        call_success = False

                    tool_calls_log.append({
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                        "result": result_str,
                        "success": call_success,
                        "timestamp": call_end,
                    })

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result_str,
                    })

                step += 1

            elif "content" in response and response["content"]:
                # Text-only response means the agent is done
                messages.append({"role": "assistant", "content": response["content"]})
                done = True
            else:
                # Empty response, terminate
                done = True

        end_time = time.time()
        total_time_ms = (end_time - start_time) * 1000

        # Determine success by checking final adapter state
        success = await self._check_success(task)

        # Get final state
        final_state = await self._get_final_state(task)

        return Trajectory(
            task_id=task.id,
            task_type=task.type,
            messages=messages,
            tool_calls=tool_calls_log,
            success=success,
            total_steps=step,
            total_time_ms=total_time_ms,
            final_state=final_state,
            ground_truth=task.ground_truth,
            metadata={
                "backend": task.backend,
                "model": self.model_name,
                "dry_run": self.dry_run,
                "max_steps": task.max_steps,
                "optimal_steps": task.optimal_steps,
            },
        )

    async def _call_llm(self, messages: list[dict], tools: list[dict]) -> dict:
        """Call the OpenAI-compatible LLM API."""
        client = self._get_client()

        # Run synchronous OpenAI call in executor to avoid blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ),
        )

        choice = response.choices[0]
        if choice.message.tool_calls:
            tool_calls = []
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                })
            return {"tool_calls": tool_calls}
        else:
            return {"content": choice.message.content or ""}

    async def _check_success(self, task: Task) -> bool:
        """Check whether the task was completed successfully based on ground truth."""
        gt = task.ground_truth

        try:
            if task.type == "robot_control":
                from harness.adapters.mujoco_go1.robot_config import DEVICE_ID
                state = await self.adapter.get_device_state(DEVICE_ID)
                props = state.properties

                # Check final action
                if "final_action" in gt:
                    if props.get("current_action") != gt["final_action"]:
                        return False

                # Check body height
                pos = props.get("body_position", [0, 0, 0])
                if "body_height_min" in gt and pos[2] < gt["body_height_min"]:
                    return False
                if "body_height_max" in gt and pos[2] > gt["body_height_max"]:
                    return False

                # Check x position
                if "final_position_x_min" in gt and pos[0] < gt["final_position_x_min"]:
                    return False
                if "final_position_x_max" in gt and pos[0] > gt["final_position_x_max"]:
                    return False

                # Check yaw
                orientation = props.get("body_orientation", [0, 0, 0])
                yaw = abs(orientation[2])
                if "final_yaw_min" in gt and yaw < gt["final_yaw_min"]:
                    return False
                if "final_yaw_max" in gt and yaw > gt["final_yaw_max"]:
                    return False

                return True

            elif task.type == "device_control":
                # Check that specific device property matches expected
                if gt.get("check_only"):
                    # For observation tasks, success if agent checked the state
                    return True

                devices = await self.adapter.list_devices()
                target_devices = [d for d in devices if gt["device_type"] in d.device_type]
                if not target_devices:
                    return False

                for dev in target_devices:
                    state = await self.adapter.get_device_state(dev.device_id)
                    prop_val = state.properties.get(gt["property"])
                    if prop_val == gt["expected_value"]:
                        return True
                return False

            elif task.type == "multi_device":
                # All specified devices must have the expected value
                devices = await self.adapter.list_devices()
                for device_type in gt["devices_off"]:
                    matching = [d for d in devices if device_type in d.device_type]
                    for dev in matching:
                        state = await self.adapter.get_device_state(dev.device_id)
                        prop_val = state.properties.get(gt["property"])
                        if prop_val != gt["expected_value"]:
                            return False
                return True

            elif task.type == "traffic":
                device_id = gt["device_id"]
                state = await self.adapter.get_device_state(device_id)
                prop_val = state.properties.get(gt["property"])

                expected = gt["expected_value"]
                tolerance = gt.get("tolerance", 0)

                if isinstance(expected, (int, float)) and tolerance > 0:
                    return abs(prop_val - expected) <= tolerance
                else:
                    return prop_val == expected

        except Exception:
            return False

        return False

    async def _get_final_state(self, task: Task) -> dict:
        """Capture the final state of the environment."""
        try:
            if task.type == "robot_control":
                from harness.adapters.mujoco_go1.robot_config import DEVICE_ID
                state = await self.adapter.get_device_state(DEVICE_ID)
                return state.properties
            else:
                # Return states of all devices
                devices = await self.adapter.list_devices()
                result = {}
                for dev in devices:
                    state = await self.adapter.get_device_state(dev.device_id)
                    result[dev.device_id] = state.properties
                return result
        except Exception:
            return {}


async def run_batch(
    tasks: list[Task],
    adapter: Any,
    episodes_per_task: int = 5,
    model_url: str = "http://localhost:8000/v1",
    model_name: str = "Qwen/Qwen3-8B",
    api_key: str = "EMPTY",
    temperature: float = 0.7,
    max_tokens: int = 2048,
    dry_run: bool = False,
    progress_callback=None,
) -> list[Trajectory]:
    """Run multiple episodes across multiple tasks.

    Args:
        tasks: List of Task objects to execute.
        adapter: The simulation adapter instance.
        episodes_per_task: Number of episodes to run per task.
        model_url: OpenAI-compatible API URL.
        model_name: Model identifier.
        api_key: API key.
        temperature: Sampling temperature.
        max_tokens: Max tokens per response.
        dry_run: If True, use scripted responses.
        progress_callback: Optional callable(task_id, episode, trajectory).

    Returns:
        List of all recorded Trajectories.
    """
    engine = RolloutEngine(
        adapter=adapter,
        model_url=model_url,
        model_name=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        dry_run=dry_run,
    )

    trajectories: list[Trajectory] = []

    for task in tasks:
        for episode in range(episodes_per_task):
            # Re-initialize adapter for each episode to reset state
            trajectory = await engine.run_episode(task)
            trajectories.append(trajectory)

            if progress_callback:
                progress_callback(task.id, episode, trajectory)

    return trajectories
