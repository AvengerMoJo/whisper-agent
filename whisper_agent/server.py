"""HTTP API for whisper-agent.

Routes:
  GET  /api/status        backend/model overview + effective config
  GET  /api/models        cached whisper model files available on this host
  POST /api/transcribe    JSON {url|path, lang?, model?, task?, backend?,
                                 upload?, filename?} -> transcription + buffer link
  POST /api/transcription raw int16 PCM body  (legacy useful-transformers contract)

Runtime-configurable: per-request fields override the server's base config.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import whisper  # for model listing
from flask import Flask, jsonify, request

from .backends import backend_status
from .config import Config
from .service import transcribe_pcm, transcribe_url

app = Flask(__name__)
app.config["BASE_CFG"] = Config.load()

_lock = threading.Lock()


@app.get("/api/status")
def status():
    cfg = app.config["BASE_CFG"]
    return jsonify({**backend_status(cfg), "config": cfg.snapshot()})


@app.get("/api/models")
def models():
    cache = Path.home() / ".cache/whisper"
    names = sorted(p.stem for p in cache.glob("*.pt")) if cache.exists() else []
    return jsonify({"models": names, "cache_dir": str(cache)})


@app.post("/api/transcribe")
def transcribe():
    with _lock:
        data = request.get_json(force=True)
        if not data or not data.get("url") and not data.get("path"):
            return jsonify({"error": "provide 'url' or 'path'"}), 400
        field_map = {"lang": "src_lang"}
        overrides = {field_map.get(k, k): data[k] for k in (
            "lang", "model", "task", "backend", "device") if k in data}
        cfg = app.config["BASE_CFG"].merge(**overrides)
        source = data.get("url") or data.get("path")
        try:
            result = transcribe_url(
                source, cfg,
                upload=bool(data.get("upload", True)),
                filename=data.get("filename"),
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        result["status"] = "ok"
        return jsonify(result)


@app.post("/api/transcription")
def transcription_legacy():
    """Legacy raw-PCM endpoint (16 kHz mono int16 in the request body)."""
    with _lock:
        array_data = np.frombuffer(request.data, dtype=np.int16)
        if array_data.size == 0:
            return jsonify({"error": "empty PCM body"}), 400
        cfg = app.config["BASE_CFG"]
        try:
            text = transcribe_pcm(array_data, cfg, upload=False)["text"]
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify(result=text)


def run_http(cfg: Config | None = None, host: str | None = None,
             port: int | None = None) -> int:
    cfg = cfg or app.config["BASE_CFG"]
    app.config["BASE_CFG"] = cfg
    host = host or cfg.http_host
    port = port or cfg.http_port
    app.run(host=host, port=port, debug=False)
    return 0