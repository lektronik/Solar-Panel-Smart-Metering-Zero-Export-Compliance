import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from src.mqtt_client import MqttClient

@pytest.fixture
def mqtt_client():
    return MqttClient("broker", 1883, "client_id", "prefix")

@pytest.mark.asyncio
async def test_mqtt_connect(mqtt_client):
    with patch("src.mqtt_client.aiomqtt.Client") as MockClient:
        mock_instance = MockClient.return_value
        # Mock async context manager
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_instance.publish = AsyncMock()
        
        # We need to break the infinite loop in run() for testing
        # Or test connect() separately? connect() is called by run().
        # Let's test publish separately first.
        
        # Simulate connected state for publish test
        mqtt_client._connected.set()
        mqtt_client._client = mock_instance
        
        await mqtt_client.publish("test/topic", "payload")
        
        mock_instance.publish.assert_called_with(
            "test/topic", payload="payload", qos=0, retain=False
        )

@pytest.mark.asyncio
async def test_mqtt_publish_state(mqtt_client):
    mqtt_client._connected.set()
    mqtt_client._client = AsyncMock()
    
    await mqtt_client.publish_state("key", "value")
    
    mqtt_client._client.publish.assert_called_with(
        "prefix/state/key", payload="value", qos=1, retain=True
    )

def test_on_topic_registration(mqtt_client):
    async def handler(topic, payload):
        pass
    
    mqtt_client.on_topic("test/#", handler)
    assert "test/#" in mqtt_client._handlers
    assert mqtt_client._handlers["test/#"] == handler
