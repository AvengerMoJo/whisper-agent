# MoJoAssistant Third-Party Service Module Standard

version 1.0 (draft)

A public, defined contract for building **service modules** that MoJoAssistant
can configure, install, start, stop, restart, monitor, and consume — the same
way it treats `mcp-buffer`, `mcp-service`, OpenCode, Playwright, and tmux.

This repository, `whisper-agent`, is the **reference implementation** of this
standard. When a rule here is ambiguous, read this repo's code first.

---

## 1. What a service module is

A service module is a standalone, installable package that exposes one or more
**MCP tools** (and optionally plain HTTP routes) over a standard MCP transport,
plus a fixed set of contract points MoJoAssistant relies on:

| Contract point | Who uses it | Where |
|---|---|---|
| Registration metadata | MoJo MCP client manager | `config/mcp_servers.json` (system) + `~/.memory/config/mcp_servers.json` (personal override) |
| Lifecycle (start/stop/restart/status) | MoJo agent hub | `agent(action=..., agent_id=<server_id>)`, agent type `mcp_server` |
| Tool discovery + permission scoping | MoJo capability registry | tools registered as `<server_id>__<tool_name>`, scoped by `category` |
| Preflight / doctor diagnostics | MoJo installer & doctor | `install_hint`, `requires` |
| Runtime reconfiguration | operator / other agents | layered config (file → env → per-request) |

Three published modules follow these patterns today:

- `mcp-buffer` — file-handoff buffer (FastMCP streamable-http, backend plugin registry, transport security)
- `mcp-service` — OAuth-secured service infrastructure (config, errors, oauth, templates)
- `whisper-agent` — GPU transcription (CLI + HTTP + MCP) — this repo, the reference

---

## 2. Mandatory repository/package structure

```
<module>/
├── pyproject.toml            # console script + installable package
├── README.md                 # install, quick start, tools, config keys
├── pytest.ini                # asyncio_mode = auto, testpaths = tests
├── .gitignore                # __pycache__, *.egg-info/, venv/, credentials
├── tests/
│   ├── test_config.py        # config layering
│   ├── test_server*.py       # MCP server + transport-security behavior
│   └── test_<domain>.py      # domain behavior
└── <module_pkg>/
    ├── __init__.py
    ├── config.py             # layered runtime config (see §5)
    ├── cli.py                # console entry (argparse): serve / mcp / status
    ├── server.py             # optional: plain HTTP routes (flask/FastAPI)
    ├── mcp_server.py         # FastMCP server: tools + transport setup
    └── <domain modules>.py   # business logic, backends, plugins
```

`pyproject.toml` must declare:

```toml
[project]
name = "<module>"
requires-python = ">=3.10"
dependencies = ["mcp>=1.0", ...]

[project.scripts]
<module> = "<module_pkg>.cli:main"

[tool.setuptools.packages.find]
include = ["<module_pkg>*"]
```

Every module must be installable with `pip install -e .` into the venv that
will run it.

---

## 3. MCP transport contract

### 3.1 Preferred transport: streamable HTTP

MoJo connects to externally-running modules with
`transport = "http"` and a full URL / port. **Streamable HTTP is the standard
transport** — not SSE, which is being superseded and doesn't play as nicely
with reverse proxies and tunnels.

```python
# <module_pkg>/mcp_server.py
mcp = FastMCP("<module>")
mcp.settings.host = cfg.http_host          # e.g. 127.0.0.1
mcp.settings.port = cfg.mcp_port           # e.g. 8820
mcp.settings.streamable_http_path = "/mcp" # fixed endpoint path
mcp.run(transport="streamable-http")
```

The MCP endpoint MUST live at `/mcp`. A typical Healthz of a running module:
`http://localhost:<port>/mcp` must answer MCP `initialize`.

### 3.2 Transport security (DNS-rebinding protection)

Keep FastMCP's DNS-rebinding protection **on** (it is a real defense), with
loopback hosts allowed by default. When the module is exposed through a
reverse proxy/tunnel, extend the allowlist from a public-URL environment
variable so the forwarded `Host` header isn't blanket-421'd:

```python
from mcp.server.transport_security import TransportSecuritySettings

_DEFAULT_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]

def _transport_security() -> TransportSecuritySettings:
    allowed_hosts = list(_DEFAULT_ALLOWED_HOSTS)
    public_url = os.environ.get("<MODULE>_PUBLIC_URL")
    if public_url:
        host = urlparse(public_url).hostname
        allowed_hosts += [host, f"{host}:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
    )
```

