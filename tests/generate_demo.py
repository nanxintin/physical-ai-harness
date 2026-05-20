#!/usr/bin/env python3
"""Generate demo GIF from VirtualHome task execution.

Renders step-by-step frames showing device states and agent actions,
then combines into an animated GIF. No GPU or FFmpeg required.

Usage: python tests/generate_demo.py
Output: tests/ai2thor_results/demo_task_execution.gif
"""

import asyncio
import base64
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).parent / "ai2thor_results"
OUTPUT_DIR.mkdir(exist_ok=True)
FRAME_DIR = OUTPUT_DIR / "demo_frames"
FRAME_DIR.mkdir(exist_ok=True)

# Visual constants
W, H = 900, 650
BG_COLOR = (25, 25, 35)
HEADER_COLOR = (50, 50, 70)
TEXT_COLOR = (220, 220, 220)
ACTION_COLOR = (100, 200, 255)
SUCCESS_COLOR = (80, 220, 80)
BLOCKED_COLOR = (255, 80, 80)
DEVICE_ON_COLOR = (0, 200, 100)
DEVICE_OFF_COLOR = (120, 120, 130)


def render_frame(
    step_num: int,
    total_steps: int,
    action_text: str,
    devices: list[dict],
    status: str = "executing",
    message: str = "",
) -> Image.Image:
    """Render a single visualization frame."""
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle([(0, 0), (W, 55)], fill=HEADER_COLOR)
    draw.text((20, 12), "Physical AI Harness — Task Execution Demo", fill=(255, 255, 255))
    draw.text((W - 150, 12), f"Step {step_num}/{total_steps}", fill=(180, 180, 180))

    # Progress bar
    progress = step_num / max(total_steps, 1)
    draw.rectangle([(20, 45), (W - 20, 52)], fill=(60, 60, 80))
    draw.rectangle([(20, 45), (20 + int((W - 40) * progress), 52)], fill=ACTION_COLOR)

    # Current action
    y = 70
    draw.text((20, y), "Current Action:", fill=(180, 180, 180))
    y += 25
    action_color = SUCCESS_COLOR if status == "success" else BLOCKED_COLOR if status == "blocked" else ACTION_COLOR
    draw.text((20, y), f"  → {action_text}", fill=action_color)
    y += 25
    if message:
        msg_color = SUCCESS_COLOR if "✅" in message else BLOCKED_COLOR if "❌" in message or "⚠️" in message else TEXT_COLOR
        draw.text((20, y), f"  {message}", fill=msg_color)
    y += 35

    # Separator
    draw.line([(20, y), (W - 20, y)], fill=(60, 60, 80))
    y += 15

    # Device status panel
    draw.text((20, y), "Device States:", fill=(180, 180, 180))
    y += 30

    for device in devices:
        name = device["name"]
        states = device.get("states", [])
        safety = device.get("safety", "low")
        active = "ON" in states or "OPEN" in states

        # Safety indicator
        safety_colors = {"low": (80, 200, 80), "medium": (220, 180, 40), "high": (220, 80, 40), "critical": (200, 0, 0)}
        sc = safety_colors.get(safety, (150, 150, 150))
        draw.ellipse([(20, y + 3), (32, y + 15)], fill=sc)

        # Device name and state
        color = DEVICE_ON_COLOR if active else DEVICE_OFF_COLOR
        state_str = ", ".join(states) if states else "—"
        draw.text((40, y), f"{name:18s}", fill=color)
        draw.text((220, y), f"{state_str}", fill=color)
        draw.text((450, y), f"[{safety}]", fill=(120, 120, 130))
        y += 28

    # Footer
    draw.rectangle([(0, H - 30), (W, H)], fill=HEADER_COLOR)
    draw.text((20, H - 25), "Engine: VirtualHome evolving_graph (CPU) | Harness v0.1.0", fill=(120, 120, 130))

    return img


