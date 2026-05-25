#!/usr/bin/env python3
"""Physical AI Harness Demo - Gradio WebUI.

Runs the Harness MCP Server directly (in-process) and provides a chat interface
where users can control simulated IoT devices via natural language.

Usage:
    python demo/run_demo.py
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import gradio as gr

from harness.adapters.ai2thor_adapter import AI2ThorAdapter
from harness.events import EventBus
from harness.models import SafetyLevel
from harness.safety import SafetySandbox

event_bus = EventBus()
adapter = AI2ThorAdapter(event_bus=event_bus)
sandbox = SafetySandbox(max_allowed=SafetyLevel.HIGH)

_scene_loaded = False


async def ensure_scene(scene: str = "FloorPlan1"):
    global _scene_loaded
    if not _scene_loaded:
        await adapter.initialize(scene)
        _scene_loaded = True


async def process_command(user_input: str, history: list):
    """Process a user command and return results."""
    global _scene_loaded

    await ensure_scene()

    response_text = ""
    image_data = None
    device_states = {}

    user_lower = user_input.lower()

    if any(w in user_lower for w in ["list", "what devices", "show devices"]):
        devices = await adapter.list_devices()
        lines = []
        for d in devices:
            caps = ", ".join(c.name for c in d.capabilities)
            lines.append(f"• **{d.display_name}** ({d.device_type}) [{d.safety_class.value}] - {caps}")
        response_text = f"Found {len(devices)} controllable devices:\n\n" + "\n".join(lines[:30])
        if len(devices) > 30:
            response_text += f"\n... and {len(devices) - 30} more"

    elif any(w in user_lower for w in ["capture", "screenshot", "show", "scene", "photo"]):
        img_b64 = await adapter.capture_image()
        image_data = base64.b64decode(img_b64)
        response_text = "Here's the current scene view."

    elif any(w in user_lower for w in ["describe", "status", "overview"]):
        devices = await adapter.list_devices()
        lines = []
        for d in devices[:20]:
            state = await adapter.get_device_state(d.device_id)
            state_str = ", ".join(f"{k}={v}" for k, v in state.properties.items())
            lines.append(f"• {d.display_name}: {state_str}")
        response_text = f"Scene status ({adapter._scene}):\n\n" + "\n".join(lines)

    elif any(w in user_lower for w in ["turn on", "open"]):
        target = _find_device_in_text(user_input)
        if target:
            cdd = adapter._devices.get(target)
            check = sandbox.check(cdd)
            if not check.allowed:
                response_text = f"⚠️ Blocked: {check.reason}"
            else:
                prop = "isToggled" if any(c.name == "isToggled" for c in cdd.capabilities) else "isOpen"
                try:
                    new_state = await adapter.set_property(target, prop, True)
                    response_text = f"✅ Turned on/opened **{cdd.display_name}**\nNew state: {new_state.properties}"
                    device_states = new_state.to_dict()
                except Exception as e:
                    response_text = f"❌ Failed: {e}"
        else:
            response_text = "I couldn't identify which device to control. Try listing devices first."

    elif any(w in user_lower for w in ["turn off", "close"]):
        target = _find_device_in_text(user_input)
        if target:
            cdd = adapter._devices.get(target)
            check = sandbox.check(cdd)
            if not check.allowed:
                response_text = f"⚠️ Blocked: {check.reason}"
            else:
                prop = "isToggled" if any(c.name == "isToggled" for c in cdd.capabilities) else "isOpen"
                try:
                    new_state = await adapter.set_property(target, prop, False)
                    response_text = f"✅ Turned off/closed **{cdd.display_name}**\nNew state: {new_state.properties}"
                    device_states = new_state.to_dict()
                except Exception as e:
                    response_text = f"❌ Failed: {e}"
        else:
            response_text = "I couldn't identify which device to control. Try listing devices first."

    elif any(w in user_lower for w in ["load", "scene"]):
        import re
        match = re.search(r"FloorPlan\d+", user_input)
        scene_name = match.group(0) if match else "FloorPlan1"
        _scene_loaded = False
        await ensure_scene(scene_name)
        devices = await adapter.list_devices()
        response_text = f"✅ Loaded **{scene_name}** with {len(devices)} controllable devices."

    else:
        response_text = (
            "I can help you control IoT devices. Try:\n"
            "• \"list devices\" - show all controllable devices\n"
            "• \"turn on the lamp\" - control a device\n"
            "• \"capture scene\" - take a screenshot\n"
            "• \"describe status\" - show all device states\n"
            "• \"load FloorPlan201\" - switch scene"
        )

    history.append((user_input, response_text))

    img_output = None
    if image_data:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(image_data)
        tmp.close()
        img_output = tmp.name

    return history, img_output, json.dumps(device_states, indent=2) if device_states else ""


def _find_device_in_text(text: str) -> str | None:
    """Fuzzy-match a device from the text."""
    text_lower = text.lower()
    best_match = None
    best_score = 0

    for device_id, cdd in adapter._devices.items():
        type_lower = cdd.device_type.lower()
        name_lower = cdd.display_name.lower()

        if type_lower in text_lower or name_lower in text_lower:
            score = len(type_lower)
            if score > best_score:
                best_score = score
                best_match = device_id

    return best_match


def create_demo():
    with gr.Blocks(title="Physical AI Harness Demo", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🏠 Physical AI Harness Demo\nControl simulated IoT devices through natural language.")

        with gr.Row():
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(label="Agent Conversation", height=400)
                msg = gr.Textbox(label="Your command", placeholder="e.g., 'list devices' or 'turn on the lamp'")
                with gr.Row():
                    send_btn = gr.Button("Send", variant="primary")
                    clear_btn = gr.Button("Clear")

                gr.Examples(
                    examples=[
                        "list devices",
                        "turn on the floor lamp",
                        "open the fridge",
                        "capture scene",
                        "describe status",
                        "turn off the microwave",
                        "load FloorPlan201",
                    ],
                    inputs=msg,
                )

            with gr.Column(scale=1):
                scene_image = gr.Image(label="Scene View", type="filepath")
                device_json = gr.Code(label="Device State", language="json")

        async def respond(message, chat_history):
            if not message.strip():
                return chat_history, None, ""
            chat_history, img, states = await process_command(message, chat_history or [])
            return chat_history, img, states

        send_btn.click(respond, [msg, chatbot], [chatbot, scene_image, device_json]).then(
            lambda: "", None, msg
        )
        msg.submit(respond, [msg, chatbot], [chatbot, scene_image, device_json]).then(
            lambda: "", None, msg
        )
        clear_btn.click(lambda: ([], None, ""), None, [chatbot, scene_image, device_json])

    return demo


if __name__ == "__main__":
    demo = create_demo()
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
