# Read-only mode

Status: implemented on `feat/read-only-mode`.

## Goal

One switch that makes jama-cli unable to change anything in Jama, so an MCP
client (an AI agent) can be pointed at a production instance safely. It has to
hold in both MCP transports (stdio and HTTP) and in the CLI, and tests have to
prove it.

## Switch

- `read_only: true` in a profile (`~/.jama/config.yml`)
- `JAMA_READ_ONLY=1` (also `true`, `yes`, `on`)
- `jama serve --read-only` (stdio, HTTP and daemon mode; `jama serve restart`
  keeps the mode of the previous daemon, recorded in `~/.jama/server.mode`)
- MCP server `.env` / YAML config: `JAMA_READ_ONLY` / `read_only`

Any one of them turns it on. Nothing turns it off again: an environment variable
cannot override `read_only: true` in a profile. Default stays read-write
(published package, backward compatible).

## Two independent layers

1. **Tool layer (MCP servers).** An explicit allowlist of read tools (stdio)
   and read intents (HTTP), in `jama_mcp_server/core/read_only.py`.
   - stdio `list_tools` hides everything else; `_execute_tool` refuses it.
   - HTTP `_execute_jama_operation` refuses it (covers `/v1/invoke`,
     `/v1/batch`, SSE messages and prompt parsing, which all end there);
     `/v1/tools` hides it; `/health` reports `read_only`.
   - Refusals carry error code `READ_ONLY_MODE`.
   - Every tool and intent must be listed as either read or write. A test fails
     when a new one is added without a classification.

2. **Transport layer.** Independent of the tool lists:
   - `JamaHttpClient(read_only=True)` raises `ReadOnlyModeError` in `_request`
     for any method other than GET/HEAD/OPTIONS, before anything is sent.
     All `JamaApi` calls (CLI, stdio server, shared attachment/test run tools)
     go through `_request`. OAuth token and session login/logout requests use
     their own paths and keep working.
   - HTTP mode still uses py-jama-rest-client for most intents. Its
     `requests.Session` gets a wrapping adapter that refuses non-GET methods.
     If the library's internals change so that the session cannot be found,
     the server refuses to start in read-only mode (fail closed).

## Classification decisions

- `download_attachment`: allowed. Reads from Jama; may write a local file
  (stdio, or HTTP with `--allow-local-paths`).
- `get_session_status`, `logout_session`: allowed. They manage the local login
  session, not Jama data.
- `get_filter_results`, `search_items`, `get_abstract_items`: reads (GET).
- Everything that POSTs, PUTs, PATCHes or DELETEs is a write, including
  `set_item_lock`/`put_item_lock`, `post_item_tag`, `create_tag`,
  `post_item_sync`, user management.

## Tests (`tests/test_read_only_mode.py`)

- Classification: read ∪ write == all listed stdio tools / all HTTP intents,
  disjoint; shared tools classified.
- stdio: write tools hidden from `list_tools`; calling one returns a
  read-only error; read tools still listed and dispatched.
- stdio end to end with a recording `httpx.MockTransport`: every write tool is
  called with the tool gate bypassed, and no non-GET request reaches the wire
  (proves layer 2 alone holds, including read-modify-write tools).
- `JamaHttpClient`: every write verb raises before sending; GET works; OAuth
  token refresh (POST) still works.
- `JamaApi`: every write method raises with a read-only client.
- HTTP server: write intents refused with `READ_ONLY_MODE`, nothing sent;
  `/v1/tools` filtered; `/health` reports the mode.
- py-jama-rest-client guard: non-GET refused at the adapter, GET passes, and
  startup fails closed when the session cannot be found.
- Config: profile key, env var (truthy/falsy parsing), env cannot turn it
  off, `jama serve --read-only` reaches both servers, CLI client built from a
  read-only profile refuses writes.

## Out of scope

- Per-project or per-user permissions (that is go-jama-gw's job).
- A global `jama --read-only` flag for every CLI command; the profile key and
  env var cover the CLI.