async def run_demo_scenario():
    """Execute a demo scenario and capture frames."""
    from harness.adapters.virtualhome_adapter import VirtualHomeAdapter
    from harness.events import EventBus
    from harness.models import SafetyLevel
    from harness.safety import SafetySandbox

    bus = EventBus()
    adapter = VirtualHomeAdapter(event_bus=bus)
    sandbox = SafetySandbox(max_allowed=SafetyLevel.HIGH)
    await adapter.initialize("kitchen")

    devices_list = await adapter.list_devices()
    frames: list[Image.Image] = []

    # Define demo scenario
    scenario = [
        {"action": "Scene loaded: Kitchen (13 devices)", "type": "info"},
        {"action": "Turn on the light", "device_id": "lightswitch_5", "property": "power", "value": "on"},
        {"action": "Open the fridge", "device_id": "fridge_2", "property": "open", "value": True},
        {"action": "Close the fridge", "device_id": "fridge_2", "property": "open", "value": False},
        {"action": "Turn on the microwave", "device_id": "microwave_3", "property": "power", "value": "on"},
        {"action": "Open the microwave", "device_id": "microwave_3", "property": "open", "value": True},
        {"action": "Turn on the TV", "device_id": "tv_14", "property": "power", "value": "on"},
        {"action": "Turn on the stove (HIGH safety)", "device_id": "stove_4", "property": "power", "value": "on"},
        {"action": "Turn off everything (batch)", "type": "batch_off"},
    ]

    total_steps = len(scenario)

    async def get_device_display():
        """Get current device states for display."""
        display = []
        for d in devices_list:
            state = await adapter.get_device_state(d.device_id)
            display.append({
                "name": d.device_type,
                "states": state.properties.get("states", []),
                "safety": d.safety_class.value,
            })
        return display

    # Initial frame
    device_display = await get_device_display()
    frames.append(render_frame(0, total_steps, "Initializing scene...", device_display, "executing", "Loading kitchen environment"))

    for i, step in enumerate(scenario, 1):
        action_text = step["action"]

        if step.get("type") == "info":
            device_display = await get_device_display()
            frames.append(render_frame(i, total_steps, action_text, device_display, "success", "✅ 13 devices discovered"))

        elif step.get("type") == "batch_off":
            switchable = [d for d in devices_list if any(c.name == "power" for c in d.capabilities)]
            for d in switchable:
                try:
                    await adapter.set_property(d.device_id, "power", "off")
                except Exception:
                    pass
            device_display = await get_device_display()
            frames.append(render_frame(i, total_steps, action_text, device_display, "success", "✅ All devices turned off"))

        else:
            device_id = step["device_id"]
            prop = step["property"]
            value = step["value"]

            cdd = adapter._devices.get(device_id)
            if cdd:
                check = sandbox.check(cdd, prop)
                if not check.allowed:
                    device_display = await get_device_display()
                    frames.append(render_frame(i, total_steps, action_text, device_display, "blocked", f"⚠️ BLOCKED: {check.reason}"))
                else:
                    try:
                        await adapter.set_property(device_id, prop, value)
                        device_display = await get_device_display()
                        frames.append(render_frame(i, total_steps, action_text, device_display, "success", f"✅ {cdd.device_type} → {prop}={value}"))
                    except Exception as e:
                        device_display = await get_device_display()
                        frames.append(render_frame(i, total_steps, action_text, device_display, "error", f"❌ {e}"))

    # Save individual frames
    for idx, frame in enumerate(frames):
        frame.save(FRAME_DIR / f"frame_{idx:03d}.png")

    # Generate GIF
    gif_path = OUTPUT_DIR / "demo_task_execution.gif"
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=1500,  # 1.5 seconds per frame
        loop=0,
    )
    print(f"✅ Demo GIF saved: {gif_path} ({len(frames)} frames, {len(frames)*1.5:.0f}s)")

    # Also save as individual PNGs for inspection
    print(f"✅ Individual frames saved to: {FRAME_DIR}/")

    return gif_path, len(frames)


if __name__ == "__main__":
    gif_path, frame_count = asyncio.run(run_demo_scenario())
    print(f"\nDemo generation complete!")
    print(f"  GIF: {gif_path}")
    print(f"  Frames: {frame_count}")
    print(f"  Duration: {frame_count * 1.5:.0f}s @ 1.5s/frame")
