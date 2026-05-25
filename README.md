# Physical AI Harness

**让 AI Agent 以统一接口感知和操控一切物理设备。**

Physical AI Harness 是一个面向 AI Agent 的开源硬件编排框架，通过统一的 Capability Model 和 MCP 协议，将仿真/真实物理设备暴露为 Agent 可调用的标准化工具。

```
User (自然语言)
    ↓
Agent (Claude / GPT / MiMo)
    ↓ MCP Protocol
Harness MCP Server
    ├── Safety Sandbox (四级安全校验)
    ├── Event Bus (状态变更事件)
    └── Adapter Layer (可插拔)
         ↓
Physical / Simulated Devices
```

## 核心特性

- **Capability-First 抽象**：所有设备按能力原语建模（set_property / read_sensor / invoke_action / capture_image），而非按设备类型硬编码
- **MCP 原生**：通过 Model Context Protocol 暴露工具，任何支持 MCP 的 Agent 即插即用
- **四级安全沙箱**：LOW → MEDIUM → HIGH → CRITICAL，CRITICAL 级操作自动拦截
- **插件化适配层**：实现 `Adapter` 接口即可接入新的仿真/真实设备后端
- **AI2-THOR 仿真**：内置 AI2-THOR 适配器，120+ 预置房间，600+ 可交互物体

## 快速开始

### 安装

```bash
cd harness
pip install -e .
```

### 方式一：MCP Server（推荐，与任何 Agent 框架集成）

```bash
# 启动 MCP Server（stdio 模式）
python -m harness.mcp_server
```

在 Agent 框架中配置 MCP 连接（以 NanoBot 为例）：

```json
{
  "tools": {
    "mcp_servers": {
      "harness": {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "harness.mcp_server"],
        "tool_timeout": 120
      }
    }
  }
}
```

### 方式二：Gradio Demo（可视化交互）

```bash
python demo/run_demo.py
# 打开 http://localhost:7860
```

### 方式三：Python SDK 直接调用

```python
import asyncio
from harness.adapters.ai2thor_adapter import AI2ThorAdapter

async def main():
    adapter = AI2ThorAdapter()
    await adapter.initialize("FloorPlan1")
    
    # 发现设备
    devices = await adapter.list_devices()
    print(f"Found {len(devices)} devices")
    
    # 控制设备
    lamps = [d for d in devices if "Lamp" in d.device_type]
    if lamps:
        state = await adapter.set_property(lamps[0].device_id, "isToggled", True)
        print(f"Lamp state: {state.properties}")
    
    # 捕获场景图像
    image_b64 = await adapter.capture_image()

asyncio.run(main())
```

## MCP 工具列表

### 通用工具（所有后端）

| 工具 | 说明 |
|------|------|
| `scene_load` | 加载场景（IoT: FloorPlan1-430, Robot: flat_ground） |
| `devices_list` | 列出所有可控设备及能力描述 |
| `device_state` | 查询设备当前状态 |
| `device_control` | 设置设备属性（布尔/浮点数） |
| `scene_capture` | 截取当前场景图像（base64 PNG） |
| `scene_describe` | 描述场景中所有设备状态 |
| `events_history` | 查询近期设备事件 |

### 机器人专属工具（HARNESS_BACKEND=mujoco/mujoco_mock）

| 工具 | 说明 |
|------|------|
| `robot_move` | 高级运动指令（stand/sit/walk/turn/trot/stop） |
| `robot_joints` | 直接设置关节角度（JSON 格式） |
| `robot_sensors` | 一次性读取全部传感器数据 |

## Capability Model (CDD)

每个设备通过 **Capability Description Document** 声明能力：

```json
{
  "device_id": "FloorLamp|+01.32|+00.00|+00.45",
  "device_type": "FloorLamp",
  "display_name": "FloorLamp",
  "safety_class": "low",
  "capabilities": [
    {"name": "isToggled", "type": "boolean", "writable": true, "description": "Power on/off state"}
  ]
}
```

AI2-THOR 适配器从场景元数据**自动生成** CDD，无需手动编写。

## 安全等级

| 等级 | 设备示例 | 策略 |
|------|---------|------|
| 🟢 LOW | 灯、电视、笔记本 | 直接执行 |
| 🟡 MEDIUM | 冰箱、微波炉、窗户 | 参数校验后执行 |
| 🔴 HIGH | 灶台、水龙头 | 警告用户后执行 |
| ⛔ CRITICAL | 保险箱 | 拒绝执行，要求人工确认 |

