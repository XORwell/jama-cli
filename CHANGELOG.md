# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- HTTP-mode MCP server: the attachment and test run tools (`get_test_run`,
  `update_test_run`, `upload_attachment`, `attach_screenshot_to_test_run`,
  `download_attachment`) are available there too, from the same registry the stdio server
  uses. `GET /v1/tools` lists them; call one with `POST /v1/invoke` and
  `parameters.intent`. Over HTTP files are sent as base64; file paths are refused unless
  the server is started with `--allow-local-paths --local-path-dir DIR`
  (`JAMA_MCP_ALLOW_LOCAL_PATHS`, `JAMA_MCP_LOCAL_PATH_DIR`) and are then confined to that
  directory
- Reuse the session from the user's own Firefox instead of a second login:
  `jama login --from-browser firefox` (or `session_source` / `JAMA_SESSION_SOURCE`).
  Reads only the `JSESSIONID` and `jama-csrf-token` cookies for the configured host, so browser,
  CLI and MCP server share one session and do not evict each other on one-session instances.
  Works in the "CLI in WSL, browser on Windows" setup; Firefox stores cookie values in clear
  text, so it is a plain file read. Non-interactive, so it also works with
  `login_interactive: never`; a truly dead session is re-read from the browser rather than
  prompting. New settings `browser_cookie_profile` and `browser_cookies_path`. Cookie values are
  never logged, and the copied cookie database is deleted after reading. Chrome and Edge are not
  supported (App-Bound Encryption) and fail with a clear message
- Browser-session ("SSO cookie") auth mode, `auth_type: session` / `JAMA_AUTH_TYPE=session`:
  log in once in a real browser (or with the native login form) and work as yourself, with
  your own Jama permissions, without API credentials
  - New commands `jama login`, `jama logout`, `jama status`
  - Session store shared by all processes (`~/.jama/sessions/`, mode 0600, file lock, atomic
    writes), so terminals, IDE windows and MCP servers reuse one session instead of
    invalidating each other's
  - Persistent browser profile for silent re-login; no idle logout
  - Automatic recovery: CSRF token repair, pick-up of a session renewed by another process,
    and a single locked re-login
  - `login_interactive` setting (`auto` | `always` | `never`) and optional keepalive
  - stdio MCP server: session auth plus `get_session_status` and `logout_session` tools
  - Playwright is an optional extra: `pip install "jama-cli[browser]"`
- New dependency: `filelock`
- stdio MCP server: 19 more tools for API operations that had none: `get_items_page`,
  `search_items`, `replace_item`, `get_item_version`, `get_item_lock`, `set_item_lock`,
  `get_relationships`, `get_relationship`, `get_item_upstream_related`,
  `get_item_downstream_related`, `delete_relationship`, `get_relationship_type`,
  `get_item_types`, `get_pick_list`, `get_pick_list_options`, `get_tagged_items`, `create_tag`,
  `get_baseline_versioned_items`, `get_user`
- `get_filter_results` MCP tool accepts an optional `project_id`
- Attachments: `jama attachments upload` now really uploads (create, file upload, link) and
  prints the attachment id, the stored file's id and the embed URL for inline images; new
  options `--name`, `--description`, `--no-link`, `--no-cache`, `--json`; new commands
  `jama attachments download` and `jama attachments download-url`
- Test run results: new command group `jama testruns` with `add-screenshot` (embed images in
  the actual results of a run or of one step), `set-actual` (append or `--replace` HTML) and
  `get`. Edits are a verified read-modify-write that keeps other steps, statuses and existing
  content
- Client API: `JamaClient.create_attachment`, `link_attachment`, `download_embedded`,
  `embed_image_html`, `get_test_run`, `append_to_actual_results`,
  `attach_screenshots_to_test_run`, `update_test_run`
- stdio MCP server: tools `upload_attachment`, `attach_screenshot_to_test_run`,
  `download_attachment` (file path or base64 content) and `get_test_run`
- Under `auth_type: session`, an attachment upload that Jama refuses through the REST API
  falls back to the web UI's own, undocumented endpoint (`/ui/internal/attachments`); other
  auth modes never use it
- Re-running an upload reuses the earlier attachment (local map of file hashes under
  `~/.cache/jama-cli/uploads/`); upload size limit via `JAMA_MAX_ATTACHMENT_BYTES` (default 50 MB)

### Changed
- `JamaClient.upload_attachment` returns a dict (`attachment_id`, `file_id`, `embed_url`, ...)
  instead of an int, and `JamaClient.download_attachment` returns the written path
- MCP tool `update_test_run` merges the given values into the current test run and returns a
  result object instead of the HTTP status; `data` is optional when `step` + `step_fields`
  are given

### Fixed
- `jama attachments upload <testRunId> <file>` failed with 404: test runs are not items in
  the REST API (`items/{id}` and `items/{id}/attachments` answer 404 for a test run id). The
  project is now taken from the test run, or from the new `--project` option, and no link is
  attempted for a test run; the result says `linked: false` with an info note instead of a
  404 warning. `testruns add-screenshot` no longer tries to link either
- `jama items list <project> --type <id>` printed an empty list for test plan, test cycle
  and test run types, which Jama's item list never returns; it now fails with a hint
- Test run results per step were written to the wrong key. Jama stores a step's actual
  results under `result`; a step key `actualResults` is accepted and silently dropped, so
  `testruns set-actual --step`, `testruns add-screenshot --step` and the MCP tools failed on
  every freshly generated run ("did not store"). Steps are now written as `result`;
  `actualResults` on a step is only read as a fallback, and `update_test_run` writes it as
  `result` with a warning
