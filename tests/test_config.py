import os
import pytest
from src.config import Config, load_config, _resolve_env_vars, _walk_and_resolve

def test_resolve_env_vars():
    os.environ["TEST_VAR"] = "123"
    assert _resolve_env_vars("val_${TEST_VAR}") == "val_123"
    assert _resolve_env_vars("val_${MISSING:-default}") == "val_default"
    assert _resolve_env_vars("val_${MISSING}") == "val_"
    assert _resolve_env_vars("no_var") == "no_var"

def test_walk_and_resolve():
    os.environ["TEST_VAR"] = "xyz"
    data = {"key": "val_${TEST_VAR}", "list": ["${TEST_VAR}"]}
    resolved = _walk_and_resolve(data)
    assert resolved["key"] == "val_xyz"
    assert resolved["list"][0] == "xyz"

def test_config_class():
    data = {"a": 1, "b": {"c": 2}, "inverters": [{"serial": "123"}]}
    cfg = Config(data)
    assert cfg.a == 1
    assert cfg.b.c == 2
    assert cfg.get("a") == 1
    assert cfg.get("b").c == 2
    assert cfg.inverters[0].serial == "123"
    
    with pytest.raises(AttributeError):
        _ = cfg.missing

def test_load_config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("key: value\nsub:\n  k: v")
    
    cfg = load_config(str(config_file))
    assert cfg.key == "value"
    assert cfg.sub.k == "v"

def test_load_config_missing():
    with pytest.raises(FileNotFoundError):
        load_config("non_existent.yaml")
