# Jama CLI

[![CI](https://img.shields.io/github/actions/workflow/status/XORwell/jama-cli/ci.yml?branch=main&label=CI)](https://github.com/XORwell/jama-cli/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/jama-cli.svg)](https://pypi.org/project/jama-cli/)
[![Python Versions](https://img.shields.io/pypi/pyversions/jama-cli.svg)](https://pypi.org/project/jama-cli/)
[![Docker](https://img.shields.io/badge/ghcr.io-jama--cli-blue?logo=docker)](https://ghcr.io/xorwell/jama-cli)


A powerful command-line interface for Jama requirements management, with MCP (Model Context Protocol) server support for AI assistants.

> **DISCLAIMER**: This is an unofficial community project and is not associated with, endorsed by, or affiliated with Jama Software in any way.

## Quick Start

```bash
# Install
pip install jama-cli

# Configure
jama config init

# Use
jama projects list
jama items list 123
jama -o json items get 456
```

## Features

### CLI Commands
- **Projects**: List, view, and search projects
- **Items**: Full CRUD operations (create, read, update, delete)
- **Relationships**: Manage upstream/downstream traceability
- **Traceability**: Coverage analysis, trace matrix, trace trees
- **Baselines**: Compare baselines, view versioned items
- **History**: View item version history, compare versions
- **Search**: Full-text and regex search across projects
- **Diff**: Compare projects, count differences
- **Migrate**: Export, import, clone, copy data
- **Types**: View item types and their fields
- **Config**: Multi-profile configuration management

> **See [EXAMPLES.md](https://github.com/XORwell/jama-cli/blob/main/EXAMPLES.md) for comprehensive usage examples**

### MCP Server
- **stdio mode**: Native integration with Claude Desktop, Cline, VS Code
- **HTTP mode**: REST API with OpenAPI documentation
- **70 Jama operations**: Complete API coverage

### Output Formats
```bash
jama items list 123                    # Table (default)
jama -o json items list 123      # JSON
jama -o csv items list 123       # CSV
jama -o yaml items list 123      # YAML
```

## Installation

### pip (recommended)
```bash
pip install jama-cli
```

### pipx (isolated)
```bash
pipx install jama-cli
```

### From source
```bash
git clone https://github.com/XORwell/jama-cli.git
cd jama-cli
pip install -e .
```

## Configuration

### Interactive Setup
```bash
jama config init
```

### Configuration File
Location: `~/.jama/config.yml`

```yaml
default_profile: production

profiles:
  production:
    url: https://company.jamacloud.com
    auth_type: api_key
    api_key: ${JAMA_API_KEY}  # Environment variable

  staging:
    url: https://staging.jamacloud.com
    auth_type: oauth
    client_id: ${JAMA_CLIENT_ID}
    client_secret: ${JAMA_CLIENT_SECRET}

defaults:
  output: table
  limit: 50
```

### Environment Variables
```bash
export JAMA_URL=https://company.jamacloud.com
export JAMA_API_KEY=your-api-key
export JAMA_PROFILE=production  # Optional: override default profile
```

## Browser Session Login (SSO)

`auth_type: session` lets you work as yourself, without API credentials. You log in once in a
real browser (SSO, MFA and consent screens included), the CLI captures the Jama web session, and
every REST call reuses it. Everything runs with your own Jama permissions and is attributed to
you. It works on Jama Cloud and self-hosted instances, with or without SSO.

> **Check with your Jama admin first.** This mode reuses a web session for REST calls. Whether
> that is acceptable under your organisation's Jama terms and license is for your Jama admin to
> confirm; this project cannot decide that for you.

### Setup

```bash
pip install "jama-cli[browser]"     # Playwright is an optional extra
playwright install chromium         # or use an installed browser: --browser-channel chrome|msedge
```

```yaml
# ~/.jama/config.yml
profiles:
  me:
    url: https://company.jamacloud.com    # self-hosted: include the context path, e.g. https://host/contour
    auth_type: session
```

or with environment variables: `JAMA_URL=... JAMA_AUTH_TYPE=session`.

### Commands

```bash
jama login      # Log in and store the session
jama status     # Base URL, user, age, last validation, and whether the session is valid right now
jama logout     # Log out on the server (releases the license seat) and delete the stored session
```

`jama login` options: `--mode browser|form`, `--browser-channel`, `--browser-profile-dir`,
`--timeout`, `--headful` (skip the silent attempt), `--force`, and `--debug-dir DIR`, which saves a
screenshot of each login step for diagnosing a failed login (the screenshots can show your user
name; delete them afterwards).

- **`browser` (default):** uses a persistent browser profile (`~/.jama/browser-profile`), so your
  identity provider remembers you. Later logins first run headless and are usually silent; only
  if that needs you (password, MFA) does a window open. Nothing is pre-filled and your password
  is never read or stored. The SSO button is detected automatically; if your instance uses a
  different button, set `sso_selectors`.
- **`form`:** native Jama login without a browser, for non-SSO instances and service accounts.
  Takes `username`/`password` from the profile or `JAMA_USERNAME`/`JAMA_PASSWORD`. Does not need
  Playwright.

### How the session is kept

- The session is stored per Jama URL and account in `~/.jama/sessions/` (mode `0600`) and is
  **shared by every process**: all terminals, IDE windows, agents and MCP servers use the same
  session. Jama allows one live session per account, so a process whose session stopped working
  first checks whether another process already logged in again before logging in itself. Logins
  are serialised with a file lock.
- There is **no idle logout**. The session ends when you run `jama logout` or when Jama's own
  idle timeout expires it.
- **License seat:** on a floating license a session holds a seat until logout or Jama's
  server-side timeout. Run `jama logout` when you are done.
- The session file contains your session cookies. Treat it like a password and do not copy it to
  other machines.

### Settings

Environment variables override the profile.

| Profile key | Environment variable | Default | Meaning |
|---|---|---|---|
| `auth_type: session` | `JAMA_AUTH_TYPE=session` | | Select this mode |
| `login_mode` | `JAMA_LOGIN_MODE` | `browser` | `browser` or `form` |
| `login_interactive` | `JAMA_LOGIN_INTERACTIVE` | `auto` | See below |
| `login_timeout` | `JAMA_LOGIN_TIMEOUT` | `300` | Seconds to wait for a login |
| `browser_channel` | `JAMA_BROWSER_CHANNEL` | bundled Chromium | `chrome`, `msedge`, ... |
| `browser_profile_dir` | `JAMA_BROWSER_PROFILE_DIR` | `~/.jama/browser-profile` | Persistent browser profile |
| `sso_selectors` | `JAMA_SSO_SELECTORS` | `#loginWithSSOButton`, `input[name="submitWithSSO"]` | CSS selectors of the SSO button (list; comma-separated in the env var) |
| `session_file` | `JAMA_SESSION_FILE` | `~/.jama/sessions/<hash>.json` | Session store file |
| `login_debug_dir` | `JAMA_LOGIN_DEBUG_DIR` | off | Screenshots of each login step |
| `session_keepalive_minutes` | `JAMA_SESSION_KEEPALIVE_MINUTES` | `0` (off) | MCP server only: one cheap request every N minutes |
| | `JAMA_SESSION_DIR` | `~/.jama/sessions` | Directory for session files |

`login_interactive` controls what happens when a command or the MCP server finds no valid session:

- `auto` (default): try a silent, headless login; open a browser window only if that is not enough.
- `always`: open a browser window directly whenever a login is needed.
- `never`: never start a browser; fail with "run `jama login`". Use this on servers and in CI.
  (`form` logins need no browser and still work.)

### MCP server

`jama serve --stdio` supports session auth (the HTTP server mode does not). Two extra tools are
available: `get_session_status` (never returns cookies or tokens) and `logout_session` (releases
the seat). All logs go to stderr; stdout carries only the MCP protocol.

```json
{
  "mcpServers": {
    "jama": {
      "command": "jama",
      "args": ["serve", "--stdio"],
      "env": {
        "JAMA_URL": "https://company.jamacloud.com",
        "JAMA_AUTH_TYPE": "session",
        "JAMA_LOGIN_INTERACTIVE": "never"
      }
    }
  }
}
```

With `never`, run `jama login` in a terminal once; the server picks the session up from the store.

### WSL, SSH and containers

The browser opens **on the machine where the process runs**. In WSL that is the Linux side (it
needs WSLg or another display); over SSH it is the remote host, not your laptop. If that machine
has no display, log in with `--mode form` where possible, or run the tool locally. In containers
Chromium is started with `--no-sandbox --disable-dev-shm-usage` automatically.

## CLI Commands

### Projects
```bash
jama projects list                     # List all projects
jama projects get 123                  # Get project details
jama -o json projects list       # JSON output
```

### Items
```bash
jama items list 123                    # List items in project 123
jama items get 456                     # Get item details
jama items children 456                # Get child items

# Create item
jama items create 123 --type 45 --name "New Requirement"

# Update item
jama items update 456 --name "Updated Name"
jama items update 456 --field status=Approved

# Delete item
jama items delete 456
jama items delete 456 --force          # Skip confirmation
```

### Relationships
```bash
jama relationships list 456            # All relationships for item
jama relationships upstream 456        # Upstream items (traced from)
jama relationships downstream 456      # Downstream items (traced to)

# Create relationship
jama relationships create --from 456 --to 789

# Delete relationship  
jama relationships delete 123
```

### Item Types
```bash
jama types list                        # List all item types
jama types get 45                      # Get type details
```

### Configuration
```bash
jama config init                       # Interactive setup
jama config list                       # List profiles
jama config show                       # Show current profile
jama config add prod --url https://... --api-key xxx
jama config remove staging
jama config set-default production
jama config cache                      # Show cache stats
jama config cache --clear              # Clear cache
```

### Search
```bash
jama search items "login"                        # Search all projects
jama search items "login" --project 123          # Search in specific project
jama search items "REQ-" --field documentKey     # Search by document key
jama search items "^REQ-\\d+" --regex            # Regex search
jama search items "test" --type 45               # Search specific item type
jama search fields 123                           # List searchable fields
```

### Diff (Compare Projects)
```bash
jama diff projects 123 456                       # Compare two projects
jama diff projects 123 456 --from dev --to prod  # Compare across instances
jama diff projects 123 456 --type 45             # Compare specific item type
jama diff projects 123 456 --key name            # Match by name instead of key
jama diff count 123 456                          # Quick count comparison
```

### Traceability Analysis
```bash
jama trace matrix 1172                           # Traceability matrix
jama trace matrix 1172 -s 45 -t 67               # Requirements → Test Cases
jama trace matrix 1172 --untraced                # Show coverage gaps
jama trace coverage 1172                         # Coverage % by item type
jama trace tree 12345                            # Trace tree for item
jama trace tree 12345 --direction upstream       # Upstream only
```

### Baselines
```bash
jama baseline list 1172                          # List baselines
jama baseline items 100                          # Items in baseline
jama baseline diff 100 101                       # Compare baselines
# Shows: +Added, ~Modified, -Removed
```

### Version History
```bash
jama history list 12345                          # Version history
jama history get 12345 3                         # Get version 3
jama history diff 12345 1 3                      # Compare versions
```

### Data Migration
```bash
# Export items to JSON (fast by default)
jama migrate export 123                          # Export all items
jama migrate export 123 --max 100                # Export first 100 items (fast)
jama migrate export 123 --parent 456 --max 50   # Export subtree, limit 50
jama migrate export 123 --type 45                # Export only type 45
jama migrate export 123 --relationships          # Include relationships (slower)

# Import from JSON
jama migrate import backup.json --project 456   # Import to project 456
jama migrate import backup.json -p 456 --dry-run  # Preview import

# Clone within same instance
jama migrate clone 123 456                       # Clone project 123 to 456
jama migrate clone 123 456 --source-parent 789   # Clone children of item

# Copy between instances (requires two profiles)
jama migrate copy 123 456 --from staging --to production

# Inspect export file
jama migrate info backup.json
```

### Attachments
```bash
# Upload a file and link it to an item (shows on the item's Attachments tab)
jama attachments upload 456 screenshot.png
jama attachments upload 456 report.pdf --name "Test report" --description "Nightly run"
jama attachments upload 456 screenshot.png --no-link    # create it, do not link it
jama attachments upload 456 screenshot.png --json       # ids and embed URL for scripts

# Download
jama attachments download 789 -o report.pdf             # by attachment ID
jama attachments download-url "https://jama.example.com/contour/attachment/9000/shot.png" -o shot.png
```

`upload` prints three things: the **attachment ID**, the **file ID** and the
**embed URL**. They are not interchangeable: an inline image in a rich-text field
must use the embed URL (`<base>/attachment/<fileId>/<file name>`), which is built
from the file ID. A URL built from the attachment ID shows a broken image. After
every upload the embed URL is checked through `GET /rest/v1/files?url=...`; if it
does not load, the command fails.

- Content type comes from the file extension (png, jpg/jpeg, gif, webp, svg, pdf;
  anything else is sent as `application/octet-stream`).
- Files larger than 50 MB are rejected; set `JAMA_MAX_ATTACHMENT_BYTES` to change the limit.
- Uploading the same file to the same project again reuses the earlier attachment
  instead of creating a duplicate (a local map under `~/.cache/jama-cli/uploads/`
  holds ids and URLs only). Use `--no-cache` to force a new upload.

### Screenshots in Test Runs
```bash
# Look at a test run and its steps
jama -o json testruns get 1234

# Embed screenshots in the run-level "Actual results"
jama testruns add-screenshot 1234 shot1.png shot2.png --caption "After login"

# ... or in the actual results of step 2 (steps are numbered from 1)
jama testruns add-screenshot 1234 failure.png --step 2 --caption "Error dialog"

# Write text/HTML: appended by default, --replace replaces only that field
jama testruns set-actual 1234 --html "<p>Works as expected</p>"
jama testruns set-actual 1234 --file result.html --step 3
jama testruns set-actual 1234 --html "<p>Retested</p>" --step 3 --replace
```

These commands change a test run with a read-modify-write: the run is read, only
the targeted field is changed, the complete step list is sent back, and the run is
read again to check that the other steps, their statuses and the existing HTML are
unchanged. Existing content is appended to, never replaced, unless `--replace` is
given. Running the same `add-screenshot` again neither uploads the file again nor
adds a second image. If Jama does not allow an attachment to be linked to a test
run, the image is still embedded and a warning says that it is missing from the
Attachments tab. If the run cannot be edited (locked cycle, missing permission),
Jama's error is shown and nothing is retried.

The same functions are available in Python (`JamaClient.upload_attachment`,
`download_attachment`, `download_embedded`, `embed_image_html`,
`append_to_actual_results`, `attach_screenshots_to_test_run`) and as MCP tools
(`upload_attachment`, `attach_screenshot_to_test_run`, `download_attachment`,
`get_test_run`, `update_test_run`). The MCP tools accept a file path on the
server's machine or base64 content, so they also work when the MCP client runs
on another machine.

#### Attachments with a browser-session (SSO) login

With `auth_type: session`, Jama may refuse the REST call that creates an
attachment for SSO users. Only in that case, and only under session auth,
jama-cli falls back to the endpoint the Jama web UI itself uses
(`POST <base>/ui/internal/attachments`), which creates the attachment and links
it to the item in one step. **This endpoint is not part of Jama's documented REST
API**: it can change or disappear with any Jama release. With `basic`, `api_key`
and `oauth` it is never called; a refused upload is reported as Jama's error.
Because that endpoint always links the attachment, `--no-link` cannot be honoured
when the fallback is used (a warning says so).

## MCP Server

### For Claude Desktop / Cline

Add to your MCP configuration:

```json
{
  "mcpServers": {
    "jama": {
      "command": "jama",
      "args": ["serve", "--stdio"]
    }
  }
}
```

### HTTP Server

```bash
# Start HTTP server
jama serve                             # Default: localhost:8000
jama serve --port 9000                 # Custom port
jama serve --api-key secret            # With authentication

# Access
curl http://localhost:8000/health
open http://localhost:8000/api/docs    # Swagger UI
```

### Available Operations

The MCP server exposes 70 Jama API operations:

| Category | Operations |
|----------|------------|
| Projects | get_projects, get_project |
| Items | get_items, get_item, create_item, update_item, delete_item |
| Relationships | get_relationships, create_relationship, delete_relationship |
| Types | get_item_types, get_item_type |
| Pick Lists | get_pick_lists, get_pick_list, get_pick_list_options |
| Tags | get_tags, get_tagged_items |
| Tests | get_test_plans, get_test_cycles, get_test_runs, get_test_run, update_test_run, attach_screenshot_to_test_run |
| Attachments | get_attachments, upload_attachment, download_attachment |
| ... | See full list in API documentation |

## Global Options

```bash
jama [OPTIONS] COMMAND [ARGS]

Options:
  -p, --profile TEXT     Profile name from config
  -o, --output FORMAT    Output: table, json, csv, yaml
  -v, --verbose          Increase verbosity (-v, -vv, -vvv)
  -q, --quiet            Suppress non-error output
  --version              Show version
  --help                 Show help
```

## Examples

### List requirements and export to CSV
```bash
jama -o csv items list 123 --type 45 > requirements.csv
```

### Get item as JSON for scripting
```bash
ITEM=$(jama -o json items get 456)
echo $ITEM | jq '.fields.name'
```

### Create item from script
```bash
jama items create 123 \
  --type 45 \
  --name "REQ-001: User Authentication" \
  --description "Users shall authenticate with SSO" \
  --field priority=High \
  --field status=Draft
```

### Trace upstream requirements
```bash
jama -o table relationships upstream 456
```

### Use different profile
```bash
jama -p staging items list 123
```

## Docker

A pre-built Docker image is available for running the Jama MCP server without installing Python.

```bash
docker pull ghcr.io/xorwell/jama-cli
```

### Quick Start

```bash
# Using environment variables
docker run -p 8000:8000 \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_API_KEY=your-api-key \
  ghcr.io/xorwell/jama-cli
```

The server starts on port 8000 with health checks, rate limiting, and Swagger UI at `/api/docs`.

### Using a Config File

Mount your existing `~/.jama/config.yml` into the container:

```bash
docker run -p 8000:8000 \
  -v ~/.jama/config.yml:/home/appuser/.jama/config.yml:ro \
  ghcr.io/xorwell/jama-cli
```

To use a specific profile from your config:

```bash
docker run -p 8000:8000 \
  -v ~/.jama/config.yml:/home/appuser/.jama/config.yml:ro \
  ghcr.io/xorwell/jama-cli \
  jama serve --host 0.0.0.0 --port 8000 --profile production
```

### Authentication Methods

```bash
# API Key
docker run -p 8000:8000 \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_API_KEY=your-api-key \
  ghcr.io/xorwell/jama-cli

# OAuth2 Client Credentials
docker run -p 8000:8000 \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_CLIENT_ID=your-client-id \
  -e JAMA_CLIENT_SECRET=your-client-secret \
  ghcr.io/xorwell/jama-cli

# Username/Password
docker run -p 8000:8000 \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_USERNAME=your-username \
  -e JAMA_PASSWORD=your-password \
  ghcr.io/xorwell/jama-cli
```

### Server Authentication

Protect the MCP server with an API key so only authorized clients can use it:

```bash
docker run -p 8000:8000 \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_API_KEY=your-jama-key \
  -e MCP_API_KEY=my-server-secret \
  ghcr.io/xorwell/jama-cli

# Clients must include: Authorization: Bearer my-server-secret
```

### Docker Compose

```yaml
services:
  jama-mcp:
    image: ghcr.io/xorwell/jama-cli
    ports:
      - "8000:8000"
    environment:
      - JAMA_URL=https://company.jamacloud.com
      - JAMA_API_KEY=${JAMA_API_KEY}
    # Or mount config:
    # volumes:
    #   - ~/.jama/config.yml:/home/appuser/.jama/config.yml:ro
    restart: unless-stopped
```

### Using the CLI via Docker

You can also use the Docker image to run CLI commands:

```bash
docker run --rm \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_API_KEY=your-api-key \
  ghcr.io/xorwell/jama-cli \
  jama projects list

docker run --rm \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_API_KEY=your-api-key \
  ghcr.io/xorwell/jama-cli \
  jama -o json items list 123
```

### Building Locally

```bash
docker build -t jama-cli .
docker run -p 8000:8000 -e JAMA_URL=... -e JAMA_API_KEY=... jama-cli
```

> **See [DOCKER.md](https://github.com/XORwell/jama-cli/blob/main/DOCKER.md) for full Docker documentation** including endpoints, image details, Kubernetes probes, and more.

## Development

```bash
# Clone
git clone https://github.com/XORwell/jama-cli.git
cd jama-cli

# Install with dev dependencies
poetry install

# Run tests
poetry run pytest

# Lint
poetry run ruff check .
poetry run black --check .

# Type check
poetry run mypy jama_cli jama_mcp_server
```

## License

MIT License - see [LICENSE](https://github.com/XORwell/jama-cli/blob/main/LICENSE)

## Contributing

Contributions welcome! Please read [CONTRIBUTING.md](https://github.com/XORwell/jama-cli/blob/main/CONTRIBUTING.md).

## Related

- [Jama REST API Documentation](https://dev.jamasoftware.com/api/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [py-jama-rest-client](https://github.com/jamasoftware-ps/py-jama-rest-client)
