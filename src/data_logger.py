import asyncio
import logging
from datetime import datetime, timezone

from src.config import Config

logger = logging.getLogger(__name__)

try:
    from influxdb_client import Point
    from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
    HAS_INFLUX = True
except ImportError:
    HAS_INFLUX = False


class DataLogger:
    def __init__(self, cfg: Config):
        self._enabled = HAS_INFLUX
        if not HAS_INFLUX:
            logger.warning("influxdb-client not installed, telemetry disabled")
            return

        influx = cfg.influxdb
        self._url = influx.url
        self._token = influx.token
        self._org = influx.org
        self._bucket = influx.bucket
        self._buffer: list = []
        self._lock = asyncio.Lock()
        self._flush_interval = 5
        self._client: InfluxDBClientAsync | None = None

    async def _get_client(self) -> InfluxDBClientAsync:
        if self._client is None:
            self._client = InfluxDBClientAsync(
                url=self._url, token=self._token, org=self._org
            )
        return self._client

    def record(self, measurement: str, fields: dict, tags: dict | None = None):
        if not self._enabled:
            return
        point = Point(measurement)
        point.time(datetime.now(timezone.utc))
        if tags:
            for k, v in tags.items():
                point.tag(k, v)
        for k, v in fields.items():
            point.field(k, v)
        self._buffer.append(point)

    async def flush(self):
        if not self._enabled or not self._buffer:
            return

        async with self._lock:
            batch = self._buffer[:]
            self._buffer.clear()

        try:
            client = await self._get_client()
            write_api = client.write_api()
            await write_api.write(bucket=self._bucket, record=batch)
            logger.debug("Flushed %d data points to InfluxDB", len(batch))
        except Exception:
            logger.exception("InfluxDB write failed, re-buffering %d points", len(batch))
            self._client = None
            async with self._lock:
                self._buffer = batch + self._buffer

    async def run(self):
        while True:
            await asyncio.sleep(self._flush_interval)
            await self.flush()

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None
