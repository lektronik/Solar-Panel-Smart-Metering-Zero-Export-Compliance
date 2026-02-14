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

    async def handle_mqtt(self, topic: str, payload: str):
        async with self._cache_lock:
            self._cache[topic] = payload
            self._last_update[topic] = time.monotonic()

    def _get(self, topic: str, default: str = "0") -> str:
        return self._cache.get(topic, default)

    def _inv(self, serial: str, path: str, default: str = "0") -> str:
        return self._get(f"{self.opendtu_topic}/{serial}/{path}", default)

    def is_reachable(self, serial: str) -> bool:
        return self._inv(serial, "status/reachable") == "1"

    def get_name(self, serial: str) -> str:
        return self._inv(serial, "name", serial)

    def get_ac_power(self, serial: str) -> float:
        return float(self._inv(serial, "0/power"))

    def get_dc_power(self, serial: str) -> float:
        return float(self._inv(serial, "0/powerdc"))

    def get_total_ac_power(self) -> float:
        return float(self._get(f"{self.opendtu_topic}/ac/power"))

    def get_temperature(self, serial: str) -> float:
        return float(self._inv(serial, "0/temperature"))

    def get_ac_voltage(self, serial: str) -> float:
        return float(self._inv(serial, "0/voltage"))

    def get_ac_current(self, serial: str) -> float:
        return float(self._inv(serial, "0/current"))

    def get_frequency(self, serial: str) -> float:
        return float(self._inv(serial, "0/frequency"))

    def get_power_factor(self, serial: str) -> float:
        return float(self._inv(serial, "0/powerfactor"))

    def get_reactive_power(self, serial: str) -> float:
        return float(self._inv(serial, "0/reactivepower"))

    def get_yield_day(self, serial: str) -> float:
        return float(self._inv(serial, "0/yieldday"))

    def get_yield_total(self, serial: str) -> float:
        return float(self._inv(serial, "0/yieldtotal"))

    def get_efficiency(self, serial: str) -> float:
        ac = self.get_ac_power(serial)
        dc = self.get_dc_power(serial)
        if dc > 0:
            return round(ac / dc * 100, 2)
        return 0.0

    def get_limit_relative(self, serial: str) -> float:
        return float(self._inv(serial, "status/limit_relative"))

    def get_limit_absolute(self, serial: str) -> float:
        return float(self._inv(serial, "status/limit_absolute"))

    def get_last_update(self, serial: str) -> float:
        return float(self._inv(serial, "status/last_update"))

    def get_panel_voltages(self, serial: str) -> list[float]:
        voltages = []
        for ch in range(1, 5):
            v = float(self._inv(serial, f"{ch}/voltage"))
            if v > 0:
                voltages.append(v)
        return voltages

    def get_panel_currents(self, serial: str) -> list[float]:
        currents = []
        for ch in range(1, 5):
            c = float(self._inv(serial, f"{ch}/current", "0"))
            currents.append(c)
        return currents

    def get_panel_powers(self, serial: str) -> list[float]:
        powers = []
        for ch in range(1, 5):
            p = float(self._inv(serial, f"{ch}/power", "0"))
            powers.append(p)
        return powers

    def get_panel_yield_day(self, serial: str) -> list[float]:
        yields = []
        for ch in range(1, 5):
            y = float(self._inv(serial, f"{ch}/yieldday", "0"))
            yields.append(y)
        return yields

    def get_panel_yield_total(self, serial: str) -> list[float]:
        yields = []
        for ch in range(1, 5):
            y = float(self._inv(serial, f"{ch}/yieldtotal", "0"))
            yields.append(y)
        return yields

    def get_panel_irradiation(self, serial: str) -> list[float]:
        irr = []
        for ch in range(1, 5):
            i = float(self._inv(serial, f"{ch}/irradiation", "0"))
            irr.append(i)
        return irr

    def is_producing(self, serial: str) -> bool:
        return self._inv(serial, "status/producing") == "1"

    def is_dtu_online(self) -> bool:
        return self._get(f"{self.opendtu_topic}/dtu/status") == "1"

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
