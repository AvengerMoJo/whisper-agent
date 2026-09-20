import pytest

from whisper_agent.config import Config


def test_load_defaults():
    cfg = Config.load()
    assert cfg.model == "base"
    assert cfg.src_lang == "zh"
    assert cfg.backend == "auto"
    assert cfg.device == "auto"


def test_env_override(monkeypatch):
    monkeypatch.setenv("WHISPER_AGENT_MODEL", "medium")
    monkeypatch.setenv("WHISPER_AGENT_SRC_LANG", "auto")
    cfg = Config.load()
    assert cfg.model == "medium"
    assert cfg.src_lang == "auto"


def test_merge_temperature_scalar():
    cfg = Config.load()
    cfg.merge(temperature=0.5)
    assert cfg.temperature == [0.5]


def test_config_snapshot_immutable():
    cfg = Config.load()
    snap = cfg.snapshot()
    snap["model"] = "medium"
    assert cfg.model == "base"