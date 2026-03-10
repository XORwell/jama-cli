# Jama CLI

[![CI](https://img.shields.io/github/actions/workflow/status/XORwell/jama-cli/ci.yml?branch=main&label=CI)](https://github.com/XORwell/jama-cli/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/jama-cli.svg)](https://pypi.org/project/jama-cli/)
[![Python Versions](https://img.shields.io/pypi/pyversions/jama-cli.svg)](https://pypi.org/project/jama-cli/)


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
jama items get 456 --output json
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
jama items list 123 --output json      # JSON
jama items list 123 --output csv       # CSV
jama items list 123 --output yaml      # YAML
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

## CLI Commands

### Projects
```bash
jama projects list                     # List all projects
jama projects get 123                  # Get project details
jama projects list --output json       # JSON output
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
| Tests | get_test_plans, get_test_cycles, get_test_runs |
| Attachments | get_attachments, upload_attachment |
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
jama items list 123 --type 45 --output csv > requirements.csv
```

### Get item as JSON for scripting
```bash
ITEM=$(jama items get 456 --output json)
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
jama relationships upstream 456 --output table
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
  jama items list 123 --output json
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
