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

| 工具 | 说明 |
|------|------|
| `scene_load` | 加载 AI2-THOR 场景（FloorPlan1-430） |
| `devices_list` | 列出所有可控设备及能力描述 |
| `device_state` | 查询设备当前状态 |
| `device_control` | 设置设备属性（开关/开合等） |
| `scene_capture` | 截取当前场景图像（base64 PNG） |
| `scene_describe` | 描述场景中所有设备状态 |
| `events_history` | 查询近期设备事件 |

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
│   ├── models.py          # CDD, DeviceState, SafetyLevel
│   ├── adapter.py         # Adapter 抽象接口
│   ├── safety.py          # SafetySandbox
│   ├── events.py          # EventBus
│   ├── mcp_server.py      # FastMCP Server 入口
│   └── adapters/
│       └── ai2thor_adapter.py  # AI2-THOR 实现
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

## 环境要求

- Python 3.10+
- AI2-THOR 需要图形环境（WSL2 需 X server 或 `xvfb-run`）
- 内存 16GB+（AI2-THOR Unity 进程约占 4GB）

## License

Apache 2.0
