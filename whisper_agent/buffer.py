"""Thin MCP client for the buffer service.

Buffer (https://buffer.eclipsogate.org/mcp) stores scratch files and hands
back streamable links. whisper-agent uses it to (a) read audio by URL and
(b) push transcription results back as text files so other assistants/users
can keep working from a link.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from .config import Config


class BufferClient:
    def __init__(self, base_url: str | None = None):
        self._mcp_url = (base_url or "https://buffer.eclipsogate.org") + "/mcp"
        self._session: str | None = None

    def _rpc(self, method: str, params: dict[str, Any], timeout: int = 120) -> Any:
        if self._session is None:
            self._session = self._initialize()
        req = urllib.request.Request(
            self._mcp_url,
            data=json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "method": method, "params": params,
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": self._session,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            data = json.loads(line[5:])
            if "result" in data:
                return data["result"]
            if "error" in data:
                raise RuntimeError(f"buffer RPC {method}: {data['error']}")
        raise RuntimeError(f"buffer RPC {method} returned no usable result")

    def _initialize(self) -> str:
        req = urllib.request.Request(
            self._mcp_url,
            data=json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "whisper-agent", "version": "0.1.0"},
                },
            }).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode()
            session = resp.headers.get("mcp-session-id")
        if not session:
            raise RuntimeError("buffer server did not return an mcp-session-id")
        return session

    def upload_text(self, text: str, filename: str,
                    mime_type: str = "text/plain") -> dict[str, Any]:
        """Upload raw text to the buffer and return {buffer_id, link, ...}."""
        b64 = base64.b64encode(text.encode("utf-8")).decode()
        result = self._rpc("tools/call", {
            "name": "buffer_upload_bytes",
            "arguments": {
                "content_base64": b64,
                "filename": filename,
                "mime_type": mime_type,
            },
        })
        return _extract_text_payload(result)

    def make_default_filename(self, lang: str | None, model: str) -> str:
        lng = lang or "auto"
        return f"whisper_agent_{lng}_{model}_transcription.txt"


def _extract_text_payload(result: dict[str, Any]) -> dict[str, Any]:
    """buffer_upload_bytes returns content=[{'type':'text','text': <json>}].
    Parse that embedded JSON back into a dict."""
    for item in result.get("content", []):
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except (KeyError, ValueError):
                return {"raw": item["text"]}
    return {}