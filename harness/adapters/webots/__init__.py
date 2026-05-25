"""Webots R2025a e-puck differential drive robot adapter."""

from harness.adapters.webots.mock_adapter import MockWebotsAdapter

try:
    from harness.adapters.webots.adapter import WebotsAdapter
except ImportError:
    WebotsAdapter = None