### 3.3 One process, one port, optional extra HTTP routes

Additional HTTP routes (file downloads, uploads, pastebin-style endpoints) run
on the **same port** as the MCP server via `FastMCP.custom_route()` — never a
second socket. Registration order matters: more-specific routes first so they
aren't shadowed by parameterized ones.

### 3.4 stdio (spawned) transport

Modules that are cheap to start and don't hold warm state may also expose
`--transport stdio` (MoJo spawns the process with `command`/`args`). Both
transports can coexist behind one CLI flag:

```
<module> mcp --host 127.0.0.1 --port 8820      # streamable-http (default)
<module> mcp --transport stdio                  # spawned by MoJo
```

---

## 4. Tool contract

- Tools are declared with `@mcp.tool()` on the FastMCP server.
- Tool names are **snake_case verbs**: `transcribe_url`, `status`, `list_models`.
- Tools MUST return JSON-serializable types (dict/list/str/int/float/bool/None).
- **Large/binary payloads are never base64'd through JSON-RPC.** Hand off by URL
  (see mcp-buffer): upload to the buffer, return the link.
- Every module MUST expose a `status()` tool returning at minimum:
  `{ "backends"/"engine": ..., "device": ..., "model": ..., "config": {...} }`.
  MoJo uses it as the BRIDLE post-check that the module is actually working.

### Plugins / backend selection

Multi-backend modules register implementations with a decorator-based registry
(see `mcp_buffer/registry.py`) and select at runtime:

```python
os.environ.get("<MODULE>_BACKEND", "default")
```

---

## 5. Configuration contract

Layering, lowest to highest precedence:

```
defaults → config file → environment → per-request tool args
```

- **Config file**: `~/.config/<module>/config.json`, or a path overridden by
  `$<MODULE>_CONFIG`.
- **Environment**: `<MODULE>_<KEY>` for every config key — e.g.
  `WHISPER_AGENT_MODEL=base`, `WHISPER_AGENT_HTTP_PORT=5000`,
  `MCP_BUFFER_BACKEND=local`. The `<MODULE>_PUBLIC_URL` key controls the
  transport-security host allowlist (§3.2).
- **Per-request**: tool args override config for that call only.
- Prefixes are **module-scoped and must not collide** (e.g. `WHISPER_AGENT_*`,
  `MCP_BUFFER_*`). The `MCP_` prefix is conventional for MCP-facing knobs such
  as public URL and backend selection.

---

## 6. Registration contract (`mcp_servers.json`)

Register a module by adding an entry to the personal layer
`~/.memory/config/mcp_servers.json` (a same-`id` entry there overrides the
system `config/mcp_servers.json`). Two transport models:

### stdio (MoJo spawns it)

```json
{
  "id": "tmux",
  "name": "tmux MCP",
  "transport": "stdio",
  "command": "/path/to/binary",
  "args": ["--flag"],
  "env": {"KEY": "value"},
  "category": "terminal",
  "enabled": true,
  "install_hint": "how to install",
  "requires": [{"binary": "tmux", "hint": "apt install tmux"}]
}
```

### http (externally running, MoJo registers how to reach it)

```json
{
  "id": "whisper-agent",
  "name": "Whisper Agent MCP",
  "transport": "http",
  "mcp_http_url": "http://localhost:8820/mcp",
  "port": null,
  "pid": null,
  "authorization": null,
  "authorization_env": "WHISPER_AGENT_TOKEN",
  "category": "media",
  "enabled": true
}
```

`port` is shorthand for `http://localhost:<port>/mcp`. Provide
`mcp_http_url` OR `port`. `authorization_env` reads a Bearer token from the
named environment variable at connect time. `authorization` holds the literal
token; never commit tokens.

Required fields: `id`, `name`, `transport`, `category`, `enabled`.
Optional: `mcp_http_url`, `port`, `pid`, `authorization`, `authorization_env`,
`install_hint`, `requires`, `comment`.

### `category` — permission scoping

`category` links tools to `tool_catalog.json`: roles that declare that category
receive all tools from the module. Use an existing category (`browser`,
`terminal`, `exec`, `file`, `google`, `external`, ...) or extend the catalog
with a new one (e.g. `media` for whisper-agent) when none fits.

### Tool registration

