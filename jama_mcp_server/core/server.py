"""
Core MCP server implementation for Jama integration.

This module provides a production-ready HTTP server for the Jama MCP protocol
with support for security features, metrics, and graceful shutdown.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import re
import signal
import time
from contextlib import suppress
from typing import Any

from aiohttp import web
from aiohttp_swagger3 import SwaggerDocs, SwaggerUiSettings
from loguru import logger
from py_jama_rest_client.client import JamaClient

from jama_mcp_server import __version__
from jama_mcp_server.models import (
    BatchRequest,
    BatchResponse,
    ErrorResponse,
    HealthCheckResponse,
    JamaConfig,
    MCPRequest,
    MCPResponse,
)


class JamaMCPServer:
    """MCP server implementation for Jama API with both read and write capabilities.

    This server provides:
    - Full CRUD operations for Jama items
    - HTTP REST API with OpenAPI documentation
    - SSE streaming for real-time updates
    - Batch operations for improved performance
    - Security features (rate limiting, request validation)
    - Health checks and metrics
    """

    # Rate limiting configuration
    RATE_LIMIT_WINDOW = 60  # seconds
    RATE_LIMIT_MAX_REQUESTS = 100

    # Endpoints that don't require authentication
    PUBLIC_ENDPOINTS = {"/health", "/ready", "/live", "/api/docs"}

    def __init__(
        self,
        config: JamaConfig,
        host: str = "localhost",
        port: int = 8000,
        api_key: str | None = None,
    ) -> None:
        """
        Initialize the Jama MCP server.

        Args:
            config: Jama configuration
            host: The host to bind the MCP server to
            port: The port to listen on
            api_key: Optional API key for server authentication (if set, requires Bearer token)
        """
        self.config = config
        self.host = host
        self.port = port
        self.api_key = api_key
        self.jama_client: JamaClient | None = None
        self._running = False
        self._start_time: float | None = None
        self._request_count = 0
        self._error_count = 0
        self._rate_limit_store: dict[str, list[float]] = {}

        # Setup application
        self.app = web.Application(
            middlewares=[
                self._error_middleware,
                self._auth_middleware,
                self._security_middleware,
                self._logging_middleware,
            ]
        )

        # Setup routes
        self.app.add_routes(
            [
                web.post("/v1/invoke", self._handle_invoke),
                web.post("/v1/batch", self._handle_batch),
                web.get("/v1/sse", self._handle_sse),
                web.post("/v1/messages", self._handle_sse_message),
                web.get("/health", self._handle_health),
                web.get("/metrics", self._handle_metrics),
                web.get("/ready", self._handle_ready),
                web.get("/live", self._handle_live),
            ]
        )

        # Setup Swagger documentation
        self._setup_swagger()

        self.runner: web.AppRunner | None = None
        self._shutdown_event: asyncio.Event | None = None

    def _setup_swagger(self) -> None:
        """Setup OpenAPI/Swagger documentation."""
        SwaggerDocs(
            self.app,
            swagger_ui_settings=SwaggerUiSettings(path="/api/docs"),
            title="Jama MCP Server API",
            version=__version__,
            description="""
# Jama MCP Server API

A Model Context Protocol (MCP) server for Jama with full read/write capabilities.

## Features
- **Full CRUD Operations**: Create, Read, Update, Delete Jama items
- **Project Management**: Access and manage Jama projects
- **Relationship Management**: Create and manage item relationships
- **Dual Protocol**: HTTP REST API and stdio MCP support
- **Batch Operations**: Execute multiple operations efficiently

## Authentication
Supports multiple authentication methods:
- OAuth2 client credentials
- API tokens
- Username/password

