"""MuJoCo Unitree Go1 quadruped robot adapter."""

from harness.adapters.mujoco_go1.mock_adapter import MockMuJoCoAdapter

try:
    from harness.adapters.mujoco_go1.adapter import MuJoCoAdapter
except ImportError:
    MuJoCoAdapter = None
