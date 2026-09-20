"""Backend abstraction for transcription.

Backends:
  - "torch"  : openai-whisper on PyTorch, device auto (ROCm/CUDA first, CPU fallback)
  - "cpp"    : useful-transformers C++ engine (CPU-only, experimental)
  - "rknn"   : reserved for RK3588 NPU validation (next week)

`resolve_backend(config)` turns the config's `backend: auto|torch|cpp|rknn`
into a concrete backend, with auto preferring torch-GPU.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from .config import Config


class BackendError(RuntimeError):
    pass


class Backend:
    name: str = "base"

    def transcribe(self, audio_float: np.ndarray, config: Config) -> dict[str, Any]:
        raise NotImplementedError


class TorchBackend(Backend):
    """openai-whisper reference implementation. Best quality; GPU accelerated."""

    name = "torch"

    def __init__(self, device: str = "auto"):
        import whisper  # openai-whisper
        self._whisper = whisper
        self._model_name: str | None = None
        self._model = None
        self._device = self._pick_device(device)

    @staticmethod
    def _pick_device(pref: str) -> str:
        if pref == "cuda":
            return "cuda"
        if pref == "cpu":
            return "cpu"
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _load(self, model_name: str):
        if self._model is not None and self._model_name == model_name:
            return
        self._model = self._whisper.load_model(model_name, device=self._device)
        self._model_name = model_name

    def available(self) -> bool:
        try:
            import torch  # noqa: F401
            return True
        except ImportError:
            return False

    def hardware(self) -> str:
        return self._device

    def transcribe(self, audio_float: np.ndarray, config: Config) -> dict[str, Any]:
        self._load(config.model)
        t0 = time.time()
        lang = config.src_lang if config.src_lang and config.src_lang != "auto" else None
        result = self._model.transcribe(
            audio_float,
            task=config.task,
            language=lang,
            temperature=config.temperature or None,
            condition_on_previous_text=config.condition_on_previous_text,
            verbose=False,
        )
        text = (result.get("text") or "").strip()
        return {
            "text": text,
            "language": result.get("language"),
            "backend": "torch",
            "device": self._device,
            "model": config.model,
            "runtime_s": round(time.time() - t0, 2),
        }


class CppBackend(Backend):
    """useful-transformers C++ engine (greedy decode, CPU, experimental).
    Can hallucinate on low-confidence speech — torch backend is preferred."""

    name = "cpp"

    def __init__(self, repo_path: str | None = None,
                 weights_path: str | None = None):
        self._repo_path = repo_path
        self._weights_path = weights_path

    def available(self) -> bool:
        return self._repo_path is not None

    def hardware(self) -> str:
        return "cpu"

    def transcribe(self, audio_float: np.ndarray, config: Config) -> dict[str, Any]:
        if not self._repo_path:
            raise BackendError("cpp backend not configured: set cpp_repo")
        import sys
        sys.path.insert(0, self._repo_path)
        import examples.whisper.whisper as wh  # useful-transformers

        model = config.model
        if self._weights_path:
            model = self._weights_path
        t0 = time.time()
        pcm = (np.clip(audio_float, -1.0, 1.0) * 32768).astype(np.int16)
        text = wh.decode_pcm(pcm, model, task=config.task, src_lang=config.src_lang or "en")
        text = (text or "").strip()
        return {
            "text": text,
            "language": config.src_lang,
            "backend": "cpp",
            "device": "cpu",
            "model": config.model,
            "runtime_s": round(time.time() - t0, 2),
        }


class RknnBackend(Backend):
    name = "rknn"

    def available(self) -> bool:
        return False

    def hardware(self) -> str:
        return "rknn5580"

    def transcribe(self, audio_float: np.ndarray, config: Config) -> dict[str, Any]:
        raise BackendError(
            "rknn backend not yet available (RK3588 NPU validation is scheduled "
            "next week). Use backend=torch or backend=cpp."
        )


def resolve_backend(config: Config) -> Backend:
    choice = config.backend
    if choice == "auto":
        torch_b = TorchBackend(config.device)
        if torch_b.available():
            return torch_b
        cpp_b = CppBackend(config.cpp_repo)
        if cpp_b.available():
            return cpp_b
        raise BackendError("no backend available: torch and cpp are both unconfigured")
    if choice == "torch":
        return TorchBackend(config.device)
    if choice == "cpp":
        return CppBackend(config.cpp_repo)
    if choice == "rknn":
        return RknnBackend()
    raise BackendError(f"unknown backend: {choice!r}")


def backend_status(config: Config) -> dict[str, Any]:
    """Human/API-facing overview of what is installed and which backend wins."""
    torch_b = TorchBackend(config.device)
    cpp_b = CppBackend(config.cpp_repo)
    rknn_b = RknnBackend()
    resolved = None
    try:
        resolved = resolve_backend(config).name
    except BackendError:
        pass
    return {
        "configured": config.backend,
        "resolved": resolved,
        "torch": {
            "available": torch_b.available(),
            "device": torch_b.hardware() if torch_b.available() else None,
        },
        "cpp": {
            "available": cpp_b.available(),
            "device": "cpu",
        },
        "rknn": {"available": rknn_b.available()},
        "model": config.model,
        "src_lang": config.src_lang,
        "task": config.task,
    }


def transcribe(audio_float: np.ndarray, config: Config) -> dict[str, Any]:
    backend = resolve_backend(config)
    return backend.transcribe(audio_float, config)