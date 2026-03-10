# Usage

The Jama MCP Server can be used both as a command-line application and as a library in your Python code.

## Command Line Interface

### Basic Usage

#### With Username/Password

```bash
jama serve --host 0.0.0.0 --port 8000
```

#### With API Token (Recommended)

```bash
jama serve --host 0.0.0.0 --port 8000
```

### Using Environment Variables

You can also set configuration using environment variables:

#### With Username/Password

```bash
export JAMA_URL=https://your-jama-instance.com
export JAMA_USERNAME=your_username
export JAMA_PASSWORD=your_password
export MCP_HOST=0.0.0.0
export MCP_PORT=8000

jama serve
```

#### With API Token (Recommended)

```bash
export JAMA_URL=https://your-jama-instance.com
export JAMA_TOKEN=your_api_token
export MCP_HOST=0.0.0.0
export MCP_PORT=8000

jama serve
```

Or use a .env file:

```bash
cp .env.example .env
# Edit the .env file with your settings
jama serve
```

## Library Usage

You can also use the Jama MCP Server as a library in your own Python code:

### With Username/Password

```python
from jama_mcp_server.models import JamaConfig
from jama_mcp_server.core.server import JamaMCPServer
import asyncio

# Configure Jama connection with username/password
config = JamaConfig(
    url="https://your-jama-instance.com",
    username="your_username",
    password="your_password"
)
```

### With API Token (Recommended)

```python
from jama_mcp_server.models import JamaConfig
from jama_mcp_server.core.server import JamaMCPServer
import asyncio

# Configure Jama connection with API token (recommended)
config = JamaConfig(
    url="https://your-jama-instance.com",
    token="your_api_token"
)

# Create server instance
server = JamaMCPServer(config)

# Run the server
async def main():
    await server.start("0.0.0.0", 8000)

asyncio.run(main())
```

## API Endpoints

The MCP server exposes the following endpoints:

### Health Check

```
GET /health
```

Returns the health status of the server.

### Query Endpoint

```
POST /query
```

The main endpoint for interacting with Jama. The request body should be a JSON object with the following structure:

```json
{
  "query": "get_projects",
  "parameters": {}
}
```

### Supported Queries

| Query | Parameters | Description |
|-------|------------|-------------|
| `get_projects` | None | Get all projects in Jama |
| `get_item` | `item_id` (int) | Get a specific item by ID |
| `create_item` | `item_data` (object) | Create a new item |
| `update_item` | `item_id` (int), `updated_fields` (object) | Update an existing item |
| `delete_item` | `item_id` (int) | Delete an item |
| `get_item_children` | `item_id` (int) | Get children of an item |
