# whisper-agent

Standalone bilingual speech-transcription agent with three faces — **CLI**, **HTTP API**, and **MCP server** — backed by hardware-accelerated whisper (ROCm/CUDA GPU first, C++ CPU fallback, RKNN slot reserved).

Built so MoJoAssistant can deploy/consume it as a module and reconfigure it at runtime without code changes.

## Install

```bash
pip install -e .            # into the venv that has torch + openai-whisper (GPU)
```

Dependencies: `flask`, `openai-whisper`, `mcp`, `requests`. A `torch` install with
ROCm/CUDA support provides GPU acceleration; without it, backend falls back to CPU.

## Usage

```bash
# Transcribe a buffer link or a local file; result text is uploaded back to the
# buffer and the fresh link is returned.
whisper-agent transcribe https://buffer.eclipsogate.org/buffer/<id> --lang zh
whisper-agent transcribe path/to/audio.wav --no-upload --raw

# Status: which backend/device/model is active
whisper-agent status

# HTTP API  (GET /api/status, /api/models · POST /api/transcribe, /api/transcription)
whisper-agent serve --host 127.0.0.1 --port 5000

# MCP server (streamable HTTP, tools: transcribe_url, status, list_models)
whisper-agent mcp --host 127.0.0.1 --port 8820
```

### Runtime configuration

Layering, lowest to highest precedence: defaults → config file → environment → per-request.

- **Config file**: `~/.config/whisper-agent/config.json` (or `$WHISPER_AGENT_CONFIG`)
- **Environment**: `WHISPER_AGENT_<KEY>` — e.g. `WHISPER_AGENT_MODEL=base`,
  `WHISPER_AGENT_SRC_LANG=zh`, `WHISPER_AGENT_BACKEND=auto`,
  `WHISPER_AGENT_DEVICE=auto`, `WHISPER_AGENT_HTTP_PORT=5000`,
  `WHISPER_AGENT_MCP_PORT=8820`.
- **Per-request** (HTTP JSON body / MCP tool args): `lang`, `model`, `task`,
  `backend`, `device`, `upload`, `filename`.

Keys: `model` (base, medium, large-v3, tiny.en, ...), `src_lang` (zh | auto),
`task` (transcribe | translate), `backend` (auto | torch | cpp | rknn),
`device` (auto | cuda | cpu), `temperature`, `condition_on_previous_text`,
`buffer_base_url`, `cpp_repo` (path to useful-transformers for the C++ engine),
`http_host/http_port`, `mcp_host/mcp_port`.

## Backends

| backend | engine | accel | status |
|---------|--------|-------|--------|
| `torch` (default) | openai-whisper | ROCm/CUDA GPU, else CPU | production |
| `cpp` | useful-transformers C++ engine | CPU | experimental (greedy decode, can hallucinate) |
| `rknn` | reserved RK3588 NPU | NPU | planned (validation next week) |

`backend=auto` resolves to torch-GPU when available.

## Example

```bash
whisper-agent transcribe https://buffer.eclipsogate.org/buffer/ecf27e37-6d02-46f5-a2e4-4bfbd05595c8
```

returns JSON with `text`, `language`, `backend`, `device`, `model`, `runtime_s`
and a `buffer_link` to the uploaded transcription.

## Registering with MoJoAssistant / opencode

```jsonc
// ~/.config/opencode/opencode.json
"mcp": {
  "whisper-agent": { "type": "remote", "url": "http://127.0.0.1:8820/mcp", "enabled": true }
}
```

Start the server with `whisper-agent mcp` (the MoJoAssistant process can start it
via its `mcp_server` agent lifecycle, or via systemd/user services for the Radeon host).

## Tests

```bash
pip install -e '.[dev]'
pytest
```

## Layout

```
whisper_agent/
  cli.py         argparse entry: transcribe / serve / mcp / status
  config.py      layered runtime config (file + env + per-request)
  audio.py       URL fetch + ffmpeg decode -> 16 kHz PCM
  service.py     orchestration (transcribe + buffer push)
  backends.py    torch / cpp / rknn registry
  buffer.py      buffer MCP client (read audio, push text)
  server.py      flask HTTP API
  mcp_server.py  streamable-HTTP MCP server for MoJoAssistant
```

## Roadmap

- RK3588/RKNN NPU backend (validation next week on real hardware)
- Streaming / long-form chunked transcription
- Speaker diarization (optional)