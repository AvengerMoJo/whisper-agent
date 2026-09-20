"""Orchestration: URL or local file -> PCM -> backend transcribe -> buffer upload."""

from __future__ import annotations

from typing import Any

from . import audio
from .backends import transcribe
from .buffer import BufferClient
from .config import Config


def transcribe_url(url_or_path: str, config: Config,
                   upload: bool = True, filename: str | None = None) -> dict[str, Any]:
    """Transcribe audio at a URL (buffer link) or a local file path.

    Returns the transcription plus, when upload=True, a fresh buffer link for
    the resulting text so the caller/MoJoAssistant can point at it later.
    """
    audio_float = audio.load_float(url_or_path, config)
    result = transcribe(audio_float, config)
    result["source"] = url_or_path
    if upload:
        result["buffer_link"] = _push_result(result, config, filename)
    return result


def transcribe_pcm(pcm_int16: Any, config: Config,
                   upload: bool = True, filename: str | None = None) -> dict[str, Any]:
    """Transcribe raw int16 PCM (16 kHz mono) without touching the filesystem."""
    import numpy as np
    arr = np.asarray(pcm_int16)
    if arr.dtype != np.int16:
        raise ValueError(f"expected int16 PCM, got {arr.dtype}")
    audio_float = (arr.astype(np.float32) / 32768.0).astype(np.float32)
    result = transcribe(audio_float, config)
    if upload:
        result["buffer_link"] = _push_result(result, config, filename)
    return result


def _push_result(result: dict[str, Any], config: Config,
                 filename: str | None) -> str:
    name = filename or BufferClient(config.buffer_base_url).make_default_filename(
        result.get("language"), result.get("model") or config.model)
    client = BufferClient(config.buffer_base_url)
    payload = client.upload_text(result["text"], name, config.buffer_mime_type)
    link = payload.get("link") or payload.get("url") or payload.get("buffer_url")
    if not link:
        raise ValueError(f"buffer upload returned no link: {payload}")
    return link