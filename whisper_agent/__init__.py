"""whisper-agent: standalone bilingual speech-transcription agent.

Provides a CLI, an HTTP API, and an MCP server backed by a configurable
backend (ROCm/CUDA GPU via openai-whisper, CPU via the useful-transformers
C++ engine, with an RKNN slot reserved).
"""

__version__ = "0.1.0"