# Test Results Report

## Test Environment

| Item | Value |
|------|-------|
| System | Linux 6.6.87.2-microsoft-standard-WSL2 |
| Python | 3.10.12 |
| AI2-THOR | 5.0.0 (Mock mode testing) |
| MCP SDK | 1.27.1 |
| Date | 2026-05-20 |

## Test Suite 1: Full Pipeline (Mock Adapter)

**File**: `tests/test_full_pipeline.py`  
**Result**: ✅ **36/36 passed**

| Test Group | Count | Status |
|------------|-------|--------|
| Adapter Initialization | 7 | ✅ All passed |
| Device State Query | 3 | ✅ All passed |
| Device Control | 5 | ✅ All passed |
| Safety Sandbox | 6 | ✅ All passed |
| Event Bus | 4 | ✅ All passed |
| Image Capture | 4 | ✅ All passed |
| Multi-Device Orchestration | 2 | ✅ All passed |
| CDD Format | 5 | ✅ All passed |

### Key Verification Points

- **Device Discovery**: Mock scene contains 10 devices (FloorLamp, DeskLamp, Television, Fridge, Microwave, StoveBurner, Faucet, Window, Safe, CoffeeMachine)
- **Property Control**: Supports both isToggled (on/off) and isOpen (open/close) property types
- **Safety Sandbox**:
  - LOW/MEDIUM/HIGH level devices pass when `max_allowed=HIGH` ✅
  - CRITICAL level devices are automatically blocked and require human confirmation ✅
  - Strict mode `max_allowed=MEDIUM` correctly blocks HIGH level operations ✅
- **Event Bus**: State change events are correctly triggered and recorded ✅
- **Image Capture**: Generates valid PNG images ✅

### Bug Fix Log

| Time | Issue | Fix |
|------|-------|-----|
| Initial run | CRITICAL devices passed safety checks | SafetySandbox.check() logic corrected: capability safety level now takes the higher of device level and capability level |

---

## Test Suite 2: MCP Server Tools

**File**: `tests/test_mcp_server.py`  
**Result**: ✅ **12/12 passed**

| Tool | Test Content | Status |
|------|-------------|--------|
| `scene_load` | Loading scene returns device count and type list | ✅ |
| `devices_list` | Unfiltered returns all 10 devices | ✅ |
| `devices_list(filter)` | Filtering by "Lamp" returns 2 | ✅ |
| `device_state` | Query FloorLamp initial state isToggled=False | ✅ |
| `device_control` (on) | Turn on lamp succeeds, state becomes True | ✅ |
| `device_control` (open) | Open fridge succeeds, state becomes True | ✅ |
| `device_control` (blocked) | Safe is blocked by safety sandbox, returns blocked_by_safety | ✅ |
| `scene_capture` | Returns valid base64 PNG (26556 characters) | ✅ |
| `scene_describe` | Returns status description text for 10 devices | ✅ |
| `events_history` | Returns 2 state change events | ✅ |
| Error handling | Non-existent device returns error field | ✅ |
| Persistence | Scene state persists across calls | ✅ |

---

## AI2-THOR Real-Environment Testing

**Status**: ⚠️ Currently limited by WSL2 environment, cannot complete

### Environment Diagnostics

| Approach | Result | Reason |
|----------|--------|--------|
| Default launch | Unity process `<defunct>` | Missing libGL/Mesa/Vulkan libraries |
| `platform=CloudRendering` | Timeout | Requires NVIDIA CloudRendering support |
| `x_display="0"` | Timeout | WSLg X server lacks OpenGL acceleration |

### Required Environment

The AI2-THOR Unity binary has been successfully downloaded (769MB → ~/.ai2thor/releases/, includes UnityPlayer.so 32MB), but launching requires:

```bash
# Option 1: Install Mesa OpenGL (requires sudo)
sudo apt-get install -y xvfb libvulkan1 libgl1-mesa-glx libglu1-mesa
xvfb-run python tests/test_ai2thor_real.py

# Option 2: Run on a machine with a GPU
# AI2-THOR supports Linux + NVIDIA GPU (recommended) or macOS

# Option 3: Docker with GPU
docker run --gpus all -it python:3.10 bash
pip install ai2thor && python -c "from ai2thor.controller import Controller; ..."
```

### Verification Script Ready

`tests/test_ai2thor_real.py` has been written and covers:
- [x] Scene loading + performance timing
- [x] Device discovery + category statistics
- [x] Toggle/Open operations (with safety checks)
- [x] Image capture + PNG verification
- [x] Multi-device orchestration scenarios
- [x] Event tracking
- [x] Safety sandbox real-world verification

Run on a machine with a graphics environment: `python tests/test_ai2thor_real.py`

---

## Performance Metrics (Mock Mode)

| Operation | Average Time |
|-----------|-------------|
| Scene initialization | < 1ms |
| Device list query | < 1ms |
| Single device state query | < 1ms |
| Device property control | < 1ms |
| Image generation (800x600 PNG) | ~5ms |
| Scene description (10 devices) | < 2ms |

---

## Design Improvement Log

Optimizations based on test feedback:

1. **SafetySandbox Logic Correction**  
   - Issue: Querying by capability overrode the device-level safety class
   - Fix: Take the higher value between device level and capability level
   - Impact: CRITICAL devices are now correctly blocked regardless of which capability is queried

2. **Mock Adapter Introduction**  
   - Motivation: AI2-THOR requires a 769MB binary download + graphics environment, which hinders rapid development and CI
   - Design: Fully simulates 10 device behaviors, generates PNG images visualizing device states
   - Usage: Switch via `HARNESS_MOCK=1` environment variable

3. **MCP Server Environment Variable Switching**  
   - Seamlessly switch between Mock/AI2-THOR modes via `HARNESS_MOCK=1`
   - Passed through the `env` field in NanoBot configuration
