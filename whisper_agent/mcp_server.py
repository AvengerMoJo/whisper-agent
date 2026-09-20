"""MCP server for whisper-agent.

Exposes transcription as MCP tools so MoJoAssistant (and any MCP client) can
transcribe audio directly:
  - transcribe_url(url, lang?, model?, task?, backend?, upload?) -> text + buffer link
  - status() -> backend/model/hardware overview
  - list_models() -> cached whisper models on this host

Transport: streamable HTTP (run via `whisper-agent mcp`). Runtime-configurable
per call; base config comes from config file / env.
"""

from __future__ import annotations

import json

from .backends import backend_status
from .config import Config
from .service import transcribe_url

_cfg_holder = {"cfg": None}


def _cfg() -> Config:
    if _cfg_holder["cfg"] is None:
        _cfg_holder["cfg"] = Config.load()
    return _cfg_holder["cfg"]


def _build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("whisper-agent")

    @mcp.tool()
    def transcribe_url_tool(
        url: str,
        lang: str | None = None,
        model: str | None = None,
        task: str | None = None,
        backend: str | None = None,
        device: str | None = None,
        upload: bool = True,
    ) -> dict:
        """Transcribe audio from a URL (e.g. a buffer link) or a local path.

        Returns the transcription text, detected language, backend used and the
        buffer link to the resulting text file (when upload=True).
        """
        cfg = _cfg().merge(src_lang=lang, model=model, task=task,
                           backend=backend, device=device)
        return transcribe_url(url, cfg, upload=upload)

    @mcp.tool()
    def status() -> dict:
        """Report which backends are available, the active backend/device/model,
        and the effective runtime config."""
        cfg = _cfg()
        return backend_status(cfg)

    @mcp.tool()
    def list_models() -> dict:
        """List whisper model files cached on this host."""
        from pathlib import Path
        cache = Path.home() / ".cache/whisper"
        names = sorted(p.stem for p in cache.glob("*.pt")) if cache.exists() else []
        return {"models": names, "cache_dir": str(cache)}

    return mcp


def run_mcp(cfg: Config | None = None, host: str | None = None,
            port: int | None = None) -> int:
    cfg = cfg or Config.load()
    _cfg_holder["cfg"] = cfg
    mcp = _build_server()
    mcp.settings.host = host or cfg.mcp_host
    mcp.settings.port = port or cfg.mcp_port
    mcp.settings.streamable_http_path = "/mcp"
    mcp.run(transport="streamable-http")
    return 0