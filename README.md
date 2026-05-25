<p align="center">
  <h1 align="center">🤖 Physical AI Harness</h1>
  <p align="center">
    <em>Let AI Agents perceive and control any physical device through a unified interface.</em>
  </p>
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-features">Features</a> •
  <a href="#-mcp-tools">MCP Tools</a> •
  <a href="#-adapters">Adapters</a> •
  <a href="#-roadmap">Roadmap</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/MCP-native-green?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCI+PHRleHQgeT0iMTgiIGZvbnQtc2l6ZT0iMTYiPuKalDwvdGV4dD48L3N2Zz4=" alt="MCP"/>
  <img src="https://img.shields.io/badge/license-Apache_2.0-orange" alt="License"/>
  <img src="https://img.shields.io/badge/simulation-AI2--THOR_%7C_MuJoCo-purple" alt="Simulation"/>
</p>

---

## 🌟 What is Physical AI Harness?

Physical AI Harness is an open-source hardware orchestration framework for AI Agents. It exposes simulated and real physical devices as standardized tools via the **Model Context Protocol (MCP)**, enabling any LLM-powered agent to sense and control the physical world.

```
User (natural language)
    ↓
AI Agent (Claude / GPT / any LLM)
    ↓ MCP Protocol
┌─────────────────────────────────────┐
│  Physical AI Harness                │
│  ├── Safety Sandbox (4-level)       │
│  ├── Event Bus (async pub/sub)      │
│  └── Adapter Layer (pluggable)      │
│       ├── AI2-THOR (IoT devices)    │
│       ├── MuJoCo (quadruped robot)  │
│       └── Your adapter here...      │
└─────────────────────────────────────┘
    ↓
Physical / Simulated Devices
```

### Key Design Principles

| Principle | Description |
|-----------|-------------|
| **Capability-First** | Devices are modeled by what they can do (capabilities), not by type |
| **MCP-Native** | Any MCP-compatible agent can connect instantly |
| **Safety-by-Default** | 4-level safety sandbox: LOW → MEDIUM → HIGH → CRITICAL |
| **Plugin Architecture** | Implement the `Adapter` interface to add any new backend |
| **Model-Agnostic** | Works with Claude, GPT, open-source models, or any LLM |

---

## ⚡ Quick Start

### Installation

```bash
git clone https://github.com/nanxintin/physical-ai-harness.git
cd physical-ai-harness
pip install -e .

# For MuJoCo robot support (optional)
pip install -e ".[mujoco]"
```

### Option 1: MCP Server (recommended — integrates with any agent)

```bash
# IoT simulation (mock mode, no GPU needed)
HARNESS_BACKEND=mock python -m harness.mcp_server

# Robot simulation (mock mode)
HARNESS_BACKEND=mujoco_mock python -m harness.mcp_server

# Real MuJoCo physics
MUJOCO_GL=egl HARNESS_BACKEND=mujoco python -m harness.mcp_server
```

### Option 2: Python SDK

```python
import asyncio
from harness.adapters.mujoco_go1.adapter import MuJoCoAdapter

async def main():
    adapter = MuJoCoAdapter()
    await adapter.initialize("flat_ground")

    # Discover devices
    devices = await adapter.list_devices()
    print(f"Found: {devices[0].display_name} with {len(devices[0].capabilities)} capabilities")

    # Control the robot
    await adapter.invoke_action("unitree_go1", "walk_forward", {"speed": 0.3, "duration": 2.0})

    # Read sensors
    state = await adapter.get_device_state("unitree_go1")
    print(f"Position: {state.properties['body_position']}")

    await adapter.shutdown()

asyncio.run(main())
```

### Option 3: Gradio Demo (visual interaction)

