"""Home Assistant adapter."""

from harness.adapters.homeassistant.mock_adapter import MockHomeAssistantAdapter

try:
    from harness.adapters.homeassistant.adapter import HomeAssistantAdapter
except ImportError:
    HomeAssistantAdapter = None
