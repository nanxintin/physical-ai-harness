# 安装与运行指南

## 环境要求

| 项目 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.10+ | 推荐 3.11 |
| 内存 | 4GB | Mock 模式；AI2-THOR 需 16GB+ |
| 显卡 | 无 | Mock 模式无需 GPU；AI2-THOR 需要图形环境 |
| 系统 | Linux / WSL2 / macOS | AI2-THOR 支持 Linux 和 macOS |

## 快速安装

```bash
# 1. 克隆仓库
git clone https://github.com/nanxintin/physical-ai-harness.git
cd physical-ai-harness

# 2. 创建虚拟环境（推荐）
python -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -e .

# 4. 验证安装
python -c "from harness.mcp_server import mcp; print(f'OK: {len(mcp._tool_manager._tools)} tools registered')"
```

## 运行模式

### Mock 模式（推荐初次使用）

无需 AI2-THOR Unity 二进制，内存中模拟 10 个 IoT 设备。适合：
- 首次体验和开发调试
- CI/CD 测试
- 无 GPU / 无图形环境的服务器

```bash
# 启动 MCP Server（Mock 模式）
HARNESS_MOCK=1 python -m harness.mcp_server

# 运行测试
python tests/test_full_pipeline.py
python tests/test_mcp_server.py

# 启动 Gradio Demo（Mock 模式）
HARNESS_MOCK=1 python demo/run_demo.py
```

### AI2-THOR 模式（完整仿真）

需要下载 AI2-THOR Unity 二进制（~769MB），首次启动时自动下载。

**WSL2 额外要求**：
```bash
# 安装 X server 支持
sudo apt-get install xvfb

# 方式一：使用 Xvfb 虚拟显示
xvfb-run python -m harness.mcp_server

# 方式二：使用 WSLg（Windows 11 自带，确认 DISPLAY 已设置）
echo $DISPLAY  # 应输出 :0 或类似值
python -m harness.mcp_server
```

**macOS / 本机 Linux**：
```bash
# 直接启动（自动使用系统图形环境）
python -m harness.mcp_server
```

**首次下载 Unity 二进制**：
```bash
# 预下载（避免首次调用 scene_load 时等待）
python -c "from ai2thor.controller import Controller; print('Download complete')"
# 文件位置：~/.ai2thor/releases/
```

## 与 NanoBot 集成

### 配置

将 Harness 作为 MCP Server 连接到 NanoBot：

```bash
# 编辑 NanoBot 配置（或使用 demo/nanobot_config.json）
cat demo/nanobot_config.json
```

关键配置项：
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

### 运行

```python
import asyncio
from nanobot.nanobot import Nanobot

async def main():
    bot = Nanobot.from_config("demo/nanobot_config.json")
    result = await bot.run("Load the kitchen scene and list all devices")
    print(result.content)

asyncio.run(main())
```

## 调试

### 查看 MCP 工具注册

```python
from harness.mcp_server import mcp
for name, tool in mcp._tool_manager._tools.items():
    print(f"  {name}: {tool.description[:60]}")
```

### 单独测试 Adapter

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

### MCP Server 日志

```bash
# 带详细日志启动
HARNESS_MOCK=1 python -m harness.mcp_server 2>mcp_debug.log
```

### 常见问题

| 问题 | 解决方案 |
|------|---------|
| AI2-THOR 下载慢 | 使用代理：`export http_proxy=...`；或先用 Mock 模式 |
| WSL2 无法渲染 | `sudo apt install xvfb && xvfb-run python ...` |
| MCP 连接超时 | 增大 `tool_timeout` 到 120-180（AI2-THOR 首次启动慢） |
| 内存不足 | 使用 Mock 模式，或降低 AI2-THOR 分辨率 |
| "Scene not loaded" | 确保先调用 `scene_load` 工具 |