```bash
python demo/run_demo.py
# Open http://localhost:7860
```

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Layer 3: AI Agent (Claude / GPT / any LLM)              │
│           ↕ MCP Protocol (stdio / SSE)                   │
├──────────────────────────────────────────────────────────┤
│  Layer 2: Harness Core                                   │
│  ┌────────────┬──────────────┬────────────────────────┐  │
│  │ MCP Server │ Safety       │ Event Bus              │  │
│  │ (FastMCP)  │ Sandbox      │ (async pub/sub)        │  │
│  └────────────┴──────────────┴────────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│  Layer 1: Adapter Layer (pluggable backends)             │
│  ┌──────────────┬────────────────┬────────────────────┐  │
│  │ AI2-THOR     │ MuJoCo Go1     │ VirtualHome        │  │
│  │ (IoT sim)    │ (robot sim)    │ (graph sim)        │  │
│  └──────────────┴────────────────┴────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│  Layer 0: Simulation Backends                            │
│  Unity (AI2-THOR) │ MuJoCo (physics) │ Graph Engine     │
└──────────────────────────────────────────────────────────┘
```

---

## ✨ Features

### 🏠 IoT Smart Home Simulation (AI2-THOR)

- 120+ pre-built rooms (kitchens, living rooms, bedrooms, bathrooms)
- 600+ interactive objects (lamps, TVs, fridges, microwaves, faucets...)
- Automatic CDD generation from scene metadata
- Unity-quality rendering

### 🐕 Quadruped Robot (MuJoCo + Unitree Go1)

- 12 joint actuators (4 legs × 3 DOF)
- Body state sensors (position, orientation, velocity, IMU)
- Foot contact detection
- High-level locomotion: stand, sit, walk, turn, trot, stop
- Open-loop sinusoidal gait controller
- EGL headless rendering for CI/CD

### 🛡️ Safety Sandbox

| Level | Devices | Policy |
|-------|---------|--------|
| 🟢 LOW | Lamps, TVs, laptops | Execute freely |
| 🟡 MEDIUM | Fridge, microwave, e-stop | Parameter validation |
| 🔴 HIGH | Stove, faucet, robot joints | Warn before execution |
| ⛔ CRITICAL | Safe, fast gaits (trot) | Block, require human confirmation |

### 📡 Event-Driven Architecture

- Async event bus with publish/subscribe
- State change tracking with full history
- Event-triggered multi-device orchestration

---

## 🔧 MCP Tools

### Universal Tools (all backends)

| Tool | Description |
|------|-------------|
| `scene_load` | Load a simulation scene |
| `devices_list` | List all controllable devices with capabilities |
| `device_state` | Query current device state |
| `device_control` | Set device properties (boolean or float) |
| `scene_capture` | Capture scene image (base64 PNG) |
| `scene_describe` | Describe all device states |
| `events_history` | Query recent device events |

### Robot Tools (mujoco backend only)

| Tool | Description |
|------|-------------|
| `robot_move` | High-level locomotion (stand/sit/walk/turn/trot/stop) |
| `robot_joints` | Direct joint angle control (JSON targets) |
| `robot_sensors` | Read all sensor data at once |

---

## 🔌 Adapters

### Available Backends

| Backend | Env Variable | Use Case |
|---------|-------------|----------|
| `mock` | `HARNESS_BACKEND=mock` | IoT device mock (default, no GPU) |
| `ai2thor` | `HARNESS_BACKEND=ai2thor` | AI2-THOR Unity simulation |
| `virtualhome` | `HARNESS_BACKEND=virtualhome` | VirtualHome graph simulation |
| `mujoco` | `HARNESS_BACKEND=mujoco` | MuJoCo physics (real simulation) |
| `mujoco_mock` | `HARNESS_BACKEND=mujoco_mock` | Robot mock (no GPU, CI-friendly) |

### Writing Your Own Adapter

Implement the `Adapter` abstract class (6 async methods):

```python
from harness.adapter import Adapter

class MyAdapter(Adapter):
    async def initialize(self, scene: str) -> dict:
        """Load scene, return metadata."""

    async def list_devices(self) -> list[CDD]:
        """Return Capability Description Documents for all devices."""

    async def get_device_state(self, device_id: str) -> DeviceState:
        """Read current device state."""

    async def set_property(self, device_id: str, property_name: str, value) -> DeviceState:
        """Set a device property."""

    async def invoke_action(self, device_id: str, action: str, params=None) -> dict:
        """Execute a discrete action."""

    async def capture_image(self) -> str:
        """Capture scene view as base64 PNG."""