On connect, MoJo registers every tool as `<server_id>__<tool_name>` with
executor `external_mcp` (e.g. `whisper-agent__transcribe_url`). Multiple
modules can share a category safely; tool names are always namespaced by
server id.

---

## 7. Lifecycle contract (MoJo agent hub)

Modules appear under agent type `mcp_server`, identified by their `server_id`:

```
agent(action="list", type="mcp_server")        # all configured + connection state
agent(action="status", agent_id="<server_id>")
agent(action="start", agent_id="<server_id>")  # connect/reconnect
agent(action="restart", agent_id="<server_id>")
agent(action="stop", agent_id="<server_id>")
agent(action="list_servers")
agent(action="reconnect_all")
```

`start` for an already-connected server is a no-op (use `restart` to force
reconnect). Tools are only callable through MoJo while the server is in
`connected` state; MoJo surfaces dead sessions naturally at call time.

---

## 8. Publishing / onboarding workflow (public availability)

1. **Scaffold** — layout per §2, `pip install -e .` works in the target venv.
2. **Implement** — MCP server per §3, tools per §4, config per §5.
3. **Test** — `pytest`: config layering, server responds on `/mcp`, transport
   security allows loopback and rejects a spoofed `Host` header.
4. **Smoke-test the handshake** before registering:
   ```bash
   curl -s -X POST "http://localhost:8820/mcp" \
     -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
   # then call the status tool via the returned session id and confirm:
   #   varargs {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"status","arguments":{}}}
   ```
5. **Register** — add the `mcp_servers.json` entry (personal layer first).
6. **Verify lifecycle** — `agent(action="list_servers")` → `restart` the
   server → call `status`; confirm `state == connected` and tools visible.
7. **Wire permissions** — declare the `category` in `tool_catalog.json`, grant it
   to the roles that should use the module.
8. **Expose publicly (optional)** — tunnel (cloudflared / headscale-style), set
   `<MODULE>_PUBLIC_URL`, verify the tunneled `Host` header is not 421'd.
9. **Publish source** — public GitHub repo keeps the module installable and
   auditable (see §9).

---

## 9. Source publication

- Repos are public on GitHub under the module's own name (`mcp-buffer`,
  `mcp-service`, `whisper-agent`).
- Add a `pytest.ini` shipped with the repo and a CI workflow
  (`pytest` on push/PR).
- Never commit secrets: tokens, `.env` files, key stores. Use
  `authorization_env` (env var names) in registration instead of literal tokens.
- `.gitignore` must exclude `__pycache__/`, `*.pyc`, `venv/`, `.venv/`,
  `*.egg-info/`, `.pytest_cache/`, and any credential dumps.

---

## 10. Conformance checklist

| # | Check | Reference |
|---|---|---|
| C1 | `pip install -e .` into runtime venv | `pyproject.toml` |
| C2 | Exposes MCP tools at `/mcp` over streamable-http | `mcp_server.py` |
| C3 | ONE process, ONE port; extra routes via `custom_route()` | mcp-buffer `server.py`, `file_routes.py` |
| C4 | DNS-rebinding protection ON; allowlist extendable via a public-URL env var | `_transport_security()` |
| C5 | Tools return JSON-serializable values, snake_case names, no base64 blobs | `tools.py` |
| C6 | Exposes `status()` for BRIDLE post-check | `mcp_server.py` |
| C7 | Layered config: defaults → `~/.config/<module>/config.json` → `<MODULE>_<KEY>` env → per-request | `config.py` |
| C8 | Prefix is module-scoped and non-colliding | `WHISPER_AGENT_*`, `MCP_BUFFER_*` |
| C9 | Registers via `mcp_servers.json` (id/name/transport/category/enabled ...) | §6 |
| C10 | Lifecycle via `agent(action=..., agent_id=<server_id>)`, type `mcp_server` | §7 |
| C11 | `pytest` green: config, server `/mcp`, transport-security tests | `tests/` |
| C12 | Public source repo, no secrets, `.gitignore` excludes credentials | §9 |

---

## 11. Versioning of this document

This standard is drafted at v1.0. Update it deliberately: any change that
alters the registration schema (`ExternalMCPServer` fields in
`app/scheduler/mcp_client_manager.py`), the lifecycle surface
(`app/mcp/agents/mcp_server_manager.py`), or the transport rules is a breaking
change and must bump the major version and migrate the reference
implementations (`mcp-buffer`, `mcp-service`, `whisper-agent`) together.