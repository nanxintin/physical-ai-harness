"""MQTT IoT Smart Home adapter for Physical AI Harness.

Simulates real IoT communication patterns: async messaging, device timeouts,
message delays, OTA states, and batch operations.
"""

from harness.adapters.mqtt_iot.mock_adapter import MockMqttIotAdapter

try:
    from harness.adapters.mqtt_iot.adapter import MqttIotAdapter
except ImportError:
    MqttIotAdapter = None  # type: ignore
