import asyncio
import logging
import time

import aiohttp

from src.config import Config

logger = logging.getLogger(__name__)


class OpenDTUAdapter:
    def __init__(self, cfg: Config, inverters: list[Config]):
        self.ip = cfg.opendtu.ip
        self.user = cfg.opendtu.user
        self.password = cfg.opendtu.password
        self.opendtu_topic = cfg.mqtt.opendtu_topic
        self.inverters = inverters
        self._timeout = aiohttp.ClientTimeout(total=10)

        self._cache: dict[str, str] = {}
        self._cache_lock = asyncio.Lock()
        self._last_update: dict[str, float] = {}

    def mqtt_topics(self) -> list[str]:
        topics = [
            f"{self.opendtu_topic}/ac/power",
            f"{self.opendtu_topic}/ac/yieldday",
            f"{self.opendtu_topic}/dtu/status",
        ]
        for inv in self.inverters:
            s = inv.serial
            topics.extend([
                f"{self.opendtu_topic}/{s}/status/reachable",
                f"{self.opendtu_topic}/{s}/status/producing",
                f"{self.opendtu_topic}/{s}/status/limit_relative",
                f"{self.opendtu_topic}/{s}/status/limit_absolute",
                f"{self.opendtu_topic}/{s}/0/power",
                f"{self.opendtu_topic}/{s}/0/temperature",
                f"{self.opendtu_topic}/{s}/0/voltage",
                f"{self.opendtu_topic}/{s}/name",
            ])
            for ch in range(1, 5):
                topics.append(f"{self.opendtu_topic}/{s}/{ch}/voltage")
                topics.append(f"{self.opendtu_topic}/{s}/{ch}/power")
        return topics

    async def handle_mqtt(self, topic: str, payload: str):
        async with self._cache_lock:
            self._cache[topic] = payload
            self._last_update[topic] = time.monotonic()

    def _get(self, topic: str, default: str = "0") -> str:
        return self._cache.get(topic, default)

    def is_reachable(self, serial: str) -> bool:
        key = f"{self.opendtu_topic}/{serial}/status/reachable"
        return self._get(key, "0") == "1"

    def get_name(self, serial: str) -> str:
        key = f"{self.opendtu_topic}/{serial}/name"
        return self._get(key, serial)

    def get_ac_power(self, serial: str) -> float:
        key = f"{self.opendtu_topic}/{serial}/0/power"
        return float(self._get(key, "0"))

    def get_total_ac_power(self) -> float:
        key = f"{self.opendtu_topic}/ac/power"
        return float(self._get(key, "0"))

    def get_temperature(self, serial: str) -> float:
        key = f"{self.opendtu_topic}/{serial}/0/temperature"
        return float(self._get(key, "0"))

    def get_limit_relative(self, serial: str) -> float:
        key = f"{self.opendtu_topic}/{serial}/status/limit_relative"
        return float(self._get(key, "0"))

    def get_limit_absolute(self, serial: str) -> float:
        key = f"{self.opendtu_topic}/{serial}/status/limit_absolute"
        return float(self._get(key, "0"))

    def get_panel_voltages(self, serial: str) -> list[float]:
        voltages = []
        for ch in range(1, 5):
            key = f"{self.opendtu_topic}/{serial}/{ch}/voltage"
            v = float(self._get(key, "0"))
            if v > 0:
                voltages.append(v)
        return voltages

    def get_panel_min_voltage(self, serial: str) -> float:
        voltages = [v for v in self.get_panel_voltages(serial) if v > 5]
        return min(voltages) if voltages else 0.0

    async def set_limit(self, serial: str, limit_watts: int, mqtt_client):
        topic = f"{self.opendtu_topic}/{serial}/cmd/limit_nonpersistent_absolute"
        await mqtt_client.publish(topic, str(limit_watts))
        logger.info("Sent limit %dW to inverter %s via MQTT", limit_watts, serial)

    async def set_power(self, serial: str, on: bool, mqtt_client):
        topic = f"{self.opendtu_topic}/{serial}/cmd/power"
        await mqtt_client.publish(topic, "1" if on else "0")
        logger.info("Sent power %s to inverter %s", "ON" if on else "OFF", serial)

    async def wait_for_limit_ack(self, serial: str, target_w: int,
                                  inverter_watt: int, timeout_s: int = 5) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            current = self.get_limit_absolute(serial)
            margin = inverter_watt * 0.05
            if abs(current - target_w) <= margin:
                logger.info("Inverter %s: limit %dW acknowledged", serial, target_w)
                return True
            await asyncio.sleep(0.5)
        logger.warning("Inverter %s: limit ack timeout", serial)
        return False

    async def check_version_http(self):
        url = f"http://{self.ip}/api/system/status"
        auth = aiohttp.BasicAuth(self.user, self.password)
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(url, auth=auth) as resp:
                    data = await resp.json()
                    ver = data.get("git_hash", "unknown")
                    logger.info("OpenDTU version: %s", ver)
                    return ver
        except Exception:
            logger.warning("Could not check OpenDTU version via HTTP")
            return None
