"""VirtualHome adapter - CPU-based home simulation using evolving_graph.

No GPU required. Supports 314 object classes, state transitions, and
multi-step task execution in a graph-based environment.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from harness.adapter import Adapter
from harness.events import EventBus
from harness.models import CDD, DeviceCapability, DeviceState, SafetyLevel

_ADAPTER_DIR = Path(__file__).parent
_SIM_DIR = _ADAPTER_DIR / "virtualhome_sim"

_SAFETY_MAP = {
    "stove": SafetyLevel.HIGH,
    "oven": SafetyLevel.HIGH,
    "toaster": SafetyLevel.MEDIUM,
    "microwave": SafetyLevel.MEDIUM,
    "fridge": SafetyLevel.MEDIUM,
    "dishwasher": SafetyLevel.MEDIUM,
    "coffeemaker": SafetyLevel.MEDIUM,
    "lightswitch": SafetyLevel.LOW,
    "tv": SafetyLevel.LOW,
    "computer": SafetyLevel.LOW,
    "faucet": SafetyLevel.MEDIUM,
    "door": SafetyLevel.MEDIUM,
    "safe": SafetyLevel.CRITICAL,
}

_DEFAULT_KITCHEN = {
    "nodes": [
        {"id": 1, "class_name": "kitchen", "category": "Rooms", "properties": [], "states": []},
        {"id": 2, "class_name": "fridge", "category": "Appliances", "properties": ["CAN_OPEN", "CONTAINERS"], "states": ["CLOSED"]},
        {"id": 3, "class_name": "microwave", "category": "Appliances", "properties": ["CAN_OPEN", "HAS_SWITCH"], "states": ["CLOSED", "OFF"]},
        {"id": 4, "class_name": "stove", "category": "Appliances", "properties": ["HAS_SWITCH", "SURFACES"], "states": ["OFF"]},
        {"id": 5, "class_name": "lightswitch", "category": "Electronics", "properties": ["HAS_SWITCH"], "states": ["OFF"]},
        {"id": 6, "class_name": "coffeepot", "category": "Appliances", "properties": ["CAN_OPEN", "GRABBABLE", "RECIPIENT"], "states": ["CLOSED"]},
        {"id": 7, "class_name": "plate", "category": "Tableware", "properties": ["GRABBABLE", "SURFACES"], "states": ["DIRTY"]},
        {"id": 8, "class_name": "apple", "category": "Food", "properties": ["GRABBABLE", "EATABLE"], "states": []},
        {"id": 9, "class_name": "mug", "category": "Tableware", "properties": ["GRABBABLE", "RECIPIENT", "CAN_OPEN"], "states": ["CLOSED"]},
        {"id": 10, "class_name": "sink", "category": "Furniture", "properties": ["HAS_SWITCH", "RECIPIENT"], "states": ["OFF"]},
        {"id": 11, "class_name": "dishwasher", "category": "Appliances", "properties": ["CAN_OPEN", "HAS_SWITCH", "CONTAINERS"], "states": ["CLOSED", "OFF"]},
        {"id": 12, "class_name": "cabinet", "category": "Furniture", "properties": ["CAN_OPEN", "CONTAINERS"], "states": ["CLOSED"]},
        {"id": 13, "class_name": "table", "category": "Furniture", "properties": ["SURFACES"], "states": []},
        {"id": 14, "class_name": "tv", "category": "Electronics", "properties": ["HAS_SWITCH"], "states": ["OFF"]},
        {"id": 15, "class_name": "toaster", "category": "Appliances", "properties": ["HAS_SWITCH"], "states": ["OFF"]},
        {"id": 100, "class_name": "character", "category": "Characters", "properties": [], "states": []},
    ],
    "edges": [
        {"from_id": i, "relation_type": "INSIDE", "to_id": 1} for i in range(2, 16)
    ] + [
        {"from_id": 100, "relation_type": "INSIDE", "to_id": 1},
        {"from_id": 8, "relation_type": "INSIDE", "to_id": 2},
        {"from_id": 7, "relation_type": "ON", "to_id": 13},
        {"from_id": 9, "relation_type": "ON", "to_id": 13},
    ] + [
        {"from_id": 100, "relation_type": "CLOSE", "to_id": i} for i in range(2, 16)
    ] + [
        {"from_id": i, "relation_type": "CLOSE", "to_id": 100} for i in range(2, 16)
    ],
}


def _load_sim_modules():
    import sys
    sim_path = str(_SIM_DIR)
    if sim_path not in sys.path:
        sys.path.insert(0, sim_path)
    from evolving_graph.environment import EnvironmentGraph
    from evolving_graph.execution import ScriptExecutor
    from evolving_graph.scripts import parse_script_line, Script
    return EnvironmentGraph, ScriptExecutor, parse_script_line, Script


class VirtualHomeAdapter(Adapter):
    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or EventBus()
        self._graph = None
        self._executor = None
        self._devices: dict[str, CDD] = {}
        self._scene: str = ""
        self._name_eq = None

    @property
    def is_initialized(self) -> bool:
        return self._graph is not None

    async def initialize(self, scene: str = "kitchen") -> dict[str, Any]:
        self._scene = scene
        EnvironmentGraph, ScriptExecutor, _, _ = _load_sim_modules()

        name_eq_path = _SIM_DIR / "class_name_equivalence.json"
        with open(name_eq_path) as f:
            self._name_eq = json.load(f)

        graph_data = _DEFAULT_KITCHEN
        self._graph = EnvironmentGraph(graph_data)
        self._executor = ScriptExecutor(self._graph, self._name_eq)

        self._devices = self._discover_devices(graph_data)
        return {
            "scene": scene,
            "device_count": len(self._devices),
            "device_types": list({d.device_type for d in self._devices.values()}),
            "engine": "virtualhome_evolving_graph",
            "gpu_required": False,
        }

    def _discover_devices(self, graph_data: dict) -> dict[str, CDD]:
        devices = {}
        for node in graph_data["nodes"]:
            if node["class_name"] == "character" or node["category"] == "Rooms":
                continue
            props = node.get("properties", [])
            caps = []
            if "HAS_SWITCH" in props:
                caps.append(DeviceCapability(
                    name="power", cap_type="enum",
                    writable=True, description="ON/OFF state (SWITCHON/SWITCHOFF)",
                ))
            if "CAN_OPEN" in props:
                caps.append(DeviceCapability(
                    name="open", cap_type="boolean",
                    writable=True, description="OPEN/CLOSED state",
                ))
            if "GRABBABLE" in props:
                caps.append(DeviceCapability(
                    name="grabbable", cap_type="boolean",
                    writable=False, readable=True, description="Can be picked up",
                ))
            if not caps:
                continue

            device_id = f"{node['class_name']}_{node['id']}"
            safety = _SAFETY_MAP.get(node["class_name"], SafetyLevel.LOW)
            devices[device_id] = CDD(
                device_id=device_id,
                device_type=node["class_name"],
                display_name=node["class_name"],
                location=self._scene,
                capabilities=caps,
                safety_class=safety,
                metadata={"node_id": node["id"], "states": node.get("states", [])},
            )
        return devices

    async def list_devices(self) -> list[CDD]:
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        cdd = self._devices.get(device_id)
        if not cdd:
            raise ValueError(f"Device not found: {device_id}")

        node_id = cdd.metadata["node_id"]
        try:
            graph_dict = self._graph.to_dict()
        except Exception:
            graph_dict = _DEFAULT_KITCHEN
        node = next((n for n in graph_dict["nodes"] if n["id"] == node_id), None)

        props = {}
        if node:
            states = node.get("states", [])
            props["states"] = states
            props["power"] = "ON" if "ON" in states else "OFF" if "OFF" in states else "unknown"
            props["open"] = "OPEN" in states
        return DeviceState(device_id=device_id, properties=props, timestamp=time.time())

    async def set_property(self, device_id: str, property_name: str, value: Any) -> DeviceState:
        cdd = self._devices.get(device_id)
        if not cdd:
            raise ValueError(f"Device not found: {device_id}")

        node_id = cdd.metadata["node_id"]
        _, ScriptExecutor, parse_script_line, Script = _load_sim_modules()

        if property_name == "power":
            action = "SWITCHON" if value in (True, "on", "ON") else "SWITCHOFF"
        elif property_name == "open":
            action = "OPEN" if value in (True, "on", "open") else "CLOSE"
        else:
            raise ValueError(f"Unknown property: {property_name}")

        script_line = f"[{action}] <{cdd.device_type}> ({node_id})"
        parsed = parse_script_line(script_line, 0)
        if not parsed:
            raise ValueError(f"Failed to parse action: {script_line}")

        script = Script([parsed])
        success, final_state, _ = self._executor.execute(script)

        if not success:
            raise RuntimeError(f"Action failed: {script_line}")

        if final_state:
            from evolving_graph.environment import EnvironmentGraph
            self._graph = EnvironmentGraph(final_state.to_dict())
            self._executor = ScriptExecutor(self._graph, self._name_eq)

        await self._event_bus.emit("state_changed", {
            "device_id": device_id,
            "action": script_line,
            "success": success,
            "timestamp": time.time(),
        })

        return await self.get_device_state(device_id)

    async def invoke_action(self, device_id: str, action: str, params: dict | None = None) -> dict[str, Any]:
        cdd = self._devices.get(device_id)
        if not cdd:
            return {"success": False, "error": f"Device not found: {device_id}"}

        node_id = cdd.metadata["node_id"]
        _, ScriptExecutor, parse_script_line, Script = _load_sim_modules()

        script_line = f"[{action.upper()}] <{cdd.device_type}> ({node_id})"
        parsed = parse_script_line(script_line, 0)
        if not parsed:
            return {"success": False, "error": f"Invalid action: {script_line}"}

        script = Script([parsed])
        success, final_state, _ = self._executor.execute(script)

        if success and final_state:
            from evolving_graph.environment import EnvironmentGraph
            self._graph = EnvironmentGraph(final_state.to_dict())
            self._executor = ScriptExecutor(self._graph, self._name_eq)

        return {"success": success, "action": script_line}

    async def capture_image(self) -> str:
        import base64, io
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (800, 600), color=(30, 30, 40))
        draw = ImageDraw.Draw(img)
        draw.text((20, 15), f"VirtualHome: {self._scene} (CPU mode)", fill=(255, 255, 255))
        y = 55
        for did, cdd in list(self._devices.items())[:14]:
            state = await self.get_device_state(did)
            states = state.properties.get("states", [])
            color = (0, 220, 0) if "ON" in states or "OPEN" in states else (150, 150, 150)
            draw.text((20, y), f"[{cdd.safety_class.value:8s}] {cdd.device_type:15s} | {states}", fill=color)
            y += 35
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
