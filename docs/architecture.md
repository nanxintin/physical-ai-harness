# Physical AI Harness — System Architecture

![Physical AI Harness Architecture](architecture.png)

<details>
<summary>View source HTML (for Markdown Viewer rendering)</summary>

<div style="width: 1200px; box-sizing: border-box; position: relative; background: #0f172a; padding: 20px; border-radius: 12px;">
  <style scoped>
    .arch-wrapper { display: flex; gap: 12px; }.arch-sidebar { width: 165px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #f1f5f9; margin-bottom: 4px; letter-spacing: 1px; }.arch-subtitle { text-align: center; font-size: 12px; color: #94a3b8; margin-bottom: 16px; }
    .arch-layer { margin: 8px 0; padding: 14px; border-radius: 8px; }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }
    .arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-grid-6 { grid-template-columns: repeat(6, 1fr); }
    .arch-box { border-radius: 6px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #e2e8f0; background: rgba(30, 41, 59, 0.8); border: 1px solid rgba(148, 163, 184, 0.2); }.arch-box.highlight { background: rgba(250, 204, 21, 0.15); border: 1px solid #facc15; color: #fef08a; }.arch-box.tech { font-size: 10px; color: #94a3b8; background: rgba(15, 23, 42, 0.6); }
    .arch-layer.external { background: rgba(51, 65, 85, 0.3); border: 1px dashed #475569; }.arch-layer.external .arch-layer-title { color: #94a3b8; }.arch-layer.user { background: rgba(14, 165, 233, 0.1); border: 1px solid #0ea5e9; box-shadow: 0 0 12px rgba(14, 165, 233, 0.15); }.arch-layer.user .arch-layer-title { color: #7dd3fc; }.arch-layer.application { background: rgba(245, 158, 11, 0.1); border: 1px solid #f59e0b; box-shadow: 0 0 12px rgba(245, 158, 11, 0.15); }.arch-layer.application .arch-layer-title { color: #fcd34d; }.arch-layer.ai { background: rgba(16, 185, 129, 0.1); border: 1px solid #10b981; box-shadow: 0 0 12px rgba(16, 185, 129, 0.15); }.arch-layer.ai .arch-layer-title { color: #6ee7b7; }.arch-layer.data { background: rgba(236, 72, 153, 0.1); border: 1px solid #ec4899; box-shadow: 0 0 12px rgba(236, 72, 153, 0.15); }.arch-layer.data .arch-layer-title { color: #f9a8d4; }.arch-layer.infra { background: rgba(139, 92, 246, 0.1); border: 1px solid #8b5cf6; box-shadow: 0 0 12px rgba(139, 92, 246, 0.15); }.arch-layer.infra .arch-layer-title { color: #c4b5fd; }
    .arch-sidebar-panel { border-radius: 8px; padding: 10px; background: rgba(30, 41, 59, 0.6); border: 1px solid #334155; margin-bottom: 8px; }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #94a3b8; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #cbd5e1; background: rgba(15, 23, 42, 0.5); padding: 5px; border-radius: 4px; margin: 3px 0; border: 1px solid rgba(51, 65, 85, 0.5); }.arch-sidebar-item.metric { background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #6ee7b7; font-weight: 600; }
    .arch-subgroup { display: flex; gap: 8px; margin-top: 8px; }.arch-subgroup-box { flex: 1; border-radius: 6px; padding: 8px; background: rgba(15, 23, 42, 0.4); border: 1px solid rgba(148, 163, 184, 0.1); }.arch-subgroup-title { font-size: 10px; font-weight: bold; color: #94a3b8; text-align: center; margin-bottom: 6px; }
  </style>
  <div class="arch-title">Physical AI Harness</div>
  <div class="arch-subtitle">Let AI Agents perceive and control any physical device through a unified interface</div>
  <div class="arch-wrapper">
    <div class="arch-sidebar">
      <div class="arch-sidebar-panel"><div class="arch-sidebar-title">Training Pipeline</div><div class="arch-sidebar-item">Rollout Engine</div><div class="arch-sidebar-item">Trajectory Collector</div><div class="arch-sidebar-item">Reward Functions</div><div class="arch-sidebar-item">Parquet Export</div><div class="arch-sidebar-item metric">VERL GRPO</div></div>
      <div class="arch-sidebar-panel"><div class="arch-sidebar-title">Testing</div><div class="arch-sidebar-item metric">395 Tests Passed</div><div class="arch-sidebar-item">Mock Backends</div><div class="arch-sidebar-item">Real Integration</div><div class="arch-sidebar-item">E2E Agent Demo</div></div>
      <div class="arch-sidebar-panel"><div class="arch-sidebar-title">DevOps</div><div class="arch-sidebar-item">EGL Headless</div><div class="arch-sidebar-item">CI/CD Ready</div><div class="arch-sidebar-item">Docker Deploy</div></div>
    </div>
    <div class="arch-main">
      <div class="arch-layer user">
        <div class="arch-layer-title">Layer 3 — AI Agent Interface</div>
        <div class="arch-grid arch-grid-4"><div class="arch-box highlight">Claude Code<br><small>MCP Native</small></div><div class="arch-box">GPT / OpenAI<br><small>Function Calling</small></div><div class="arch-box">Qwen3-8B<br><small>vLLM Server</small></div><div class="arch-box">Any LLM Agent<br><small>Model-Agnostic</small></div></div>
      </div>
      <div class="arch-layer application">
        <div class="arch-layer-title">Layer 2 — Harness Core (MCP Server + FastMCP)</div>
        <div class="arch-grid arch-grid-3"><div class="arch-box highlight">MCP Server<br><small>stdio / SSE transport</small></div><div class="arch-box">Event Bus<br><small>async pub/sub</small></div><div class="arch-box">CDD Model<br><small>Capability Description</small></div></div>
        <div class="arch-subgroup">
          <div class="arch-subgroup-box">
            <div class="arch-subgroup-title">Universal Tools (7)</div>
            <div class="arch-grid arch-grid-4"><div class="arch-box tech">scene_load</div><div class="arch-box tech">devices_list</div><div class="arch-box tech">device_state</div><div class="arch-box tech">device_control</div></div>
            <div class="arch-grid arch-grid-3" style="margin-top:6px;"><div class="arch-box tech">scene_capture</div><div class="arch-box tech">scene_describe</div><div class="arch-box tech">events_history</div></div>
          </div>
          <div class="arch-subgroup-box">
            <div class="arch-subgroup-title">Robot Tools (3)</div>
            <div class="arch-grid arch-grid-3"><div class="arch-box tech">robot_move</div><div class="arch-box tech">robot_joints</div><div class="arch-box tech">robot_sensors</div></div>
          </div>
        </div>
      </div>
      <div class="arch-layer ai">
        <div class="arch-layer-title">Layer 1 — Adapter Layer (11 Pluggable Backends)</div>
        <div class="arch-subgroup">
          <div class="arch-subgroup-box">
            <div class="arch-subgroup-title">Robotics</div>
            <div class="arch-grid arch-grid-2"><div class="arch-box">MuJoCo<br><small>Unitree Go1</small></div><div class="arch-box">PyBullet<br><small>Franka Panda</small></div></div>
            <div class="arch-grid arch-grid-2" style="margin-top:6px;"><div class="arch-box">Gazebo<br><small>TurtleBot3</small></div><div class="arch-box">Webots<br><small>e-puck</small></div></div>
          </div>
          <div class="arch-subgroup-box">
            <div class="arch-subgroup-title">IoT & Smart Home</div>
            <div class="arch-grid arch-grid-2"><div class="arch-box">AI2-THOR<br><small>120+ rooms</small></div><div class="arch-box">VirtualHome<br><small>graph engine</small></div></div>
            <div class="arch-grid arch-grid-2" style="margin-top:6px;"><div class="arch-box">MQTT IoT<br><small>pub/sub protocol</small></div><div class="arch-box">Home Assistant<br><small>12 entities</small></div></div>
          </div>
          <div class="arch-subgroup-box">
            <div class="arch-subgroup-title">AV & Sensing</div>
            <div class="arch-grid arch-grid-1"><div class="arch-box">SUMO<br><small>TraCI traffic</small></div></div>
            <div class="arch-grid arch-grid-1" style="margin-top:6px;"><div class="arch-box">Scenic<br><small>CARLA AV</small></div></div>
            <div class="arch-grid arch-grid-1" style="margin-top:6px;"><div class="arch-box">Wearable<br><small>health sensors</small></div></div>
          </div>
        </div>
      </div>
      <div class="arch-layer infra">
        <div class="arch-layer-title">Layer 0 — Simulation Engines & Protocols</div>
        <div class="arch-grid arch-grid-6"><div class="arch-box tech">Unity<br><small>AI2-THOR</small></div><div class="arch-box tech">MuJoCo 3.8<br><small>Physics</small></div><div class="arch-box tech">Bullet 3.2<br><small>Dynamics</small></div><div class="arch-box tech">gz-sim<br><small>ROS2</small></div><div class="arch-box tech">SUMO 1.27<br><small>TraCI</small></div><div class="arch-box tech">CARLA<br><small>Scenic</small></div></div>
        <div class="arch-grid arch-grid-4" style="margin-top:6px;"><div class="arch-box tech">Webots R2025a<br><small>e-puck SDK</small></div><div class="arch-box tech">MQTT Broker<br><small>paho-mqtt</small></div><div class="arch-box tech">HA REST API<br><small>Home Asst.</small></div><div class="arch-box tech">BLE / Zigbee<br><small>Future</small></div></div>
      </div>
      <div class="arch-layer external">
        <div class="arch-layer-title">External — Physical & Simulated Devices</div>
        <div class="arch-grid arch-grid-5"><div class="arch-box tech">Quadruped Robot<br><small>12 DOF joints</small></div><div class="arch-box tech">Robot Arm<br><small>7 DOF + gripper</small></div><div class="arch-box tech">Smart Home<br><small>600+ objects</small></div><div class="arch-box tech">Vehicles<br><small>traffic flow</small></div><div class="arch-box tech">Wearables<br><small>HR/SpO2/steps</small></div></div>
      </div>
    </div>
    <div class="arch-sidebar">
      <div class="arch-sidebar-panel"><div class="arch-sidebar-title">Safety Sandbox</div><div class="arch-sidebar-item" style="background:rgba(34,197,94,0.15);border-color:rgba(34,197,94,0.4);color:#86efac;">LOW — Lamps, TVs</div><div class="arch-sidebar-item" style="background:rgba(234,179,8,0.15);border-color:rgba(234,179,8,0.4);color:#fde047;">MEDIUM — Fridge</div><div class="arch-sidebar-item" style="background:rgba(239,68,68,0.15);border-color:rgba(239,68,68,0.4);color:#fca5a5;">HIGH — Stove, Joints</div><div class="arch-sidebar-item" style="background:rgba(168,85,247,0.15);border-color:rgba(168,85,247,0.4);color:#d8b4fe;">CRITICAL — E-stop</div></div>
      <div class="arch-sidebar-panel"><div class="arch-sidebar-title">Protocol</div><div class="arch-sidebar-item">MCP stdio</div><div class="arch-sidebar-item">MCP SSE</div><div class="arch-sidebar-item">Python SDK</div><div class="arch-sidebar-item">Gradio WebUI</div></div>
      <div class="arch-sidebar-panel"><div class="arch-sidebar-title">Metrics</div><div class="arch-sidebar-item metric">11 Backends</div><div class="arch-sidebar-item metric">10 MCP Tools</div><div class="arch-sidebar-item metric">5 Real Tests</div><div class="arch-sidebar-item metric">Apache 2.0</div></div>
    </div>
  </div>
</div>
</details>
