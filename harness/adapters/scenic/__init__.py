"""Scenic autonomous driving scenario adapter."""

from harness.adapters.scenic.mock_adapter import MockScenicAdapter

try:
    from harness.adapters.scenic.adapter import ScenicAdapter
except ImportError:
    ScenicAdapter = None
