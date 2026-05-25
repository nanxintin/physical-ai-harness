"""Wearable sensor stream adapter."""

from harness.adapters.wearable.mock_adapter import MockWearableAdapter

try:
    from harness.adapters.wearable.adapter import WearableAdapter
except ImportError:
    WearableAdapter = None
