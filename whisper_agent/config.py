"""Runtime configuration for whisper-agent.

Layering (lowest -> highest precedence):
  1. Built-in defaults
  2. Config file  (JSON) at $WHISPER_AGENT_CONFIG or ~/.config/whisper-agent/config.json
  3. Environment  WHISPER_AGENT_<KEY> (uppercase, underscores)
  4. Runtime overrides passed to .merge()  (from CLI flags / HTTP / MCP params)

All keys are surfaced as attributes on the Config dataclass, so backends and
servers read a living snapshot and can be reconfigured without a restart.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
from pathlib import Path
from typing import Any

CONFIG_FILE_ENV = "WHISPER_AGENT_CONFIG"
CONFIG_FILE_DEFAULT = Path.home() / ".config/whisper-agent/config.json"

DEFAULTS: dict[str, Any] = {
    # model / language / task
    "model": "base",            # openai-whisper model name (base, medium, large-v3, tiny.en, ...)
    "src_lang": "zh",           # source language; "auto" -> detect from audio
    "task": "transcribe",       # "transcribe" or "translate" (to English)
    # backend selection
    "backend": "auto",          # "auto" | "torch" | "cpp" | "rknn"
    "device": "auto",           # "auto" | "cuda" | "cpu"  (used by torch backend)
    "keep_warm": True,          # keep the model loaded between requests
    # decode behaviour
    "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    "condition_on_previous_text": True,
    # buffer service (the MCP-backed scratch store we read audio from / write text to)
    "buffer_base_url": "https://buffer.eclipsogate.org",
    "buffer_mime_type": "text/plain",
    # network
    "http_host": "127.0.0.1",
    "http_port": 5000,
    "mcp_host": "127.0.0.1",
    "mcp_port": 8820,
    # filesystem
    "ffmpeg_path": "ffmpeg",
    "tmp_dir": "/tmp/whisper-agent",
    # useful-transformers C++ engine location (for backend="cpp")
    "cpp_repo": str(Path.home() / "Development/Personal/useful-transformers"),
}


def _env_prefix() -> str:
    return "WHISPER_AGENT_"


@dataclasses.dataclass
class Config:
    values: dict[str, Any] = dataclasses.field(default_factory=lambda: copy.deepcopy(DEFAULTS))

    # ---- accessors ---------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.values[key] = value

    def __getattr__(self, key: str) -> Any:
        vals = self.__dict__["values"]
        if key in vals:
            return vals[key]
        raise AttributeError(key)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.values)

    def merge(self, **overrides: Any) -> "Config":
        """Apply runtime overrides in place (highest precedence). Returns self."""
        for k, v in overrides.items():
            if v is None:
                continue
            if k == "temperature" and isinstance(v, (int, float)):
                v = [float(v)]
            self.values[k] = v
        return self

    def to_json(self) -> str:
        return json.dumps(self.values, indent=2, ensure_ascii=False)

    # ---- loading -----------------------------------------------------------
    @classmethod
    def load(cls, overrides: dict[str, Any] | None = None) -> "Config":
        cfg = cls()

        file_path = cls._config_file_path()
        if file_path and file_path.exists():
            try:
                data = json.loads(file_path.read_text())
                if isinstance(data, dict):
                    cfg.values.update(data)
            except (OSError, ValueError) as exc:
                print(f"whisper-agent: ignoring invalid config file {file_path}: {exc}")

        prefix = _env_prefix()
        for key in list(DEFAULTS):
            env_key = f"{prefix}{key.upper()}"
            if env_key in os.environ:
                cfg.values[key] = _coerce(DEFAULTS[key], os.environ[env_key])

        if overrides:
            cfg.merge(**overrides)
        return cfg

    @staticmethod
    def _config_file_path() -> Path | None:
        env = os.environ.get(CONFIG_FILE_ENV)
        if env:
            return Path(env)
        return CONFIG_FILE_DEFAULT

    def save(self, path: Path | None = None) -> Path:
        target = path or self._config_file_path()
        if target is None:
            raise ValueError("no config file path configured")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json())
        return target


def _coerce(default: Any, raw: str) -> Any:
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, list):
        try:
            return json.loads(raw)
        except ValueError:
            return [x.strip() for x in raw.split(",") if x.strip()]
    return raw