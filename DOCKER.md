# Jama CLI - Docker Image

Pre-built Docker image for the Jama MCP (Model Context Protocol) server, providing AI assistants with full access to Jama requirements management.

> **DISCLAIMER**: This is an unofficial community project and is not associated with, endorsed by, or affiliated with Jama Software in any way.

**GitHub**: [XORwell/jama-cli](https://github.com/XORwell/jama-cli)
**PyPI**: [jama-cli](https://pypi.org/project/jama-cli/)

## Quick Start

```bash
docker run -p 8000:8000 \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_API_KEY=your-api-key \
  ghcr.io/xorwell/jama-cli
```

The MCP server starts on port 8000 with:
- REST API for Jama operations
- Swagger UI at `http://localhost:8000/api/docs`
- Health check at `http://localhost:8000/health`
- 70 Jama API operations (100% coverage)

## Configuration

### Option 1: Environment Variables

Pass your Jama credentials directly:

```bash
# API Key authentication
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

### Option 2: Config File

Mount your `config.yml` into the container:

```bash
docker run -p 8000:8000 \
  -v ~/.jama/config.yml:/home/appuser/.jama/config.yml:ro \
  ghcr.io/xorwell/jama-cli
```

Example `config.yml`:

```yaml
default_profile: production

profiles:
  production:
    url: https://company.jamacloud.com
    auth_type: api_key
    api_key: your-api-key
```

To select a specific profile:

```bash
docker run -p 8000:8000 \
  -v ~/.jama/config.yml:/home/appuser/.jama/config.yml:ro \
  ghcr.io/xorwell/jama-cli \
  jama serve --host 0.0.0.0 --port 8000 --profile staging
```

## Securing the Server

Protect the MCP server endpoint with an API key:

```bash
docker run -p 8000:8000 \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_API_KEY=your-jama-key \
  -e MCP_API_KEY=my-server-secret \
  ghcr.io/xorwell/jama-cli
```

Clients must include the header: `Authorization: Bearer my-server-secret`

Public endpoints (`/health`, `/ready`, `/live`) are exempt from authentication.

## Docker Compose

```yaml
services:
  jama-mcp:
    image: ghcr.io/xorwell/jama-cli
    ports:
      - "8000:8000"
    environment:
      - JAMA_URL=https://company.jamacloud.com
      - JAMA_API_KEY=${JAMA_API_KEY}
      - MCP_API_KEY=${MCP_API_KEY}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
```

## Using the CLI

The image also includes the full `jama` CLI:

```bash
# List projects
docker run --rm \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_API_KEY=your-api-key \
  ghcr.io/xorwell/jama-cli \
  jama projects list

# Export items to JSON
docker run --rm \
  -e JAMA_URL=https://company.jamacloud.com \
  -e JAMA_API_KEY=your-api-key \
  -v $(pwd):/data \
  ghcr.io/xorwell/jama-cli \
  jama migrate export 123 --output /data/backup.json
```

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check (no auth required) |
| `GET /ready` | Kubernetes readiness probe |
| `GET /live` | Kubernetes liveness probe |
| `GET /metrics` | Server metrics |
| `GET /api/docs` | Swagger UI |
| `POST /v1/invoke` | Execute MCP operations |
| `POST /v1/batch` | Batch operations |
| `GET /v1/sse` | Server-Sent Events stream |

## Image Details

- **Base**: `python:3.11-slim`
- **Runs as**: Non-root user (`appuser`, UID 1000)
- **Port**: 8000
- **Config path**: `/home/appuser/.jama/config.yml`
- **Health check**: Built-in (every 30s)

## Tags

| Tag | Description |
|-----|-------------|
| `latest` | Latest stable release |
| `0.1.0` | Specific version |
| `0.1` | Latest patch for minor version |

## License

MIT License - see [LICENSE](https://github.com/XORwell/jama-cli/blob/main/LICENSE)
