"""Physical AI Harness MCP Server.

Exposes AI2-THOR simulated device control as MCP tools.
Run as: python -m harness.mcp_server
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

import os

from harness.events import EventBus
from harness.models import SafetyLevel
from harness.safety import SafetySandbox

event_bus = EventBus()
sandbox = SafetySandbox(max_allowed=SafetyLevel.HIGH)

_BACKEND = os.environ.get("HARNESS_BACKEND", "mock").lower()

if _BACKEND == "virtualhome":
    from harness.adapters.virtualhome_adapter import VirtualHomeAdapter
    adapter = VirtualHomeAdapter(event_bus=event_bus)
elif _BACKEND in ("mock", "1", "true", "yes") or os.environ.get("HARNESS_MOCK", "").lower() in ("1", "true", "yes"):
    from harness.adapters.mock_adapter import MockAdapter
    adapter = MockAdapter(event_bus=event_bus)
else:
    from harness.adapters.ai2thor_adapter import AI2ThorAdapter
    adapter = AI2ThorAdapter(event_bus=event_bus)

mcp = FastMCP(
    "harness",
    instructions=(
        "Physical AI Harness - control simulated IoT devices in a home environment. "
        "Use scene_load first to initialize a scene, then use other tools to "
        "query and control devices. Available scenes: FloorPlan1-FloorPlan30 (kitchens), "
        "FloorPlan201-FloorPlan230 (living rooms), FloorPlan301-FloorPlan330 (bedrooms), "
        "FloorPlan401-FloorPlan430 (bathrooms)."
    ),
)


@mcp.tool()
async def scene_load(scene: str = "FloorPlan1") -> str:
    """Load an AI2-THOR scene. Must be called before other tools.

    Args:
        scene: Scene name (e.g. FloorPlan1 for kitchen, FloorPlan201 for living room)
    """
    try:
        result = await adapter.initialize(scene)
        return json.dumps({
            "status": "success",
            "scene": result["scene"],
            "device_count": result["device_count"],
            "device_types": result["device_types"],
            "message": f"Loaded {scene} with {result['device_count']} controllable devices",
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
async def devices_list(filter_type: Optional[str] = None) -> str:
    """List all controllable devices in the current scene with their capabilities.

    Args:
        filter_type: Optional device type filter (e.g. "FloorLamp", "Fridge", "Television")
    """
    if not adapter.is_initialized:
        return json.dumps({"error": "Scene not loaded. Call scene_load first."})

    devices = await adapter.list_devices()
    if filter_type:
        devices = [d for d in devices if filter_type.lower() in d.device_type.lower()]

    result = []
    for d in devices:
        result.append({
            "device_id": d.device_id,
            "type": d.device_type,
            "name": d.display_name,
            "safety": d.safety_class.value,
            "capabilities": [c.name for c in d.capabilities],
        })

    return json.dumps({
        "count": len(result),
        "devices": result,
    }, indent=2)


@mcp.tool()
async def device_state(device_id: str) -> str:
    """Get the current state of a specific device.

    Args:
        device_id: The device ID (from devices_list)
    """
    if not adapter.is_initialized:
        return json.dumps({"error": "Scene not loaded. Call scene_load first."})

    try:
        state = await adapter.get_device_state(device_id)
        return json.dumps(state.to_dict(), indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def device_control(device_id: str, property_name: str, value: str) -> str:
    """Control a device by setting a property value.

    Args:
        device_id: The device ID (from devices_list)
        property_name: Property to set (e.g. "isToggled", "isOpen")
        value: New value ("true"/"false" for boolean properties)
    """
    if not adapter.is_initialized:
        return json.dumps({"error": "Scene not loaded. Call scene_load first."})

    cdd = adapter._devices.get(device_id)
    if not cdd:
        return json.dumps({"error": f"Device not found: {device_id}"})

    check = sandbox.check(cdd, property_name)
    if not check.allowed:
        return json.dumps({
            "error": "blocked_by_safety",
            "reason": check.reason,
            "requires_confirmation": check.requires_confirmation,
        })

    bool_value = value.lower() in ("true", "on", "1", "yes")

    try:
        new_state = await adapter.set_property(device_id, property_name, bool_value)
        return json.dumps({
            "status": "success",
            "device_id": device_id,
            "property": property_name,
            "new_value": bool_value,
            "full_state": new_state.to_dict(),
        }, indent=2)
    except (ValueError, RuntimeError) as e:
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
async def scene_capture() -> str:
    """Capture a screenshot of the current scene view. Returns base64-encoded PNG image."""
    if not adapter.is_initialized:
        return json.dumps({"error": "Scene not loaded. Call scene_load first."})

    image_b64 = await adapter.capture_image()
    return json.dumps({
        "status": "success",
        "format": "png",
        "encoding": "base64",
        "image": image_b64,
    })


@mcp.tool()
async def scene_describe() -> str:
    """Describe the current scene - list visible objects and their states."""
    if not adapter.is_initialized:
        return json.dumps({"error": "Scene not loaded. Call scene_load first."})

    devices = await adapter.list_devices()
    descriptions = []
    for d in devices:
        state = await adapter.get_device_state(d.device_id)
        state_str = ", ".join(f"{k}={v}" for k, v in state.properties.items())
        descriptions.append(f"- {d.display_name} ({d.device_type}): {state_str}")

    return json.dumps({
        "scene": adapter._scene,
        "description": "\n".join(descriptions),
        "device_count": len(devices),
    }, indent=2)


@mcp.tool()
async def events_history(limit: int = 10) -> str:
    """Get recent device events (state changes, actions).

    Args:
        limit: Number of recent events to return
    """
    history = event_bus.get_history(limit=limit)
    return json.dumps({"events": history}, indent=2, default=str)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
