"""SUMO adapter using TraCI for traffic simulation."""

from __future__ import annotations

import asyncio
import base64
import io
import os
import time
from pathlib import Path
from typing import Any

import sumolib
import traci
from PIL import Image

from harness.adapter import Adapter
from harness.adapters.sumo.config import (
    DEFAULT_PORT,
    SCENES,
    STEP_LENGTH,
    SUMO_BINARY,
    TRAFFIC_LIGHT_ACTIONS,
    TRAFFIC_LIGHT_PHASES,
    TRAFFIC_LIGHT_SAFETY_CLASS,
    VEHICLE_ACTIONS,
    VEHICLE_PROPERTIES,
    VEHICLE_SAFETY_CLASS,
)
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel

_CONFIG_DIR = Path(__file__).parent / "scenarios"


class SUMOAdapter(Adapter):
    """Adapter bridging Harness capabilities to SUMO traffic simulation via TraCI."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        sumo_binary: str | None = None,
        port: int = DEFAULT_PORT,
        gui: bool = False,
    ):
        self._event_bus = event_bus or EventBus()
        self._sumo_binary = sumo_binary or (SUMO_BINARY if not gui else "sumo-gui")
        self._port = port
        self._devices: dict[str, CDD] = {}
        self._scene = ""
        self._running = False
        self._sim_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._connection_label = "harness"

    @property
    def is_initialized(self) -> bool:
        return self._running

    async def initialize(self, scene: str = "intersection") -> dict[str, Any]:
        self._scene = scene
        scene_info = SCENES.get(scene, SCENES["intersection"])
        config_path = str(_CONFIG_DIR / scene_info["config_file"])

        sumo_cmd = [
            self._sumo_binary,
            "-c", config_path,
            "--step-length", str(STEP_LENGTH),
            "--no-warnings", "true",
        ]

        # Start SUMO in a thread to avoid blocking
        await asyncio.to_thread(traci.start, sumo_cmd, label=self._connection_label)
        self._running = True

        # Discover devices
        self._devices = {}
        await self._discover_devices()

        # Start simulation step loop
        self._sim_task = asyncio.create_task(self._simulation_loop())

        return {
            "scene": scene,
            "device_count": len(self._devices),
            "device_types": list({cdd.device_type for cdd in self._devices.values()}),
            "engine": "sumo",
            "step_length": STEP_LENGTH,
        }

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")

        cdd = self._devices[device_id]
        async with self._lock:
            if cdd.device_type == "vehicle":
                props = await asyncio.to_thread(self._read_vehicle_state, device_id)
            else:
                props = await asyncio.to_thread(self._read_traffic_light_state, device_id)

        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")

        cdd = self._devices[device_id]

        async with self._lock:
            if cdd.device_type == "vehicle":
                await asyncio.to_thread(self._set_vehicle_property, device_id, property_name, value)
            elif cdd.device_type == "traffic_light":
                await asyncio.to_thread(self._set_traffic_light_property, device_id, property_name, value)

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "property": property_name,
            "value": value,
        })
        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        if device_id not in self._devices:
            raise ValueError(f"Device not found: {device_id}")

        params = params or {}
        cdd = self._devices[device_id]

        async with self._lock:
            if cdd.device_type == "vehicle":
                if action not in VEHICLE_ACTIONS:
                    raise ValueError(f"Unknown vehicle action: {action}")
                await asyncio.to_thread(self._execute_vehicle_action, device_id, action, params)
            elif cdd.device_type == "traffic_light":
                if action not in TRAFFIC_LIGHT_ACTIONS:
                    raise ValueError(f"Unknown traffic light action: {action}")
                await asyncio.to_thread(self._execute_traffic_light_action, device_id, action, params)

        await self._event_bus.emit("action_executed", {
            "device_id": device_id,
            "action": action,
            "params": params,
        })
        return {"success": True, "action": action, "params": params}

    async def capture_image(self) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._render_screenshot)

    async def shutdown(self):
        """Cleanly shut down the SUMO simulation."""
        self._running = False
        if self._sim_task:
            self._sim_task.cancel()
            try:
                await self._sim_task
            except asyncio.CancelledError:
                pass
        try:
            await asyncio.to_thread(traci.close)
        except Exception:
            pass

    # --- Private: simulation loop ---

    async def _simulation_loop(self):
        """Advance simulation one step at a time."""
        while self._running:
            async with self._lock:
                await asyncio.to_thread(traci.simulationStep)
                # Re-discover devices (vehicles may appear/disappear)
                await asyncio.to_thread(self._refresh_vehicle_list)
            await asyncio.sleep(STEP_LENGTH)

    # --- Private: device discovery ---

    async def _discover_devices(self):
        """Discover all vehicles and traffic lights currently in simulation."""
        vehicle_ids = await asyncio.to_thread(traci.vehicle.getIDList)
        for vid in vehicle_ids:
            self._devices[vid] = self._build_vehicle_cdd(vid)

        tl_ids = await asyncio.to_thread(traci.trafficlight.getIDList)
        for tl_id in tl_ids:
            self._devices[tl_id] = self._build_traffic_light_cdd(tl_id)

    def _refresh_vehicle_list(self):
        """Update vehicle device list (vehicles can enter/leave simulation)."""
        current_vehicles = set(traci.vehicle.getIDList())
        existing_vehicles = {did for did, cdd in self._devices.items() if cdd.device_type == "vehicle"}

        # Add new vehicles
        for vid in current_vehicles - existing_vehicles:
            self._devices[vid] = self._build_vehicle_cdd(vid)

        # Remove departed vehicles
        for vid in existing_vehicles - current_vehicles:
            del self._devices[vid]

    # --- Private: state reading ---

    def _read_vehicle_state(self, vehicle_id: str) -> dict[str, Any]:
        pos = traci.vehicle.getPosition(vehicle_id)
        return {
            "position": [pos[0], pos[1]],
            "speed": traci.vehicle.getSpeed(vehicle_id),
            "heading": traci.vehicle.getAngle(vehicle_id),
            "lane": traci.vehicle.getLaneIndex(vehicle_id),
            "acceleration": traci.vehicle.getAcceleration(vehicle_id),
            "road_id": traci.vehicle.getRoadID(vehicle_id),
        }

    def _read_traffic_light_state(self, tl_id: str) -> dict[str, Any]:
        phase_index = traci.trafficlight.getPhase(tl_id)
        program = traci.trafficlight.getAllProgramLogics(tl_id)
        current_state = traci.trafficlight.getRedYellowGreenState(tl_id)
        return {
            "phase": current_state,
            "phase_index": phase_index,
            "program_id": traci.trafficlight.getProgram(tl_id),
        }

    # --- Private: property setting ---

    def _set_vehicle_property(self, vehicle_id: str, property_name: str, value: Any):
        if property_name == "speed":
            fval = float(value)
            if not (0.0 <= fval <= 50.0):
                raise ValueError(f"Speed {fval} out of range [0.0, 50.0]")
            traci.vehicle.setSpeed(vehicle_id, fval)
        elif property_name == "lane":
            ival = int(value)
            traci.vehicle.changeLane(vehicle_id, ival, duration=5.0)
        elif property_name == "acceleration":
            fval = float(value)
            traci.vehicle.setAcceleration(vehicle_id, fval, duration=2.0)
        else:
            raise ValueError(f"Cannot set vehicle property: {property_name}")

    def _set_traffic_light_property(self, tl_id: str, property_name: str, value: Any):
        if property_name == "phase":
            # Set the phase using the raw state string or index
            if isinstance(value, int):
                traci.trafficlight.setPhase(tl_id, value)
            else:
                # Map phase name to traci state
                phase_map = {"red": "r", "yellow": "y", "green": "G"}
                state = phase_map.get(value, "r")
                # Get current state length and set all to this phase
                current = traci.trafficlight.getRedYellowGreenState(tl_id)
                traci.trafficlight.setRedYellowGreenState(tl_id, state * len(current))
        else:
            raise ValueError(f"Cannot set traffic light property: {property_name}")

    # --- Private: actions ---

    def _execute_vehicle_action(self, vehicle_id: str, action: str, params: dict):
        if action == "change_lane":
            direction = params.get("direction", "right")
            current_lane = traci.vehicle.getLaneIndex(vehicle_id)
            target = current_lane + (1 if direction == "left" else -1)
            target = max(0, target)
            traci.vehicle.changeLane(vehicle_id, target, duration=3.0)
        elif action == "emergency_stop":
            traci.vehicle.setSpeed(vehicle_id, 0.0)
            traci.vehicle.setAcceleration(vehicle_id, -9.0, duration=1.0)
        elif action == "set_route":
            edges = params.get("edges", [])
            if edges:
                traci.vehicle.setRoute(vehicle_id, edges)

    def _execute_traffic_light_action(self, tl_id: str, action: str, params: dict):
        if action == "next_phase":
            current_phase = traci.trafficlight.getPhase(tl_id)
            program = traci.trafficlight.getAllProgramLogics(tl_id)
            if program:
                num_phases = len(program[0].phases)
                next_phase = (current_phase + 1) % num_phases
                traci.trafficlight.setPhase(tl_id, next_phase)
        elif action == "set_phase":
            phase = params.get("phase", "red")
            phase_map = {"red": "r", "yellow": "y", "green": "G"}
            state = phase_map.get(phase, "r")
            current = traci.trafficlight.getRedYellowGreenState(tl_id)
            traci.trafficlight.setRedYellowGreenState(tl_id, state * len(current))

    # --- Private: rendering ---

    def _render_screenshot(self) -> str:
        """Capture screenshot via traci GUI or generate a placeholder."""
        try:
            # Try GUI screenshot if available
            screenshot_path = "/tmp/sumo_screenshot.png"
            traci.gui.screenshot("View #0", screenshot_path)
            with open(screenshot_path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except (traci.TraCIException, Exception):
            # Fallback: generate simple representation
            img = Image.new("RGB", (640, 480), color=(80, 80, 80))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()

    # --- Private: CDD builders ---

    def _build_vehicle_cdd(self, vehicle_id: str) -> CDD:
        capabilities = []
        for prop_name, prop_info in VEHICLE_PROPERTIES.items():
            capabilities.append(DeviceCapability(
                name=prop_name,
                cap_type="float",
                readable=True,
                writable=True,
                safety_level=SafetyLevel.HIGH,
                value_range={"min": prop_info["min"], "max": prop_info["max"]},
                description=f"Vehicle {prop_name} ({prop_info.get('unit', '')})",
            ))
        for name, desc in [
            ("position", "Vehicle position [x, y] in meters"),
            ("heading", "Vehicle heading in degrees"),
            ("road_id", "Current road/edge ID"),
        ]:
            capabilities.append(DeviceCapability(
                name=name,
                cap_type="float" if name != "road_id" else "enum",
                readable=True,
                writable=False,
                safety_level=SafetyLevel.LOW,
                description=desc,
            ))
        for action_name, action_info in VEHICLE_ACTIONS.items():
            capabilities.append(DeviceCapability(
                name=action_name,
                cap_type="action",
                readable=False,
                writable=True,
                safety_level=action_info["safety"],
                description=action_info["description"],
            ))
        return CDD(
            device_id=vehicle_id,
            device_type="vehicle",
            display_name=vehicle_id.replace("_", " ").title(),
            location="simulation",
            capabilities=capabilities,
            safety_class=VEHICLE_SAFETY_CLASS,
            metadata={"engine": "sumo"},
        )

    def _build_traffic_light_cdd(self, tl_id: str) -> CDD:
        capabilities = [
            DeviceCapability(
                name="phase",
                cap_type="enum",
                readable=True,
                writable=True,
                safety_level=SafetyLevel.CRITICAL,
                value_range={"values": TRAFFIC_LIGHT_PHASES},
                description="Current traffic light phase",
            ),
            DeviceCapability(
                name="phase_index",
                cap_type="float",
                readable=True,
                writable=False,
                safety_level=SafetyLevel.LOW,
                description="Index of current phase in cycle",
            ),
        ]
        for action_name, action_info in TRAFFIC_LIGHT_ACTIONS.items():
            capabilities.append(DeviceCapability(
                name=action_name,
                cap_type="action",
                readable=False,
                writable=True,
                safety_level=action_info["safety"],
                description=action_info["description"],
            ))
        return CDD(
            device_id=tl_id,
            device_type="traffic_light",
            display_name=tl_id.replace("_", " ").title(),
            location="simulation",
            capabilities=capabilities,
            safety_class=TRAFFIC_LIGHT_SAFETY_CLASS,
            metadata={"engine": "sumo"},
        )
