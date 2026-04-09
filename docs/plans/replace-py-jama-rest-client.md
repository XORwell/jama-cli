# Plan: Replace py_jama_rest_client with Async JamaHttpClient

## Architecture

```
Phase 1: New files (no existing code touched)
  1.1 jama_cli/core/exceptions.py     — exception hierarchy
  1.2 jama_cli/core/http_client.py    — async httpx client (auth, pagination, retry)
  1.3 jama_cli/core/api.py            — typed async API methods (~60 wrappers)
  1.4 jama_cli/core/sync_wrapper.py   — background-thread sync facade for CLI

Phase 2: Update jama_cli/core/client.py  (swap internals, keep public API)
Phase 3: Update MCP servers             (remove run_in_executor, await directly)
  3.1 jama_mcp_server/core/stdio_server.py
  3.2 jama_mcp_server/core/server.py
Phase 4: pyproject.toml                  (drop py-jama-rest-client, add httpx)
Phase 5: Update tests
Phase 6: Cleanup (CLAUDE.md, mypy overrides)
```

## Key Decisions

- **httpx.AsyncClient** for transport (both sync CLI via thread-bridge and async MCP)
- **Async-native + background-thread sync wrapper** (one implementation, no duplication)
- **Preserve exception class names** (APIException, AlreadyExistsException, etc.)
- **Page size 50** (fix the library's hardcoded 20)
- **Retry on 429** with exponential backoff (3 retries)
- **jama_mcp_server imports from jama_cli.core** for shared client layer

## Phases 2+3 are independent and can be parallelized.
