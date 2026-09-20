"""Audio intake: fetch audio from a URL (including the buffer service) and
decode it to 16 kHz mono PCM via ffmpeg."""

from __future__ import annotations

import subprocess
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

from .config import Config


def fetch_to_file(url_or_path: str, tmp_dir: str | None = None) -> Path:
    """Download a URL into a local file, or return the local path unchanged."""
    path = Path(url_or_path)
    if path.exists():
        return path
    tmp = Path(tmp_dir or "/tmp/whisper-agent")
    tmp.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".bin", dir=tmp, delete=False) as fh:
        dst = Path(fh.name)
    req = urllib.request.Request(url_or_path, headers={"User-Agent": "whisper-agent/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp, dst.open("wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    return dst


def _ffmpeg_decode(src: Path, ffmpeg_path: str) -> np.ndarray:
    cmd = [
        ffmpeg_path, "-y", "-loglevel", "error",
        "-i", str(src),
        "-ar", "16000", "-ac", "1", "-f", "s16le", "-c:a", "pcm_s16le", "pipe:1",
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True)
    pcm = np.frombuffer(proc.stdout, dtype=np.int16)
    if pcm.size == 0:
        raise ValueError(f"no audio decoded from {src}")
    return pcm


def load_pcm(url_or_path: str, config: Config) -> np.ndarray:
    src = fetch_to_file(url_or_path, config.tmp_dir)
    return _ffmpeg_decode(src, config.ffmpeg_path)


def load_float(url_or_path: str, config: Config) -> np.ndarray:
    """Return audio as float32 in [-1, 1], the format openai-whisper expects."""
    pcm = load_pcm(url_or_path, config)
    return (pcm.astype(np.float32) / 32768.0).astype(np.float32)