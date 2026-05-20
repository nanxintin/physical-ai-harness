# Physical AI Harness — 项目路标

## 愿景

从小米现有的 Agentic AI 能力出发，构建面向 Physical AI 的开源硬件 Harness 框架。短期聚焦 IoT 智能设备的 Agent 编排（仿真验证），中期深耕 IoT 产业生态，长期扩展到机器人和智能驾驶。

---

## Phase 0: MVP Demo（当前 ✅）

**时间**：Week 1  
**状态**：已完成

| 交付物 | 状态 |
|--------|------|
| 核心模型（CDD / DeviceState / SafetyLevel） | ✅ |
| 四级安全沙箱 | ✅ |
| 异步事件总线 | ✅ |
| AI2-THOR 适配器（设备发现 + 属性控制 + 图像捕获） | ✅ |
| MCP Server（7 个工具，stdio 传输） | ✅ |
| NanoBot 集成配置 | ✅ |
| Gradio Demo WebUI | ✅ |
| GitHub 仓库 | ✅ |

---

## Phase 1: 端到端验证（Week 2-3）

**目标**：在 WSL2/Linux 上跑通完整的 Agent → Harness → AI2-THOR 闭环

| 任务 | 优先级 | 说明 |
|------|--------|------|
| AI2-THOR 渲染环境搭建 | P0 | 解决 WSL2 下 X server / CloudRendering 问题 |
| NanoBot 端到端联调 | P0 | 验证 `bot.run("turn on the lamp")` 完整流程 |
| Demo 视频录制 | P0 | 3 个核心场景：感知/控制/多设备编排 |
| 错误处理完善 | P1 | 设备不存在/场景未加载/超时等边界情况 |
| 单元测试 | P1 | 覆盖 models、safety、adapter mock |

**Go/No-Go 标准**：Agent 能在 3 轮对话内完成"查询设备 → 控制设备 → 确认结果"

---

## Phase 2: 多设备编排（Week 4-6）

**目标**：展示 Agent 的复杂推理能力——多设备联动、条件触发、场景编排

| 任务 | 优先级 | 说明 |
|------|--------|------|
| TaskScheduler 实现 | P0 | 支持 Sequential/Parallel/Conditional/Event-Triggered 四种策略 |
| 多设备场景 Demo | P0 | "我要睡觉了" → 关灯+关电视+调空调+关窗帘 |
| 事件订阅机制 | P1 | subscribe_event → 条件满足时自动触发 |
| Agent 记忆集成 | P1 | 跨 turn 记住设备状态和用户偏好 |
| 场景模板系统 | P2 | 预定义"回家""睡觉""离家"等场景 |

---

## Phase 3: 四足机器人集成（Week 7-10）

**目标**：通过 MuJoCo 仿真加入四足机器人，展示跨设备类型的统一编排

| 任务 | 优先级 | 说明 |
|------|--------|------|
| MuJoCo Adapter 实现 | P0 | Unitree Go1 四足：move_to/read_sensor/invoke_action |
| 跨平台编排 Demo | P0 | 机器人巡逻 + IoT 设备联动 |
| Robotics CDD 设计 | P1 | 扩展 Capability Model 支持 move_to/stream_data |
| 安全等级扩展 | P1 | 机器人操作默认 CRITICAL，需确认 |
| 统一 WebUI | P2 | 双窗口：AI2-THOR 场景 + MuJoCo 机器人 |

---

## Phase 4: 产品化就绪（Month 3-4）

**目标**：从 Demo 走向可用的开发者工具

| 任务 | 优先级 | 说明 |
|------|--------|------|
| Adapter SDK + CLI 脚手架 | P0 | `harness new-adapter` 一键生成模板 |
| CDD 自动生成工具 | P0 | 从小米 IoT 云 / AI2-THOR 元数据自动生成 |
| 文档网站 | P0 | API Reference + Tutorial + Architecture Guide |
| Benchmark 数据集 | P1 | SmartHome-Bench：标准任务 + 评测指标 |
| Docker 一键部署 | P1 | `docker-compose up` 含 AI2-THOR + MCP Server |
| CI/CD Pipeline | P1 | GitHub Actions + 自动测试 + 发版 |

---

## Phase 5: 开源发布（Month 5-6）

**目标**：正式开源，建立社区

| 任务 | 优先级 | 说明 |
|------|--------|------|
| Apache 2.0 许可证 | P0 | 含专利授权保护 |
| 开源 README + CONTRIBUTING | P0 | 贡献指南 + Code of Conduct |
| 种子开发者网络 | P0 | 3-5 名研究者 + 5-10 名 IoT 从业者 |
| 技术博客首发 | P0 | 架构解析文章 |
| CDD 设备库独立仓库 | P1 | 800+ 品类设备描述 |
| Good First Issues | P1 | 20+ 标注好的入门任务 |

**Go/No-Go 标准**：Star 基线 300+，种子开发者留存率 > 40%

---

## Phase 6: 生态扩展（Month 7+）

| 方向 | 内容 |
|------|------|
| 真实设备接入 | MIIO 协议适配器（Wi-Fi 设备）+ BLE Mesh 适配器 |
| 厂商合作 | Aqara / Yeelight / Roborock 创始合作伙伴 |
| 学术合作 | 联合论文 + ICRA/NeurIPS Workshop |
| 标准化 | 向 W3C WoT 提交 CDD 规范参考 |
| 智能驾驶 | SU7 座舱控制适配器（非安全关键场景） |

---

## 成功指标

| 阶段 | 指标 | 基线 | 目标 | 挑战 |
|------|------|------|------|------|
| Phase 1 | 端到端成功率 | 60% | 85% | 95% |
| Phase 2 | 多设备编排 Demo 数量 | 3 | 5 | 10 |
| Phase 3 | 跨平台设备类型 | 1 (IoT) | 2 (+Robot) | 3 (+Vehicle) |
| Phase 5 | GitHub Star | 300 | 1000 | 2000 |
| Phase 5 | 外部贡献者 | 3 | 10 | 30 |
| Phase 6 | 真实设备品类 | 2 | 10 | 50 |

---

## 技术债务跟踪

| 项目 | 当前状态 | 计划解决 |
|------|---------|---------|
| AI2-THOR 阻塞调用 | asyncio.to_thread 临时方案 | Phase 2 考虑多进程 |
| 图像传输 | base64 文本（大且慢） | Phase 4 改为文件路径或流式 |
| MCP Server 单例 | 全局 adapter 实例 | Phase 4 重构为多场景并发 |
| 无持久化 | 设备状态内存中 | Phase 2 加入 SQLite |
| 无认证 | MCP stdio 本地可信 | Phase 5 加入 token 认证 |