## Base URL
All API endpoints are relative to the server base URL (default: http://localhost:8000)
            """,
        )

    @web.middleware
    async def _error_middleware(self, request: web.Request, handler: Any) -> web.Response:
        """Middleware for consistent error handling."""
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in request: {e}")
            return web.json_response(
                ErrorResponse(
                    error="Invalid JSON in request body", error_code="INVALID_JSON"
                ).model_dump(),
                status=400,
            )
        except Exception as e:
            self._error_count += 1
            logger.exception(f"Unhandled error in request handler: {e}")
            return web.json_response(
                ErrorResponse(
                    error="Internal server error",
                    error_code="INTERNAL_ERROR",
                    details={"message": str(e)},
                ).model_dump(),
                status=500,
            )

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler: Any) -> web.Response:
        """Middleware for API key authentication.

        If an API key is configured, requests must include a valid Bearer token.
        Public endpoints (health, ready, live) are exempt from authentication.
        """
        # Skip auth for public endpoints
        if request.path in self.PUBLIC_ENDPOINTS or request.path.startswith("/api/docs"):
            return await handler(request)

        # If no API key configured, allow all requests
        if not self.api_key:
            return await handler(request)

        # Check for Authorization header
        auth_header = request.headers.get("Authorization", "")

        if not auth_header:
            return web.json_response(
                ErrorResponse(
                    error="Missing Authorization header",
                    error_code="UNAUTHORIZED",
                ).model_dump(),
                status=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Validate Bearer token
        if not auth_header.startswith("Bearer "):
            return web.json_response(
                ErrorResponse(
                    error="Invalid Authorization header format. Use 'Bearer <token>'",
                    error_code="UNAUTHORIZED",
                ).model_dump(),
                status=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[7:]  # Remove "Bearer " prefix

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(token, self.api_key):
            return web.json_response(
                ErrorResponse(
                    error="Invalid API key",
                    error_code="FORBIDDEN",
                ).model_dump(),
                status=403,
            )

        return await handler(request)

    @web.middleware
    async def _security_middleware(self, request: web.Request, handler: Any) -> web.Response:
        """Middleware for security headers and basic protection."""
        # Check content length
        content_length = request.content_length
        if content_length and content_length > 10 * 1024 * 1024:  # 10MB limit
            return web.json_response(
                ErrorResponse(
                    error="Request body too large", error_code="PAYLOAD_TOO_LARGE"
                ).model_dump(),
                status=413,
            )

        # Simple rate limiting
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return web.json_response(
                ErrorResponse(
                    error="Rate limit exceeded", error_code="RATE_LIMIT_EXCEEDED"
                ).model_dump(),
                status=429,
            )

        response = await handler(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Cache-Control"] = "no-store"

        return response

    @web.middleware
    async def _logging_middleware(self, request: web.Request, handler: Any) -> web.Response:
        """Middleware for request logging."""
        start_time = time.time()
        self._request_count += 1

        # Log request (mask sensitive data)
        logger.debug(f"Request: {request.method} {request.path} " f"from {request.remote}")

        response = await handler(request)

        # Log response
        duration = time.time() - start_time
        logger.info(f"{request.method} {request.path} - " f"{response.status} - {duration:.3f}s")

        return response

    def _check_rate_limit(self, client_ip: str) -> bool:
        """Check if request is within rate limits.

        Args:
            client_ip: Client IP address

        Returns:
            True if request is allowed, False if rate limited
        """
        current_time = time.time()
        window_start = current_time - self.RATE_LIMIT_WINDOW

        # Clean old entries and get current window
        if client_ip in self._rate_limit_store:
            self._rate_limit_store[client_ip] = [
                t for t in self._rate_limit_store[client_ip] if t > window_start
            ]
        else:
            self._rate_limit_store[client_ip] = []

        # Check limit
        if len(self._rate_limit_store[client_ip]) >= self.RATE_LIMIT_MAX_REQUESTS:
            return False

        # Record request
        self._rate_limit_store[client_ip].append(current_time)
        return True

    async def start(self) -> None:
        """Start the MCP server."""
        if self._running:
            logger.warning("Server is already running")
            return

        logger.info(f"Starting Jama MCP server on {self.host}:{self.port}")

        # Initialize Jama client
        try:
            await self._initialize_jama_client()
        except Exception as e:
            logger.error(f"Failed to connect to Jama: {e}")
            raise RuntimeError(f"Failed to connect to Jama: {e}") from e

        # Start web server
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()

        self._running = True
        self._start_time = time.time()
        self._shutdown_event = asyncio.Event()

        logger.info(
            f"Jama MCP server is running at http://{self.host}:{self.port}\n"
            f"  - API docs: http://{self.host}:{self.port}/api/docs\n"
            f"  - Health: http://{self.host}:{self.port}/health"
        )

    async def _initialize_jama_client(self) -> None:
        """Initialize the Jama client with appropriate authentication."""
        logger.info(f"Connecting to Jama at {self.config.url}")
        logger.debug(f"Auth config: {self.config.get_masked_credentials()}")

        # Use OAuth client credentials if provided
        if self.config.client_id and self.config.client_secret:
            logger.info("Using OAuth client credentials authentication")
            self.jama_client = JamaClient(
                host_domain=self.config.url,
                credentials=(self.config.client_id, self.config.client_secret),
                oauth=True,
            )
        # Use API key if provided
        elif self.config.api_key:
            logger.info("Using API key authentication")
            self.jama_client = JamaClient(
                host_domain=self.config.url,
                credentials=("api_key", self.config.api_key),
                oauth=self.config.oauth,
            )
        # Fall back to username/password
        else:
            logger.info("Using username/password authentication")
            self.jama_client = JamaClient(
                host_domain=self.config.url,
                credentials=(self.config.username, self.config.password),
                oauth=self.config.oauth,
            )

        # Test connection
        self.jama_client.get_projects()
        logger.info(f"Successfully connected to Jama instance at {self.config.url}")

    async def stop(self) -> None:
        """Stop the MCP server gracefully."""
        if not self._running:
            logger.warning("Server is not running")
            return

        logger.info("Stopping Jama MCP server...")

        if self._shutdown_event:
            self._shutdown_event.set()

        if self.runner:
            await self.runner.cleanup()

        self._running = False
        self.jama_client = None

        logger.info("Jama MCP server stopped")

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        if self._shutdown_event:
            await self._shutdown_event.wait()

    def setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self._handle_signal(s)))

    async def _handle_signal(self, sig: signal.Signals) -> None:
        """Handle shutdown signal."""
        logger.info(f"Received signal {sig.name}, shutting down...")
        await self.stop()

    async def health_check(self) -> HealthCheckResponse:
        """Check if the server is healthy.

        Returns:
            Health status information
        """
        status: str = "healthy" if self._running and self.jama_client is not None else "unhealthy"
        uptime = time.time() - self._start_time if self._start_time else None

        health_data = HealthCheckResponse(
            status=status,  # type: ignore
            jama_connected=self.jama_client is not None,
            jama_url=self.config.url,
            version=__version__,
            uptime_seconds=uptime,
        )

        # Try to get Jama project count if connected
        if self.jama_client:
            try:
                projects = self.jama_client.get_projects()
                health_data.jama_projects_count = len(projects)
            except Exception as e:
                health_data.status = "degraded"
                health_data.error = str(e)

        return health_data

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Handle an MCP request.

        Args:
            request: The MCP request

        Returns:
            The MCP response
        """
        if not self.jama_client:
            return MCPResponse(
                response=json.dumps(
                    {
                        "success": False,
                        "error": "Jama client not initialized",
                        "error_code": "CLIENT_NOT_INITIALIZED",
                    }
                ),
                metadata={"status": "error", "error": "Jama client not initialized"},
            )

        prompt = request.prompt
        params = request.parameters or {}

        try:
            # Extract the intent from the prompt
            intent, parsed_params = self._parse_prompt(prompt, params)

            # Execute the corresponding Jama operation
            result = await self._execute_jama_operation(intent, parsed_params)

            # Format the response
            return self._format_response(intent, result)

        except ValueError as e:
            # Validation errors (missing parameters, etc.)
            logger.warning(f"Validation error in Jama request: {e}")
            return MCPResponse(
                response=json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                        "error_code": "VALIDATION_ERROR",
                        "intent": params.get("intent", "unknown"),
                    }
                ),
                metadata={"status": "error", "error_type": "validation", "error": str(e)},
            )
        except Exception as e:
            # Generic errors from Jama API or other issues
            logger.error(f"Error handling Jama request: {e}", exc_info=True)

            # Try to determine error type
            error_code = self._classify_error(e)

            return MCPResponse(
                response=json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                        "error_code": error_code,
                        "intent": params.get("intent", "unknown"),
                    }
                ),
                metadata={"error": str(e), "status": "error"},
            )

    def _classify_error(self, error: Exception) -> str:
        """Classify an error into an error code.

        Args:
            error: The exception to classify

        Returns:
            Error code string
        """
        error_str = str(error)

        if "401" in error_str or "Unauthorized" in error_str:
            return "AUTHENTICATION_ERROR"
        elif "403" in error_str or "Forbidden" in error_str:
            return "PERMISSION_ERROR"
        elif "404" in error_str or "Not Found" in error_str:
            return "NOT_FOUND"
        elif "500" in error_str:
            return "SERVER_ERROR"
        elif "timeout" in error_str.lower():
            return "TIMEOUT_ERROR"
        elif "connection" in error_str.lower():
            return "CONNECTION_ERROR"
        else:
            return "UNKNOWN_ERROR"

    async def handle_batch_request(self, requests: list[MCPRequest]) -> list[MCPResponse]:
        """Handle multiple MCP requests in batch.

        Args:
            requests: List of MCP requests

        Returns:
            List of MCP responses
        """
        responses = []
        for request in requests:
            try:
                response = await self.handle_request(request)
                responses.append(response)
            except Exception as e:
                logger.error(f"Error in batch request: {e}")
                responses.append(
                    MCPResponse(
                        response=json.dumps(
                            {"success": False, "error": str(e), "error_code": "BATCH_ITEM_ERROR"}
                        ),
                        metadata={"status": "error", "error": str(e)},
                    )
                )
        return responses

    async def _execute_jama_operation(self, intent: str, params: dict[str, Any]) -> Any:
        """Execute a Jama operation based on the parsed intent and parameters.

        Args:
            intent: The operation intent (get_projects, get_items, create_item, etc.)
            params: Parameters for the operation

        Returns:
            The result of the operation

        Raises:
            ValueError: If required parameters are missing
        """
        # Use asyncio.to_thread for blocking operations (Python 3.9+)
        loop = asyncio.get_event_loop()

        # Read operations
        if intent == "get_projects":
            return await loop.run_in_executor(None, self.jama_client.get_projects)

        elif intent == "get_project_by_id":
            project_id = params.get("project_id")
            if not project_id:
                raise ValueError("Project ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_project, project_id)

        elif intent == "get_items":
            project_id = params.get("project_id")
            if not project_id:
                raise ValueError("Project ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_items, project_id)

        elif intent == "get_item_by_id":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_item, item_id)

        elif intent == "get_item_types":
            project_id = params.get("project_id")
            if not project_id:
                raise ValueError("Project ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_item_types, project_id)

        elif intent == "get_item_children":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_item_children, item_id)

        elif intent == "get_relationships":
            project_id = params.get("project_id")
            if not project_id:
                raise ValueError("Project ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_relationships, project_id)

        elif intent == "get_relationship":
            relationship_id = params.get("relationship_id")
            if not relationship_id:
                raise ValueError("Relationship ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_relationship, relationship_id
            )

        elif intent == "get_item_upstream_relationships":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_items_upstream_relationships, item_id
            )

        elif intent == "get_item_downstream_relationships":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_items_downstream_relationships, item_id
            )

        elif intent == "get_item_upstream_related":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_items_upstream_related, item_id
            )

        elif intent == "get_item_downstream_related":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_items_downstream_related, item_id
            )

        elif intent == "get_item_type":
            item_type_id = params.get("item_type_id")
            if not item_type_id:
                raise ValueError("Item type ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_item_type, item_type_id)

        elif intent == "get_pick_lists":
            return await loop.run_in_executor(None, self.jama_client.get_pick_lists)

        elif intent == "get_pick_list":
            pick_list_id = params.get("pick_list_id")
            if not pick_list_id:
                raise ValueError("Pick list ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_pick_list, pick_list_id)

        elif intent == "get_pick_list_options":
            pick_list_id = params.get("pick_list_id")
            if not pick_list_id:
                raise ValueError("Pick list ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_pick_list_options, pick_list_id
            )

        elif intent == "get_pick_list_option":
            pick_list_option_id = params.get("pick_list_option_id")
            if not pick_list_option_id:
                raise ValueError("Pick list option ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_pick_list_option, pick_list_option_id
            )

        elif intent == "get_tags":
            project_id = params.get("project_id")
            if not project_id:
                raise ValueError("Project ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_tags, project_id)

        elif intent == "get_tagged_items":
            tag_id = params.get("tag_id")
            if not tag_id:
                raise ValueError("Tag ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_tagged_items, tag_id)

        elif intent == "get_test_cycle":
            test_cycle_id = params.get("test_cycle_id")
            if not test_cycle_id:
                raise ValueError("Test cycle ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_test_cycle, test_cycle_id)

        elif intent == "get_test_runs":
            test_cycle_id = params.get("test_cycle_id")
            if not test_cycle_id:
                raise ValueError("Test cycle ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_testruns, test_cycle_id)

        # Write operations
        elif intent == "create_item":
            required_fields = [
                "project_id",
                "item_type_id",
                "child_item_type_id",
                "location",
                "fields",
            ]
            for field in required_fields:
                if field not in params:
                    raise ValueError(f"Required field '{field}' is missing")

            def create_item() -> Any:
                return self.jama_client.post_item(
                    project=params["project_id"],
                    item_type_id=params["item_type_id"],
                    child_item_type_id=params["child_item_type_id"],
                    location=params["location"],
                    fields=params["fields"],
                )

            return await loop.run_in_executor(None, create_item)

        elif intent == "update_item":
            item_id = params.get("item_id")
            fields = params.get("fields")

            if not item_id or not fields:
                raise ValueError("Item ID and fields are required for update")

            def update_item() -> Any:
                # Convert fields dict to JSON patch operations
                patches = [
                    {"op": "replace", "path": f"/fields/{key}", "value": value}
                    for key, value in fields.items()
                ]
                return self.jama_client.patch_item(item_id, patches)

            return await loop.run_in_executor(None, update_item)

        elif intent == "patch_item":
            item_id = params.get("item_id")
            patches = params.get("patches")

            if not item_id or not patches:
                raise ValueError("Item ID and patches are required")

            def patch_item() -> Any:
                return self.jama_client.patch_item(item_id, patches)

            return await loop.run_in_executor(None, patch_item)

        elif intent == "delete_item":
            item_id = params.get("item_id")

            if not item_id:
                raise ValueError("Item ID is required for deletion")

            return await loop.run_in_executor(None, self.jama_client.delete_item, item_id)

        # Attachment operations
        elif intent == "get_attachment":
            attachment_id = params.get("attachment_id")
            if not attachment_id:
                raise ValueError("Attachment ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_attachment, attachment_id)

        elif intent == "post_item_attachment":
            item_id = params.get("item_id")
            file_path = params.get("file_path")
            if not item_id or not file_path:
                raise ValueError("Item ID and file_path are required")
            return await loop.run_in_executor(
                None, self.jama_client.post_item_attachment, item_id, file_path
            )

        elif intent == "post_project_attachment":
            project_id = params.get("project_id")
            file_path = params.get("file_path")
            if not project_id or not file_path:
                raise ValueError("Project ID and file_path are required")
            return await loop.run_in_executor(
                None, self.jama_client.post_project_attachment, project_id, file_path
            )

        elif intent == "put_attachments_file":
            attachment_id = params.get("attachment_id")
            file_path = params.get("file_path")
            if not attachment_id or not file_path:
                raise ValueError("Attachment ID and file_path are required")
            return await loop.run_in_executor(
                None, self.jama_client.put_attachments_file, attachment_id, file_path
            )

        # Baseline operations
        elif intent == "get_baselines":
            project_id = params.get("project_id")
            if not project_id:
                raise ValueError("Project ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_baselines, project_id)

        elif intent == "get_baseline":
            baseline_id = params.get("baseline_id")
            if not baseline_id:
                raise ValueError("Baseline ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_baseline, baseline_id)

        elif intent == "get_baselines_versioneditems":
            baseline_id = params.get("baseline_id")
            if not baseline_id:
                raise ValueError("Baseline ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_baselines_versioneditems, baseline_id
            )

        # User operations
        elif intent == "get_current_user":
            return await loop.run_in_executor(None, self.jama_client.get_current_user)

        elif intent == "get_user":
            user_id = params.get("user_id")
            if not user_id:
                raise ValueError("User ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_user, user_id)

        elif intent == "get_users":
            return await loop.run_in_executor(None, self.jama_client.get_users)

        elif intent == "post_user":
            user_data = params.get("user_data")
            if not user_data:
                raise ValueError("User data is required")
            return await loop.run_in_executor(None, self.jama_client.post_user, user_data)

        elif intent == "put_user":
            user_id = params.get("user_id")
            user_data = params.get("user_data")
            if not user_id or not user_data:
                raise ValueError("User ID and user data are required")
            return await loop.run_in_executor(None, self.jama_client.put_user, user_id, user_data)

        elif intent == "put_user_active":
            user_id = params.get("user_id")
            active = params.get("active")
            if user_id is None or active is None:
                raise ValueError("User ID and active status are required")
            return await loop.run_in_executor(
                None, self.jama_client.put_user_active, user_id, active
            )

        # Item version operations
        elif intent == "get_item_versions":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_item_versions, item_id)

        elif intent == "get_item_version":
            version_id = params.get("version_id")
            if not version_id:
                raise ValueError("Version ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_item_version, version_id)

        elif intent == "get_versioned_item":
            item_id = params.get("item_id")
            version_num = params.get("version_num")
            if not item_id or not version_num:
                raise ValueError("Item ID and version number are required")
            return await loop.run_in_executor(
                None, self.jama_client.get_versioned_item, item_id, version_num
            )

        elif intent == "get_abstract_item_versions":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_abstract_item_versions, item_id
            )

        elif intent == "get_abstract_versioned_item":
            item_id = params.get("item_id")
            version_num = params.get("version_num")
            if not item_id or not version_num:
                raise ValueError("Item ID and version number are required")
            return await loop.run_in_executor(
                None, self.jama_client.get_abstract_versioned_item, item_id, version_num
            )

        # Item tag operations
        elif intent == "get_item_tags":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_item_tags, item_id)

        elif intent == "post_item_tag":
            item_id = params.get("item_id")
            tag_id = params.get("tag_id")
            if not item_id or not tag_id:
                raise ValueError("Item ID and tag ID are required")
            return await loop.run_in_executor(None, self.jama_client.post_item_tag, item_id, tag_id)

        elif intent == "post_tag":
            tag_data = params.get("tag_data")
            if not tag_data:
                raise ValueError("Tag data is required")
            return await loop.run_in_executor(None, self.jama_client.post_tag, tag_data)

        # Workflow operations
        elif intent == "get_item_workflow_transitions":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_item_workflow_transitions, item_id
            )

        # Filter operations
        elif intent == "get_filter_results":
            filter_id = params.get("filter_id")
            if not filter_id:
                raise ValueError("Filter ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_filter_results, filter_id)

        # Item lock operations
        elif intent == "get_item_lock":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_item_lock, item_id)

        elif intent == "put_item_lock":
            item_id = params.get("item_id")
            locked = params.get("locked")
            if item_id is None or locked is None:
                raise ValueError("Item ID and locked status are required")
            return await loop.run_in_executor(None, self.jama_client.put_item_lock, item_id, locked)

        # Test management write operations
        elif intent == "put_test_run":
            test_run_id = params.get("test_run_id")
            test_run_data = params.get("test_run_data")
            if not test_run_id or not test_run_data:
                raise ValueError("Test run ID and data are required")
            return await loop.run_in_executor(
                None, self.jama_client.put_test_run, test_run_id, test_run_data
            )

        elif intent == "post_testplans_testcycles":
            test_plan_id = params.get("test_plan_id")
            test_cycle_data = params.get("test_cycle_data")
            if not test_plan_id or not test_cycle_data:
                raise ValueError("Test plan ID and test cycle data are required")
            return await loop.run_in_executor(
                None, self.jama_client.post_testplans_testcycles, test_plan_id, test_cycle_data
            )

        # Relationship rule sets
        elif intent == "get_relationship_rule_sets":
            return await loop.run_in_executor(None, self.jama_client.get_relationship_rule_sets)

        elif intent == "get_relationship_rule_set":
            rule_set_id = params.get("rule_set_id")
            if not rule_set_id:
                raise ValueError("Rule set ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_relationship_rule_set, rule_set_id
            )

        elif intent == "get_relationship_rule_set_projects":
            rule_set_id = params.get("rule_set_id")
            if not rule_set_id:
                raise ValueError("Rule set ID is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_relationship_rule_set_projects, rule_set_id
            )

        # Abstract items and sync operations
        elif intent == "get_abstract_items":
            project_id = params.get("project_id")
            if project_id:
                return await loop.run_in_executor(
                    None, self.jama_client.get_abstract_items, project_id
                )
            else:
                return await loop.run_in_executor(None, self.jama_client.get_abstract_items)

        elif intent == "get_abstract_items_from_doc_key":
            doc_key = params.get("doc_key")
            if not doc_key:
                raise ValueError("Document key is required")
            return await loop.run_in_executor(
                None, self.jama_client.get_abstract_items_from_doc_key, doc_key
            )

        elif intent == "post_item_sync":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(None, self.jama_client.post_item_sync, item_id)

        elif intent == "get_items_synceditems":
            item_id = params.get("item_id")
            if not item_id:
                raise ValueError("Item ID is required")
            return await loop.run_in_executor(None, self.jama_client.get_items_synceditems, item_id)

        elif intent == "get_items_synceditems_status":
            item_id = params.get("item_id")
            sync_status_id = params.get("sync_status_id")
            if not item_id or not sync_status_id:
                raise ValueError("Item ID and sync status ID are required")
            return await loop.run_in_executor(
                None, self.jama_client.get_items_synceditems_status, item_id, sync_status_id
            )

        else:
            raise ValueError(f"Unsupported operation: {intent}")

    def _parse_prompt(self, prompt: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Parse the prompt to determine the operation and extract parameters.

        Args:
            prompt: The MCP prompt
            params: Parameters provided with the request

        Returns:
            Tuple of (intent, parameters)
        """
        # First check if the intent and parameters are explicitly provided
        if "intent" in params:
            return params["intent"], params

        # Simple keyword-based intent detection
        prompt_lower = prompt.lower()

        # Extract parameters from the prompt
        extracted_params: dict[str, Any] = {}

        # Extract IDs
        project_id_match = re.search(r"project(?:\s+id)?[:\s]+(\d+)", prompt_lower)
        if project_id_match:
            extracted_params["project_id"] = int(project_id_match.group(1))

        item_id_match = re.search(r"item(?:\s+id)?[:\s]+(\d+)", prompt_lower)
        if item_id_match:
            extracted_params["item_id"] = int(item_id_match.group(1))

        # Merge with provided params
        merged_params = {**extracted_params, **params}

        # Determine intent based on keywords
        if "create" in prompt_lower or "add" in prompt_lower or "new" in prompt_lower:
            if "item" in prompt_lower:
                return "create_item", merged_params

        elif "update" in prompt_lower or "change" in prompt_lower or "modify" in prompt_lower:
            if "item" in prompt_lower:
                return "update_item", merged_params

        elif "patch" in prompt_lower:
            if "item" in prompt_lower:
                return "patch_item", merged_params

        elif "delete" in prompt_lower or "remove" in prompt_lower:
            if "item" in prompt_lower:
                return "delete_item", merged_params

        elif (
            "get" in prompt_lower
            or "list" in prompt_lower
            or "fetch" in prompt_lower
            or "show" in prompt_lower
        ):
            if "project" in prompt_lower and "item" not in prompt_lower:
                if "id" in prompt_lower and "project_id" in merged_params:
                    return "get_project_by_id", merged_params
                else:
                    return "get_projects", merged_params
            elif "item" in prompt_lower:
                if "id" in prompt_lower and "item_id" in merged_params:
                    return "get_item_by_id", merged_params
                elif "project_id" in merged_params:
                    return "get_items", merged_params
            elif "type" in prompt_lower and "project_id" in merged_params:
                return "get_item_types", merged_params

        # Default to getting projects if intent cannot be determined
        logger.warning(
            f"Could not determine intent from prompt: '{prompt}'. Defaulting to get_projects."
        )
        return "get_projects", merged_params

    def _format_response(self, intent: str, result: Any) -> MCPResponse:
        """Format the Jama API result into an MCP response.

        Args:
            intent: The original intent
            result: The API result

        Returns:
            Formatted MCP response with properly serialized JSON
        """
        try:
            # Serialize the result to JSON string
            response_json = json.dumps(result, indent=2, default=str)

            return MCPResponse(
                response=response_json,
                metadata={
                    "intent": intent,
                    "status": "success",
                    "result_type": type(result).__name__,
                    "result_count": len(result) if isinstance(result, list | dict) else None,
                },
            )
        except Exception as e:
            logger.error(f"Error serializing response: {e}")
            # Fallback to string representation
            return MCPResponse(
                response=str(result),
                metadata={"intent": intent, "status": "success", "serialization_error": str(e)},
            )

    async def _handle_batch(self, request: web.Request) -> web.Response:
        """Handle batch invoke requests."""
        try:
            data = await request.json()

            # Validate using Pydantic model
            batch_request = BatchRequest(**data)

            responses = await self.handle_batch_request(batch_request.requests)

            errors_count = sum(
                1 for r in responses if r.metadata and r.metadata.get("status") == "error"
            )

            return web.json_response(
                BatchResponse(
                    responses=responses, count=len(responses), errors_count=errors_count
                ).model_dump()
            )
        except Exception as e:
            logger.error(f"Error handling batch request: {e}")
            return web.json_response(
                ErrorResponse(error=str(e), error_code="BATCH_ERROR").model_dump(), status=400
            )

    async def _handle_sse(self, request: web.Request) -> web.Response:
        """Handle SSE (Server-Sent Events) connection for MCP streaming."""
        response = web.StreamResponse()
        response.headers["Content-Type"] = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Connection"] = "keep-alive"
        response.headers["X-Accel-Buffering"] = "no"  # Disable nginx buffering

        await response.prepare(request)

        try:
            # Send initial connection event
            connection_event = {
                "status": "connected",
                "server": "jama-mcp-server",
                "version": __version__,
                "capabilities": {"read": True, "write": True, "batch": True, "streaming": True},
            }
            await response.write(b"event: connected\n")
            await response.write(f"data: {json.dumps(connection_event)}\n\n".encode())

            # Keep connection alive with heartbeats
            while True:
                await asyncio.sleep(30)  # Heartbeat every 30 seconds
                heartbeat = {"timestamp": time.time()}
                await response.write(b"event: heartbeat\n")
                await response.write(f"data: {json.dumps(heartbeat)}\n\n".encode())

        except (ConnectionResetError, asyncio.CancelledError):
            logger.info("SSE connection closed")
        except Exception as e:
            logger.error(f"SSE error: {e}")
        finally:
            with suppress(Exception):
                await response.write_eof()

        return response

    async def _handle_sse_message(self, request: web.Request) -> web.Response:
        """Handle messages sent to SSE connection."""
        try:
            data = await request.json()
            session_id = data.get("session_id")
            message = data.get("message")

            if not session_id or not message:
                return web.json_response(
                    ErrorResponse(
                        error="Missing session_id or message", error_code="INVALID_REQUEST"
                    ).model_dump(),
                    status=400,
                )

            # Process message as MCP request
            if "prompt" in message:
                mcp_request = MCPRequest(**message)
                response = await self.handle_request(mcp_request)

                return web.json_response(
                    {
                        "status": "processed",
                        "session_id": session_id,
                        "response": response.model_dump(),
                    }
                )
            else:
                return web.json_response(
                    ErrorResponse(
                        error="Invalid message format", error_code="INVALID_MESSAGE"
                    ).model_dump(),
                    status=400,
                )

        except Exception as e:
            logger.error(f"Error handling SSE message: {e}")
            return web.json_response(
                ErrorResponse(error=str(e), error_code="SSE_MESSAGE_ERROR").model_dump(), status=500
            )

    async def _handle_invoke(self, request: web.Request) -> web.Response:
        """Handle an invoke request."""
        try:
            data = await request.json()
            mcp_request = MCPRequest(**data)
            response = await self.handle_request(mcp_request)
            return web.json_response(response.model_dump())
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            return web.json_response(
                ErrorResponse(error=str(e), error_code="INVOKE_ERROR").model_dump(), status=500
            )

    async def _handle_health(self, _request: web.Request) -> web.Response:
        """Handle a health check request."""
        health_data = await self.health_check()
        status_code = 200 if health_data.status == "healthy" else 503
        return web.json_response(health_data.model_dump(), status=status_code)

    async def _handle_metrics(self, _request: web.Request) -> web.Response:
        """Handle metrics request for monitoring."""
        uptime = time.time() - self._start_time if self._start_time else 0

        metrics = {
            "server": {
                "version": __version__,
                "uptime_seconds": uptime,
                "status": "running" if self._running else "stopped",
            },
            "requests": {
                "total": self._request_count,
                "errors": self._error_count,
                "error_rate": self._error_count / max(self._request_count, 1),
            },
            "jama": {
                "connected": self.jama_client is not None,
                "url": self.config.url,
            },
            "rate_limiting": {
                "window_seconds": self.RATE_LIMIT_WINDOW,
                "max_requests": self.RATE_LIMIT_MAX_REQUESTS,
                "active_clients": len(self._rate_limit_store),
            },
        }

        return web.json_response(metrics)

    async def _handle_ready(self, _request: web.Request) -> web.Response:
        """Handle Kubernetes readiness probe."""
        if self._running and self.jama_client:
            return web.json_response({"ready": True})
        return web.json_response({"ready": False}, status=503)

    async def _handle_live(self, _request: web.Request) -> web.Response:
        """Handle Kubernetes liveness probe."""
        return web.json_response({"alive": True})
