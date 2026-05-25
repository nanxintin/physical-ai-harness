"""SUMO traffic simulation adapter."""

from harness.adapters.sumo.mock_adapter import MockSUMOAdapter

try:
    from harness.adapters.sumo.adapter import SUMOAdapter
except ImportError:
    SUMOAdapter = None
