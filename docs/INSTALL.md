# Installation and Usage Guide

## System Requirements

| Item | Minimum Version | Notes |
|------|----------------|-------|
| Python | 3.10+ | 3.11 recommended |
| Memory | 4GB | Mock mode; AI2-THOR requires 16GB+ |
| GPU | None | Mock mode requires no GPU; AI2-THOR requires a graphics environment |
| OS | Linux / WSL2 / macOS | AI2-THOR supports Linux and macOS |

## Quick Install

```bash
# 1. Clone the repository
git clone https://github.com/nanxintin/physical-ai-harness.git
cd physical-ai-harness

# 2. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -e .

# 4. Verify installation
python -c "from harness.mcp_server import mcp; print(f'OK: {len(mcp._tool_manager._tools)} tools registered')"
```

## Running Modes

### Mock Mode (Recommended for First Use)

No AI2-THOR Unity binary required; simulates 10 IoT devices in memory. Suitable for:
- First-time exploration and development
- CI/CD testing
- Servers without GPU or graphics environment

```bash
# Start MCP Server (Mock mode)
HARNESS_MOCK=1 python -m harness.mcp_server

# Run tests
python tests/test_full_pipeline.py
python tests/test_mcp_server.py

# Start Gradio Demo (Mock mode)
HARNESS_MOCK=1 python demo/run_demo.py
```

### AI2-THOR Mode (Full Simulation)

Requires downloading the AI2-THOR Unity binary (~769MB), which is automatically downloaded on first launch.

**Additional WSL2 Requirements**:
```bash
# Install X server support
sudo apt-get install xvfb

# Option 1: Use Xvfb virtual display
xvfb-run python -m harness.mcp_server

# Option 2: Use WSLg (built into Windows 11, ensure DISPLAY is set)
echo $DISPLAY  # Should output :0 or similar
python -m harness.mcp_server
```

**macOS / Native Linux**:
```bash
# Launch directly (automatically uses system graphics environment)
python -m harness.mcp_server
```

**First-time Unity Binary Download**:
```bash
# Pre-download (avoid waiting during first scene_load call)
python -c "from ai2thor.controller import Controller; print('Download complete')"
# File location: ~/.ai2thor/releases/
```

## Integration with NanoBot

### Configuration

Connect the Harness as an MCP Server to NanoBot:

```bash
# Edit NanoBot configuration (or use demo/nanobot_config.json)
cat demo/nanobot_config.json
```

Key configuration:
```json
{
  "tools": {
    "mcp_servers": {
      "harness": {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "harness.mcp_server"],
        "env": {"HARNESS_MOCK": "1"},
        "tool_timeout": 120
      }
    }
  }
}
```

### Running

```python
import asyncio
from nanobot.nanobot import Nanobot

async def main():
    bot = Nanobot.from_config("demo/nanobot_config.json")
    result = await bot.run("Load the kitchen scene and list all devices")
    print(result.content)

asyncio.run(main())
```

## Debugging

### View MCP Tool Registration

```python
from harness.mcp_server import mcp
for name, tool in mcp._tool_manager._tools.items():
    print(f"  {name}: {tool.description[:60]}")
```

### Test Adapter Independently

```python
import asyncio, os
os.environ["HARNESS_MOCK"] = "1"

from harness.adapters.mock_adapter import MockAdapter
from harness.events import EventBus

async def debug():
    bus = EventBus()
    adapter = MockAdapter(event_bus=bus)
    await adapter.initialize("FloorPlan1")
    
    devices = await adapter.list_devices()
    for d in devices:
        state = await adapter.get_device_state(d.device_id)
        print(f"{d.device_type:15s} | {d.safety_class.value:8s} | {state.properties}")

asyncio.run(debug())
```

### MCP Server Logs

```bash
# Launch with verbose logging
HARNESS_MOCK=1 python -m harness.mcp_server 2>mcp_debug.log
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| AI2-THOR download is slow | Use a proxy: `export http_proxy=...`; or use Mock mode first |
| WSL2 cannot render | `sudo apt install xvfb && xvfb-run python ...` |
| MCP connection timeout | Increase `tool_timeout` to 120-180 (AI2-THOR first launch is slow) |
| Out of memory | Use Mock mode, or reduce AI2-THOR resolution |
| "Scene not loaded" | Ensure `scene_load` tool is called first |
