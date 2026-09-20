"""CLI for whisper-agent.

Usage:
  whisper-agent transcribe <url|path> [--lang zh|auto] [--model base] [--backend auto]
                   [--no-upload] [--filename NAME] [--config FILE]
  whisper-agent serve [--host H] [--port P] [--config FILE]
  whisper-agent mcp   [--host H] [--port P] [--config FILE]
  whisper-agent status [--config FILE]
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whisper-agent",
                                     description="bilingual speech transcription agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_t = sub.add_parser("transcribe", help="transcribe a URL (buffer link) or local file")
    p_t.add_argument("source", help="buffer URL or local audio path")
    p_t.add_argument("--lang", default=None, help="source language (default from config, usually zh)")
    p_t.add_argument("--model", default=None, help="whisper model name")
    p_t.add_argument("--task", default=None, choices=["transcribe", "translate"])
    p_t.add_argument("--backend", default=None, choices=["auto", "torch", "cpp", "rknn"])
    p_t.add_argument("--device", default=None, choices=["auto", "cuda", "cpu"])
    p_t.add_argument("--no-upload", action="store_true", help="skip writing the text back to the buffer")
    p_t.add_argument("--filename", default=None, help="output filename for the buffer upload")
    p_t.add_argument("--config", default=None)
    p_t.add_argument("--raw", action="store_true", help="print raw text only (no JSON)")

    p_s = sub.add_parser("serve", help="run the HTTP API")
    p_s.add_argument("--host", default=None)
    p_s.add_argument("--port", type=int, default=None)
    p_s.add_argument("--config", default=None)

    p_m = sub.add_parser("mcp", help="run the MCP server (for MoJoAssistant)")
    p_m.add_argument("--host", default=None)
    p_m.add_argument("--port", type=int, default=None)
    p_m.add_argument("--config", default=None)

    p_st = sub.add_parser("status", help="show backend/model/config overview")
    p_st.add_argument("--config", default=None)

    args = parser.parse_args(argv)

    from .config import Config

    field_map = {"lang": "src_lang"}
    overrides = {field_map.get(k, k): getattr(args, k, None) for k in (
        "lang", "model", "task", "backend", "device")}
    overrides = {k: v for k, v in overrides.items() if v is not None}
    if getattr(args, "config", None):
        from .config import CONFIG_FILE_ENV
        import os
        os.environ[CONFIG_FILE_ENV] = args.config

    cfg = Config.load(overrides)

    if args.cmd == "transcribe":
        return _cmd_transcribe(args, cfg)
    if args.cmd == "serve":
        from .server import run_http
        return run_http(cfg, host=args.host, port=args.port)
    if args.cmd == "mcp":
        from .mcp_server import run_mcp
        return run_mcp(cfg, host=args.host, port=args.port)
    if args.cmd == "status":
        from .backends import backend_status
        print(json.dumps(backend_status(cfg), indent=2, ensure_ascii=False))
        return 0
    return 2


def _cmd_transcribe(args, cfg) -> int:
    from .service import transcribe_url

    result = transcribe_url(
        args.source, cfg,
        upload=not args.no_upload,
        filename=args.filename,
    )
    if args.raw:
        print(result["text"])
        return 0
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())