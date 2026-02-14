import os
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_ENV_PATTERN_START = "${"
_ENV_PATTERN_END = "}"


def _resolve_env_vars(value):
    if not isinstance(value, str):
        return value
    result = value
    while _ENV_PATTERN_START in result:
        start = result.index(_ENV_PATTERN_START)
        end = result.index(_ENV_PATTERN_END, start)
        token = result[start + 2 : end]
        parts = token.split(":-", 1)
        env_key = parts[0]
        default = parts[1] if len(parts) > 1 else ""
        resolved = os.environ.get(env_key, default)
        result = result[:start] + resolved + result[end + 1 :]
    return result


def _walk_and_resolve(obj):
    if isinstance(obj, dict):
        return {k: _walk_and_resolve(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_and_resolve(item) for item in obj]
    return _resolve_env_vars(obj)


class Config:
    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name):
        try:
            val = self._data[name]
        except KeyError:
            raise AttributeError(f"Config has no key '{name}'")
        if isinstance(val, dict):
            return Config(val)
        return val

    def get(self, key, default=None):
        val = self._data.get(key, default)
        if isinstance(val, dict):
            return Config(val)
        return val

    @property
    def inverters(self):
        return [Config(inv) for inv in self._data.get("inverters", [])]

    def raw(self):
        return self._data


def load_config(path: str = None) -> Config:
    if path is None:
        path = os.environ.get("CONFIG_PATH", "/app/config.yaml")

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    resolved = _walk_and_resolve(raw)
    logger.info("Loaded config from %s", config_path)
    return Config(resolved)
