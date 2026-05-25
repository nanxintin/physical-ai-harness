# Physical AI Harness — Roadmap

## Vision

Build an open-source hardware orchestration framework for Physical AI. Short-term: IoT device orchestration via simulation. Mid-term: real device protocols and ecosystem partnerships. Long-term: robotics and autonomous vehicle integration.

---

## Phase 0: MVP Demo ✅

**Timeline**: Week 1  
**Status**: Complete

| Deliverable | Status |
|-------------|--------|
| Core models (CDD / DeviceState / SafetyLevel) | ✅ |
| 4-level safety sandbox | ✅ |
| Async event bus | ✅ |
| AI2-THOR adapter (device discovery + property control + image capture) | ✅ |
| MCP Server (7 tools, stdio transport) | ✅ |
| Agent integration config | ✅ |
| Gradio Demo WebUI | ✅ |

---

## Phase 1: End-to-End Validation ✅

**Timeline**: Week 2-3  
**Goal**: Full Agent → Harness → Simulation loop running on WSL2/Linux

| Task | Priority | Status |
|------|----------|--------|
| AI2-THOR rendering setup (WSL2 X server / CloudRendering) | P0 | ✅ |
| End-to-end agent integration test | P0 | ✅ |
| Error handling (device not found / scene not loaded / timeout) | P1 | ✅ |
| Unit tests (36/36 passed) | P1 | ✅ |

---

## Phase 2: Multi-Device Orchestration ✅

**Timeline**: Week 4-6  
**Goal**: Complex multi-device scenarios and cross-backend adapters

| Task | Priority | Status |
|------|----------|--------|
| VirtualHome adapter (CPU-based, 314 object classes) | P0 | ✅ |
| Multi-device batch control | P0 | ✅ |
| Event subscription mechanism | P1 | ✅ |

---

## Phase 3: Quadruped Robot Integration ✅

**Timeline**: Week 7-10  
**Goal**: MuJoCo-based robot adapter, demonstrating cross-device-type orchestration

| Task | Priority | Status |
|------|----------|--------|
| MuJoCoAdapter (real physics simulation) | P0 | ✅ |
| MockMuJoCoAdapter (GPU-free testing) | P0 | ✅ |
| CDD design: 25 capabilities (joints + sensors + actions) | P0 | ✅ |
| Safety levels for robot operations | P0 | ✅ |
| Robot MCP tools (robot_move, robot_joints, robot_sensors) | P0 | ✅ |
| Gait controller (sinusoidal open-loop) | P1 | ✅ |
| Full test coverage (49 + 28 tests passed, E2E demo) | P1 | ✅ |
| Cross-platform orchestration demo (robot + IoT) | P1 | 🔜 |
| Unified WebUI (dual-pane: AI2-THOR + MuJoCo) | P2 | 🔜 |

---

## Phase 4: Production Ready (Month 3-4)

**Goal**: From demo to usable developer tooling

| Task | Priority |
|------|----------|
| Adapter SDK + CLI scaffolding (`harness new-adapter`) | P0 |
| CDD auto-generation tool (from platform metadata) | P0 |
| Documentation website (API Reference + Tutorials) | P0 |
| SmartHome-Bench: standardized benchmark dataset | P1 |
| Docker one-click deployment | P1 |
| CI/CD pipeline (GitHub Actions + auto-test + release) | P1 |

---

## Phase 5: Open Source Release (Month 5-6)

**Goal**: Public release and community building

| Task | Priority |
|------|----------|
| Apache 2.0 license + patent grant | P0 |
| README + CONTRIBUTING guide | P0 |
| Seed developer network (researchers + IoT practitioners) | P0 |
| Technical blog series (architecture deep-dives) | P0 |
| CDD device library (800+ categories, separate repo) | P1 |
| Good First Issues (20+ labeled tasks) | P1 |

**Go/No-Go Criteria**: 300+ GitHub stars, seed developer retention > 40%

---

## Phase 6: Ecosystem Expansion (Month 7+)

| Direction | Description |
|-----------|-------------|
| Real device protocols | Wi-Fi / BLE Mesh / Zigbee / Matter adapters |
| Vendor partnerships | IoT ecosystem partners for deep integration |
| Academic collaboration | Joint papers + ICRA/NeurIPS workshop |
| Standardization | W3C WoT submission for CDD spec reference |
| Autonomous vehicles | Cabin control adapter (non-safety-critical) |

---

## Success Metrics

| Phase | Metric | Baseline | Target | Stretch |
|-------|--------|----------|--------|---------|
| Phase 3 | E2E test pass rate | 60% | 85% | 95% |
| Phase 3 | Cross-platform device types | 1 (IoT) | 2 (+Robot) | 3 (+Vehicle) |
| Phase 5 | GitHub Stars | 300 | 1000 | 2000 |
| Phase 5 | External contributors | 3 | 10 | 30 |
| Phase 6 | Real device categories | 2 | 10 | 50 |

---

## Technical Debt Tracker

| Item | Current State | Planned Resolution |
|------|--------------|-------------------|
| AI2-THOR blocking calls | `asyncio.to_thread` workaround | Phase 4: multi-process architecture |
| Image transfer | base64 text (large, slow) | Phase 4: file path or streaming |
| MCP Server singleton | Global adapter instance | Phase 4: multi-scene concurrency |
| No persistence | Device state in-memory only | Phase 4: SQLite backend |
| No authentication | MCP stdio (local trust only) | Phase 5: token-based auth |
| Gait stability | Open-loop sinusoidal (may fall) | Phase 4: PD balance controller |