## 项目结构

```
harness/
├── harness/
│   ├── models.py              # CDD, DeviceState, SafetyLevel
│   ├── adapter.py             # Adapter 抽象接口
│   ├── safety.py              # SafetySandbox
│   ├── events.py              # EventBus
│   ├── mcp_server.py          # FastMCP Server 入口
│   ├── mcp_tools_robot.py     # 机器人专属 MCP 工具
│   └── adapters/
│       ├── ai2thor_adapter.py       # AI2-THOR IoT 仿真
│       ├── virtualhome_adapter.py   # VirtualHome 仿真
│       ├── mock_adapter.py          # IoT Mock 测试
│       └── mujoco_go1/             # MuJoCo 四足机器人
│           ├── adapter.py           # MuJoCoAdapter（真实仿真）
│           ├── mock_adapter.py      # MockMuJoCoAdapter（测试用）
│           ├── robot_config.py      # 关节/姿态/动作配置
│           ├── locomotion.py        # 步态控制器
│           └── models/unitree_go1/  # Go1 MJCF 模型文件
├── demo/
│   ├── nanobot_config.json     # NanoBot 集成配置
│   ├── system_prompt.md        # Agent 系统提示词
│   └── run_demo.py             # Gradio WebUI
└── pyproject.toml
```

## AI2-THOR 场景

| 场景范围 | 类型 | 推荐 |
|---------|------|------|
| FloorPlan1-30 | 厨房 | ⭐ 最佳 Demo（丰富的电器交互） |
| FloorPlan201-230 | 客厅 | 灯、电视、电子设备 |
| FloorPlan301-330 | 卧室 | 灯、百叶窗 |
| FloorPlan401-430 | 浴室 | 水龙头、毛巾 |

## 后端选择

通过环境变量 `HARNESS_BACKEND` 切换后端：

| 值 | 后端 | 用途 |
|------|------|------|
| `mock`（默认） | MockAdapter | IoT 设备 Mock 测试 |
| `ai2thor` | AI2ThorAdapter | AI2-THOR Unity IoT 仿真 |
| `virtualhome` | VirtualHomeAdapter | VirtualHome 图仿真 |
| `mujoco` | MuJoCoAdapter | MuJoCo 四足机器人（真实物理） |
| `mujoco_mock` | MockMuJoCoAdapter | 四足机器人 Mock（无 GPU） |

```bash
# IoT 模式
HARNESS_BACKEND=mock python -m harness.mcp_server

# 机器人模式（真实 MuJoCo 仿真）
HARNESS_BACKEND=mujoco python -m harness.mcp_server

# 机器人模式（Mock，CI/测试用）
HARNESS_BACKEND=mujoco_mock python -m harness.mcp_server
```

## MuJoCo 机器人

### Unitree Go1 四足机器人

- 12 关节执行器（4 腿 × 3 自由度）
- 传感器：体态、IMU、足底接触
- 高级动作：stand/sit/walk/turn/trot/stop
- 安全等级：运动控制 HIGH，快速步态 CRITICAL

```python
# 快速验证
MUJOCO_GL=egl HARNESS_BACKEND=mujoco python -c "
import asyncio
from harness.adapters.mujoco_go1.adapter import MuJoCoAdapter
async def main():
    a = MuJoCoAdapter()
    await a.initialize('flat_ground')
    await a.invoke_action('unitree_go1', 'walk_forward', {'speed': 0.3, 'duration': 2.0})
    state = await a.get_device_state('unitree_go1')
    print(f'Position: {state.properties[\"body_position\"]}')
    await a.shutdown()
asyncio.run(main())
"
```

### 安装 MuJoCo 依赖

```bash
pip install mujoco>=3.0.0 numpy PyOpenGL
# EGL rendering 需要 libEGL（WSL2 通常已有）
```

## 环境要求

- Python 3.10+
- AI2-THOR 需要图形环境（WSL2 需 X server 或 `xvfb-run`）
- MuJoCo 需要 EGL 或 OSMesa（`MUJOCO_GL=egl`）
- 内存 16GB+（AI2-THOR Unity 进程约占 4GB）

## License

Apache 2.0
