import logging

import aiohttp

logger = logging.getLogger(__name__)


class ShellyMeter:
    def __init__(self, ip: str, user: str, password: str,
                 emeter_index: int | None = 0, meter_type: str = "shelly_em"):
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
        readers = {
            "shelly_em": self._read_em,
            "shelly_3em": self._read_3em,
            "shelly_3em_pro": self._read_3em_pro,
            "shelly_1pm": self._read_1pm,
            "shelly_plus_1pm": self._read_plus_1pm,
        }
        reader = readers.get(self.meter_type)
        if not reader:
            raise ValueError(f"Unknown meter type: {self.meter_type}")
        return await reader()

    async def _read_em(self) -> float:
        if self.emeter_index is not None:
            data = await self._get_json(f"/emeter/{self.emeter_index}")
            return float(data["power"])
        data = await self._get_json("/status")
        return sum(float(e["power"]) for e in data["emeters"])

    async def _read_3em(self) -> float:
        data = await self._get_json("/status")
        return float(data["total_power"])

    async def _read_3em_pro(self) -> float:
        data = await self._get_rpc_json("/EM.GetStatus?id=0")
        return float(data["total_act_power"])

    async def _read_1pm(self) -> float:
        data = await self._get_json("/status")
        return float(data["meters"][0]["power"])

    async def _read_plus_1pm(self) -> float:
        data = await self._get_rpc_json("/Switch.GetStatus?id=0")
        return float(data["apower"])
