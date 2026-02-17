import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from src.data_logger import DataLogger
from src.config import Config

@pytest.fixture
def logger_config():
    return Config({
        "influxdb": {
            "url": "http://localhost:8086",
            "token": "token",
            "org": "org",
            "bucket": "bucket"
        }
    })

@pytest.fixture
def data_logger(logger_config):
    with patch("src.data_logger.HAS_INFLUX", True):
        logger = DataLogger(logger_config)
        yield logger

@pytest.mark.asyncio
async def test_record_and_flush(data_logger):
    # Mock InfluxDBClient
    with patch("src.data_logger.InfluxDBClientAsync") as MockClient:
        mock_client_instance = MockClient.return_value
        mock_write_api = AsyncMock()
        mock_client_instance.write_api.return_value = mock_write_api
        
        # Record some data
        data_logger.record("measurement", {"field": 1}, {"tag": "val"})
        
        assert len(data_logger._buffer) == 1
        
        # Flush
        await data_logger.flush()
        
        # Buffer should be empty
        assert len(data_logger._buffer) == 0
        
        # Write API called
        mock_write_api.write.assert_called_once()
        args, kwargs = mock_write_api.write.call_args
        assert kwargs["bucket"] == "bucket"
        assert len(kwargs["record"]) == 1

@pytest.mark.asyncio
async def test_flush_exception_rebuffering(data_logger):
    with patch("src.data_logger.InfluxDBClientAsync") as MockClient:
        mock_client_instance = MockClient.return_value
        mock_write_api = AsyncMock()
        mock_write_api.write.side_effect = Exception("Influx Error")
        mock_client_instance.write_api.return_value = mock_write_api
        
        data_logger.record("measurement", {"field": 1})
        
        # Flush should fail and re-buffer
        await data_logger.flush()
        
        assert len(data_logger._buffer) == 1
        assert data_logger._client is None
