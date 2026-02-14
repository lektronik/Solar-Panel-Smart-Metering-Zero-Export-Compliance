import logging
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class MeterReading:
    power: float = 0.0
    voltage: float = 0.0
    current: float = 0.0
    pf: float = 0.0
    reactive: float = 0.0
    total: float = 0.0
    total_returned: float = 0.0


class PowerMeter:
    def __init__(self, ip: str, user: str, password: str,
                 emeter_index: int | None = 0, meter_type: str = "gen1_em"):
        self.ip = ip
        self.user = user
        self.password = password
        self.emeter_index = emeter_index
        self.meter_type = meter_type
        self._timeout = aiohttp.ClientTimeout(total=10)

    async def _get_json(self, path: str) -> dict:
        url = f"http://{self.ip}{path}"
        auth = aiohttp.BasicAuth(self.user, self.password) if self.user else None
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.get(url, auth=auth) as resp:
                return await resp.json()

    async def _get_rpc_json(self, path: str) -> dict:
        url = f"http://{self.ip}/rpc{path}"
        auth = aiohttp.BasicAuth(self.user, self.password) if self.user else None
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.get(url, auth=auth) as resp:
                return await resp.json()

    async def read_watts(self) -> float:
        reading = await self.read_full()
        return reading.power

    async def read_full(self) -> MeterReading:
        readers = {
            "gen1_em": self._read_em_full,
            "gen1_3em": self._read_3em_full,
            "gen2_3em_pro": self._read_3em_pro_full,
            "gen1_1pm": self._read_1pm_full,
            "gen2_plus_1pm": self._read_plus_1pm_full,
            # Legacy aliases
            "shelly_em": self._read_em_full,
            "shelly_3em": self._read_3em_full,
            "shelly_3em_pro": self._read_3em_pro_full,
            "shelly_1pm": self._read_1pm_full,
            "shelly_plus_1pm": self._read_plus_1pm_full,
        }
        reader = readers.get(self.meter_type)
        if not reader:
            raise ValueError(f"Unknown meter type: {self.meter_type}")
        return await reader()

    async def _read_em_full(self) -> MeterReading:
        if self.emeter_index is not None:
            data = await self._get_json(f"/emeter/{self.emeter_index}")
            return MeterReading(
                power=float(data.get("power", 0)),
                voltage=float(data.get("voltage", 0)),
                current=float(data.get("current", 0)),
                pf=float(data.get("pf", 0)),
                reactive=float(data.get("reactive", 0)),
                total=float(data.get("total", 0)),
                total_returned=float(data.get("total_returned", 0)),
            )
        data = await self._get_json("/status")
        total_power = sum(float(e.get("power", 0)) for e in data["emeters"])
        first = data["emeters"][0] if data["emeters"] else {}
        return MeterReading(
            power=total_power,
            voltage=float(first.get("voltage", 0)),
            current=float(first.get("current", 0)),
            pf=float(first.get("pf", 0)),
            reactive=float(first.get("reactive", 0)),
            total=sum(float(e.get("total", 0)) for e in data["emeters"]),
            total_returned=sum(float(e.get("total_returned", 0)) for e in data["emeters"]),
        )

    async def _read_3em_full(self) -> MeterReading:
        data = await self._get_json("/status")
        return MeterReading(
            power=float(data.get("total_power", 0)),
            voltage=float(data.get("emeters", [{}])[0].get("voltage", 0)),
            current=float(data.get("emeters", [{}])[0].get("current", 0)),
            pf=float(data.get("emeters", [{}])[0].get("pf", 0)),
            total=sum(float(e.get("total", 0)) for e in data.get("emeters", [])),
            total_returned=sum(float(e.get("total_returned", 0)) for e in data.get("emeters", [])),
        )

    async def _read_3em_pro_full(self) -> MeterReading:
        data = await self._get_rpc_json("/EM.GetStatus?id=0")
        return MeterReading(
            power=float(data.get("total_act_power", 0)),
            voltage=float(data.get("a_voltage", 0)),
            current=float(data.get("a_current", 0)),
            pf=float(data.get("a_pf", 0)),
            total=float(data.get("total_act", 0)),
            total_returned=float(data.get("total_act_ret", 0)),
        )

    async def _read_1pm_full(self) -> MeterReading:
        data = await self._get_json("/status")
        meter = data.get("meters", [{}])[0]
        return MeterReading(
            power=float(meter.get("power", 0)),
            total=float(meter.get("total", 0)),
        )

    async def _read_plus_1pm_full(self) -> MeterReading:
        data = await self._get_rpc_json("/Switch.GetStatus?id=0")
        return MeterReading(
            power=float(data.get("apower", 0)),
            voltage=float(data.get("voltage", 0)),
            current=float(data.get("current", 0)),
            total=float(data.get("aenergy", {}).get("total", 0)),
        )
