# 测试结果报告

## 测试环境

| 项目 | 值 |
|------|------|
| 系统 | Linux 6.6.87.2-microsoft-standard-WSL2 |
| Python | 3.10.12 |
| AI2-THOR | 5.0.0（Mock 模式测试） |
| MCP SDK | 1.27.1 |
| 日期 | 2026-05-20 |

## 测试套件 1：Full Pipeline（Mock Adapter）

**文件**：`tests/test_full_pipeline.py`  
**结果**：✅ **36/36 passed**

| 测试组 | 项数 | 状态 |
|--------|------|------|
| Adapter Initialization | 7 | ✅ 全部通过 |
| Device State Query | 3 | ✅ 全部通过 |
| Device Control | 5 | ✅ 全部通过 |
| Safety Sandbox | 6 | ✅ 全部通过 |
| Event Bus | 4 | ✅ 全部通过 |
| Image Capture | 4 | ✅ 全部通过 |
| Multi-Device Orchestration | 2 | ✅ 全部通过 |
| CDD Format | 5 | ✅ 全部通过 |

### 关键验证点

- **设备发现**：Mock 场景包含 10 个设备（FloorLamp, DeskLamp, Television, Fridge, Microwave, StoveBurner, Faucet, Window, Safe, CoffeeMachine）
- **属性控制**：支持 isToggled（开关）和 isOpen（开合）两种属性类型
- **安全沙箱**：
  - LOW/MEDIUM/HIGH 级设备在 `max_allowed=HIGH` 时允许通过 ✅
  - CRITICAL 级设备自动拦截并要求人工确认 ✅
  - 严格模式 `max_allowed=MEDIUM` 正确阻断 HIGH 级操作 ✅
- **事件总线**：状态变更事件正确触发和记录 ✅
- **图像捕获**：生成有效 PNG 图像 ✅

### Bug 修复记录

| 时间 | 问题 | 修复 |
|------|------|------|
| 初次运行 | CRITICAL 设备通过了安全检查 | SafetySandbox.check() 逻辑修正：capability 安全等级取设备级别和 capability 级别的较高者 |

---

## 测试套件 2：MCP Server Tools

**文件**：`tests/test_mcp_server.py`  
**结果**：✅ **12/12 passed**

| 工具 | 测试内容 | 状态 |
|------|---------|------|
| `scene_load` | 加载场景返回设备计数和类型列表 | ✅ |
| `devices_list` | 无过滤返回全部 10 设备 | ✅ |
| `devices_list(filter)` | 按 "Lamp" 过滤返回 2 个 | ✅ |
| `device_state` | 查询 FloorLamp 初始状态 isToggled=False | ✅ |
| `device_control` (on) | 开灯成功，状态变为 True | ✅ |
| `device_control` (open) | 开冰箱成功，状态变为 True | ✅ |
| `device_control` (blocked) | Safe 被安全沙箱拦截，返回 blocked_by_safety | ✅ |
| `scene_capture` | 返回有效 base64 PNG（26556 字符） | ✅ |
| `scene_describe` | 返回 10 设备的状态描述文本 | ✅ |
| `events_history` | 返回 2 条状态变更事件 | ✅ |
| 错误处理 | 不存在的设备返回 error 字段 | ✅ |
| 持久性 | 跨调用场景状态保持 | ✅ |

---

## AI2-THOR 真实测试（待完成）

**状态**：AI2-THOR Unity 二进制下载中（769MB）

待完成项目：
- [ ] FloorPlan1（厨房）场景加载和设备发现
- [ ] 真实设备 Toggle/Open 操作
- [ ] 场景图像渲染验证
- [ ] 性能基准：场景加载时间、操作延迟
- [ ] 多场景切换（FloorPlan1 → FloorPlan201）

---

## 性能指标（Mock 模式）

| 操作 | 平均耗时 |
|------|---------|
| 场景初始化 | < 1ms |
| 设备列表查询 | < 1ms |
| 单设备状态查询 | < 1ms |
| 设备属性控制 | < 1ms |
| 图像生成（800x600 PNG） | ~5ms |
| 场景描述（10 设备） | < 2ms |

---

## 设计改进记录

基于测试反馈的优化：

1. **SafetySandbox 逻辑修正**  
   - 问题：按 capability 查询时覆盖了设备级安全等级
   - 修复：取设备级别和 capability 级别的较高值
   - 影响：CRITICAL 设备现在无论查询哪个 capability 都会被正确拦截

2. **Mock Adapter 引入**  
   - 动机：AI2-THOR 需要 769MB 二进制下载 + 图形环境，不利于快速开发和 CI
   - 设计：完整模拟 10 个设备行为，可视化输出设备状态的 PNG 图像
   - 使用：`HARNESS_MOCK=1` 环境变量切换

3. **MCP Server 环境变量切换**  
   - 通过 `HARNESS_MOCK=1` 在 Mock/AI2-THOR 模式间无缝切换
   - NanoBot 配置中通过 `env` 字段传递