- Test run field names and writability are read from the instance's test run item type
  (`typeKey` `TSTRN`) instead of constants, so fields with a `$<typeId>` suffix work, and a
  field that Jama leaves out of a GET because it is empty is treated as empty
- `update_test_run` now fails when Jama did not store a step value that was sent
- `jama logout` and the MCP tool `logout_session` no longer sign the user out in the browser
  when the session was taken over with `--from-browser`: only the stored copy is removed. New
  flag `jama logout --end-server-session` and tool parameter `end_server_session` end it on the
  server on purpose. The session file records where a session came from (`source`: `login`,
  `form` or `browser-firefox`; files without the key count as `login`), and `jama status`
  shows it. Sessions from `jama login` are ended on the server as before
- Session auth: a wrong or missing CSRF token is repaired silently for every HTTP method.
  Jama checks the token on reads too and answers 401 "CSRF Exception"; this was taken for a
  dead session and led to an unnecessary login (or a failure with `login_interactive: never`)
- Session auth: cookies that Jama sets in ordinary responses are taken over and saved, not
  only those of the login probe
- Deleting (and any other write) no longer fails with `Expecting value: line 1 column 1` when
  Jama answers with an empty body; affects all auth modes
- Hints and progress messages (`Showing first N items ...`, `Searching for ...`, `Info: ...`)
  go to stderr, so `jama -o json ... | jq` receives valid JSON; an empty result prints `[]`
  for JSON and YAML instead of `No data to display`
- README and EXAMPLES showed `--output` after the subcommand, where it is not accepted; it is
  a global option (`jama -o json items list 123`)
- Dropped the `all` extra from the `typer` dependency, which newer typer versions no longer
  provide
- `upload_attachment` passed the file path as an attachment id and never uploaded anything
- `download_attachment` wrote the attachment's metadata as JSON instead of the file
- MCP tool `update_test_run` sent a partial update as the whole PUT body, which could wipe
  the other steps of a test run
- Calls that return Jama's status (`post_item_attachment`, `put_test_run`, `post_item_tag`,
  ...) failed with `ValueError` when Jama reported the status as text (`"OK"`)

## [0.1.4] - 2026-04-21

### Added
- Test management tools in the stdio MCP server (test cycles, test runs, etc.)
- Project-specific `CLAUDE.md` for agent context

### Changed
- Replaced `py_jama_rest_client` with an async `httpx`-based client
  - Concurrent requests via `asyncio`; honest rate-limit handling (`Retry-After`)
  - `get_all()` now fetches at the API max page size of 50 (was 20)

### Fixed
- Environment variables (`JAMA_URL`, `JAMA_CLIENT_ID`, `JAMA_CLIENT_SECRET`) now
  override values from `config.yml` instead of being overridden by them
- `create_item`: `child_item_type_id` is now optional

## [0.1.3] - 2026-03-10

### Fixed
- Restored GHCR Docker badge in README
- Fixed lint formatting (black, isort) across test and source files
- Corrected author email in pyproject.toml
- Fixed pre-commit config (removed Python 3.11 pin, removed broken mypy hook)
- Signed all commits with YubiKey SSH key

## [0.1.0] - 2026-03-10

### Initial Public Release

#### CLI (`jama`)
- **Full CRUD Operations**: Create, Read, Update, Delete Jama items
- **70 Jama API Operations**: Complete coverage of Jama REST API
- **Multiple Auth Methods**: OAuth2, API tokens, or username/password
- **Multi-Server Profiles**: YAML config with named profiles and `--profile` switching
- **Rich Output**: Table, JSON, and plain text output formats

#### MCP Server
- **Dual Protocol Support**: stdio MCP (for Claude Desktop, Cline) and HTTP REST API
- **SSE Streaming**: Real-time Server-Sent Events via `/v1/sse`
- **Batch Operations**: Execute multiple operations via `/v1/batch`
- **OpenAPI Documentation**: Interactive Swagger UI at `/api/docs`

#### Read Operations
- Projects & Items
- Relationships & Dependencies
- Item Types & Metadata
- Pick Lists & Options
- Tags
- Test Cycles & Runs
- Baselines & Versions
- Users & Filters

#### Write Operations
- Create/Update/Delete items
- Create/Delete relationships
- Item locking
- File attachments
- Test run updates
- User management

#### Data Migration
- **Export Command**: `jama migrate export` - Export items to JSON with hierarchy preservation
- **Import Command**: `jama migrate import` - Import items from JSON with type mapping support
- **Clone Command**: `jama migrate clone` - Clone items within the same Jama instance
- **Copy Command**: `jama migrate copy` - Copy items between different Jama instances
- **Info Command**: `jama migrate info` - Inspect export file contents

#### Search & Diff
- **Search Command**: `jama search` - Find items by text or regex
- **Diff Command**: `jama diff` - Compare items between projects or instances

#### Performance
- **Caching Layer**: In-memory + disk cache for frequently accessed data
- **Cache Management**: `jama config cache` command to view stats and clear cache

#### Production Readiness
- **API Authentication**: Bearer token authentication for HTTP server
- **Rate Limiting**: Built-in rate limiting (100 requests/60 seconds per IP)
- **Security Headers**: Standard security headers on all responses
- **Graceful Shutdown**: Proper signal handling for clean shutdown
- **Kubernetes Probes**: `/ready` and `/live` endpoints
- **Structured Logging**: JSON log format option for log aggregation
- **Docker Support**: Multi-stage build with development and production images

---

[0.1.4]: https://github.com/XORwell/jama-cli/releases/tag/v0.1.4
[0.1.3]: https://github.com/XORwell/jama-cli/releases/tag/v0.1.3
[0.1.0]: https://github.com/XORwell/jama-cli/releases/tag/v0.1.0
