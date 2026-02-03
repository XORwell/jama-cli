# API Reference

This document provides a comprehensive reference for the Jama MCP Server API.

## Models

### JamaConfig

Configuration for connecting to Jama.

```python
class JamaConfig(BaseModel):
    url: str
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    oauth: bool = False
```

### MCPRequest

Represents an incoming MCP request.

```python
class MCPRequest(BaseModel):
    query: str
    parameters: Dict[str, Any] = {}
```

### MCPResponse

Represents an outgoing MCP response.

```python
class MCPResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
```

### HealthCheckResponse

Represents a health check response.

```python
class HealthCheckResponse(BaseModel):
    status: str
    version: str
```

## Core Server

### JamaMCPServer

The main server class that handles MCP requests and communicates with Jama.

```python
class JamaMCPServer:
    def __init__(self, config: JamaConfig)
    async def start(self, host: str, port: int)
    async def stop()
    def health_check() -> HealthCheckResponse
    def query(request: MCPRequest) -> MCPResponse
```

## API Client

### JamaAPIClient

A client for interacting with the Jama API.

```python
class JamaAPIClient:
    def __init__(self, config: JamaConfig)
    def get_projects() -> List[Dict[str, Any]]
    def get_item(item_id: int) -> Dict[str, Any]
    def create_item(item_data: Dict[str, Any]) -> Dict[str, Any]
    def update_item(item_id: int, updated_fields: Dict[str, Any]) -> Dict[str, Any]
    def delete_item(item_id: int) -> bool
    def get_item_children(item_id: int) -> List[Dict[str, Any]]
```

## CLI

The command-line interface for the Jama MCP Server.

```python
@app.command()
def run(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind the server"),
    port: int = typer.Option(8000, "--port", help="Port to bind the server"),
    jama_url: str = typer.Option(None, "--jama-url", help="Jama API URL"),
    jama_token: str = typer.Option(None, "--jama-token", help="Jama API token (recommended)"),
    jama_username: str = typer.Option(None, "--jama-username", help="Jama API username"),
    jama_password: str = typer.Option(None, "--jama-password", help="Jama API password"),
    jama_oauth: bool = typer.Option(False, "--jama-oauth", help="Use OAuth for Jama authentication"),
)
```