```

---

## 📦 Capability Model (CDD)

Every device declares its capabilities through a **Capability Description Document**:

```json
{
  "device_id": "unitree_go1",
  "device_type": "quadruped_robot",
  "display_name": "Unitree Go1",
  "safety_class": "high",
  "capabilities": [
    {
      "name": "joint_FR_hip",
      "type": "float",
      "writable": true,
      "safety_level": "high",
      "value_range": {"min": -0.863, "max": 0.863},
      "description": "Joint position target (radians)"
    },
    {
      "name": "walk_forward",
      "type": "action",
      "writable": true,
      "safety_level": "high",
      "description": "Walk forward at given speed"
    }
  ]
}
```

---

## 📁 Project Structure

```
physical-ai-harness/
├── harness/
│   ├── models.py                  # CDD, DeviceState, SafetyLevel
│   ├── adapter.py                 # Abstract Adapter interface
│   ├── safety.py                  # Safety Sandbox
│   ├── events.py                  # Async Event Bus
│   ├── mcp_server.py             # FastMCP Server (10 tools)
│   ├── mcp_tools_robot.py        # Robot-specific MCP tools
│   └── adapters/
│       ├── ai2thor_adapter.py         # AI2-THOR (IoT simulation)
│       ├── virtualhome_adapter.py     # VirtualHome (graph sim)
│       ├── mock_adapter.py            # IoT mock (testing)
│       └── mujoco_go1/               # MuJoCo quadruped robot
│           ├── adapter.py             # Real physics adapter
│           ├── mock_adapter.py        # Robot mock (testing)
│           ├── robot_config.py        # Joint/pose/action config
│           ├── locomotion.py          # Gait controller
│           └── models/unitree_go1/    # MJCF model files
├── demo/
│   ├── run_demo.py                # Gradio WebUI
│   ├── system_prompt.md           # Agent prompt (IoT)
│   └── system_prompt_robot.md     # Agent prompt (robot)
├── tests/
│   ├── test_full_pipeline.py      # IoT adapter tests (36 tests)
│   ├── test_mujoco_pipeline.py    # Robot adapter tests (49 tests)
│   ├── test_mujoco_mcp_tools.py   # Robot MCP tools (28 tests)
│   └── test_mujoco_e2e_demo.py    # End-to-end agent simulation
├── pyproject.toml
├── README.md
└── ROADMAP.md
```

---

## 🧪 Testing

```bash
# IoT pipeline (36 tests)
python tests/test_full_pipeline.py

# Robot pipeline (49 tests)
python tests/test_mujoco_pipeline.py

# Robot MCP tools (28 tests)
python tests/test_mujoco_mcp_tools.py

# End-to-end agent demo
python tests/test_mujoco_e2e_demo.py

# All tests: 113 passed, 0 failed
```

---

## 🗺️ Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0: MVP | ✅ Done | Core models, safety sandbox, event bus, AI2-THOR adapter, MCP server |
| Phase 1: E2E Validation | ✅ Done | Mock adapter, full test suite, Gradio demo |
| Phase 2: Multi-device | ✅ Done | VirtualHome adapter, cross-backend orchestration |
| Phase 3: Robot Integration | ✅ Done | MuJoCo adapter, Unitree Go1, gait control, robot MCP tools |
| Phase 4: Production Ready | 🔜 Next | Adapter SDK + CLI scaffold, benchmark dataset, Docker deployment |
| Phase 5: Open Source Release | 🔜 Planned | Documentation site, contributor guide, community building |
| Phase 6: Ecosystem | 🔮 Future | Real device protocols, multi-robot, autonomous driving (non-safety) |

See [ROADMAP.md](ROADMAP.md) for detailed milestones.

---

## 🔧 Requirements

- **Python**: 3.10+
- **AI2-THOR**: Requires display (X server or `xvfb-run` on WSL2)
- **MuJoCo**: Requires EGL or OSMesa (`MUJOCO_GL=egl`)
- **Memory**: 16GB+ (AI2-THOR Unity process ~4GB)

---

## 🤝 Contributing

We welcome contributions! To add a new simulation backend:

1. Implement the `Adapter` interface (6 methods)
2. Add backend selection in `mcp_server.py`
3. Write tests following the existing pattern
4. Submit a PR

---

## 📄 License

[Apache 2.0](LICENSE)
