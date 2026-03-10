"""MCP server commands with daemon support."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

import typer
from loguru import logger

from jama_cli import __version__
from jama_cli.config import get_profile_or_env
from jama_cli.output import console, print_error, print_success

app = typer.Typer(name="serve", help="Start MCP server for AI assistants")

# Default locations for daemon files
RUNTIME_DIR = Path.home() / ".jama"
PID_FILE = RUNTIME_DIR / "server.pid"
LOG_FILE = RUNTIME_DIR / "server.log"


def _get_pid() -> int | None:
    """Get the PID of the running server, or None if not running."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        # Check if process is actually running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        # PID file exists but process is not running
        PID_FILE.unlink(missing_ok=True)
        return None


def _write_pid(pid: int) -> None:
    """Write the PID to the PID file."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def _remove_pid() -> None:
    """Remove the PID file."""
    PID_FILE.unlink(missing_ok=True)


@app.callback(invoke_without_command=True)
def serve(
    ctx: typer.Context,
    stdio: Annotated[
        bool,
        typer.Option("--stdio", help="Run as stdio MCP server (for Claude, Cline)"),
    ] = False,
    host: Annotated[
        str,
        typer.Option("--host", help="Host to bind HTTP server"),
    ] = "localhost",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port for HTTP server"),
    ] = 8000,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", envvar="MCP_API_KEY", help="API key for server auth"),
    ] = None,
    daemon: Annotated[
        bool,
        typer.Option("--daemon", "-d", help="Run server in background"),
    ] = False,
) -> None:
    """Start the MCP server.

    By default, starts an HTTP server in the foreground.

    Examples:
        jama serve                    # HTTP server on localhost:8000
        jama serve --stdio            # stdio MCP server for Claude Desktop
        jama serve --port 9000        # HTTP server on custom port
        jama serve --daemon           # Run in background
        jama serve stop               # Stop background server
        jama serve status             # Check if server is running
    """
    if ctx.invoked_subcommand is not None:
        return

    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    if not profile.has_valid_credentials():
        print_error("Profile credentials are incomplete. Check 'jama config show'.")
        raise typer.Exit(1)

    # Check if already running
    if daemon:
        existing_pid = _get_pid()
        if existing_pid:
            print_error(f"Server already running (PID: {existing_pid})")
            console.print("Use 'jama serve stop' to stop it first.")
            raise typer.Exit(1)

    # Convert profile to legacy JamaConfig for existing server code
    from jama_mcp_server.models import JamaConfig

    config = JamaConfig(
        url=profile.url,
        username=profile.username or "",
        password=profile.password or "",
        api_key=profile.api_key or "",
        oauth=profile.auth_type == "oauth",
        client_id=profile.client_id or "",
        client_secret=profile.client_secret or "",
    )

    if stdio:
        if daemon:
            print_error("Cannot run stdio server in daemon mode")
            raise typer.Exit(1)
        _run_stdio_server(config)
    elif daemon:
        _start_daemon(host, port, api_key, ctx.obj.get("profile") if ctx.obj else None)
    else:
        _run_http_server(config, host, port, api_key)


@app.command("start")
def start_daemon(
    ctx: typer.Context,
    host: Annotated[
        str,
        typer.Option("--host", help="Host to bind HTTP server"),
    ] = "localhost",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port for HTTP server"),
    ] = 8000,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", envvar="MCP_API_KEY", help="API key for server auth"),
    ] = None,
) -> None:
    """Start the server in background (daemon mode)."""
    existing_pid = _get_pid()
    if existing_pid:
        print_error(f"Server already running (PID: {existing_pid})")
        console.print("Use 'jama serve stop' to stop it first.")
        raise typer.Exit(1)

    profile_name = ctx.obj.get("profile") if ctx.obj else None
    _start_daemon(host, port, api_key, profile_name)


def _start_daemon(
    host: str,
    port: int,
    api_key: str | None,
    profile_name: str | None,
) -> None:
    """Start the server as a background daemon."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    # Build command to run
    cmd = [sys.executable, "-m", "jama_cli.main", "serve", "--host", host, "--port", str(port)]

    if api_key:
        cmd.extend(["--api-key", api_key])
    if profile_name:
        cmd.extend(["--profile", profile_name])

    # Write startup info to log file
    with open(LOG_FILE, "a") as log_init:
        log_init.write(f"\n{'='*60}\n")
        log_init.write(f"Starting server at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_init.write(f"Command: {' '.join(cmd)}\n")
        log_init.write(f"{'='*60}\n")

    # Open log file for subprocess (needs to stay open)
    log_handle = open(LOG_FILE, "a")  # noqa: SIM115

    # Start subprocess
    process = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=log_handle,
        start_new_session=True,  # Detach from terminal
    )

    # Wait a moment to check if it started successfully
    time.sleep(1)

    if process.poll() is not None:
        print_error("Server failed to start. Check logs with 'jama serve logs'")
        raise typer.Exit(1)

    # Write PID file
    _write_pid(process.pid)

    print_success(f"Server started in background (PID: {process.pid})")
    console.print(f"  URL: http://{host}:{port}")
    console.print(f"  Logs: {LOG_FILE}")
    console.print("\nCommands:")
    console.print("  jama serve status  - Check status")
    console.print("  jama serve stop    - Stop server")
    console.print("  jama serve logs    - View logs")


@app.command("stop")
def stop_daemon(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Force kill (SIGKILL instead of SIGTERM)"),
    ] = False,
) -> None:
    """Stop the background server."""
    pid = _get_pid()

    if not pid:
        console.print("[dim]No server running[/dim]")
        return

    try:
        if force:
            os.kill(pid, signal.SIGKILL)
            print_success(f"Server killed (PID: {pid})")
        else:
            os.kill(pid, signal.SIGTERM)
            # Wait for graceful shutdown
            for _ in range(10):
                time.sleep(0.5)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
            else:
                # Still running, force kill
                console.print("[yellow]Server not responding, force killing...[/yellow]")
                os.kill(pid, signal.SIGKILL)

            print_success(f"Server stopped (PID: {pid})")

    except ProcessLookupError:
        console.print("[dim]Server already stopped[/dim]")
    except PermissionError as e:
        print_error(f"Permission denied to stop server (PID: {pid})")
        raise typer.Exit(1) from e
    finally:
        _remove_pid()


@app.command("status")
def server_status() -> None:
    """Check if the server is running."""
    pid = _get_pid()

    if pid:
        console.print(f"[green]Server is running[/green] (PID: {pid})")

        # Try to get health info
        try:
            import urllib.request

            with urllib.request.urlopen("http://localhost:8000/health", timeout=2) as resp:
                if resp.status == 200:
                    import json

                    data = json.loads(resp.read())
                    console.print(f"  Status: {data.get('status', 'unknown')}")
                    console.print(f"  Jama URL: {data.get('jama_url', 'unknown')}")
                    if data.get("uptime_seconds"):
                        uptime = int(data["uptime_seconds"])
                        console.print(f"  Uptime: {uptime // 60}m {uptime % 60}s")
        except Exception:
            console.print("  [dim]Health check unavailable[/dim]")
    else:
        console.print("[dim]Server is not running[/dim]")


@app.command("logs")
def view_logs(
    follow: Annotated[
        bool,
        typer.Option("--follow", "-f", help="Follow log output (like tail -f)"),
    ] = False,
    lines: Annotated[
        int,
        typer.Option("--lines", "-n", help="Number of lines to show"),
    ] = 50,
) -> None:
    """View server logs."""
    if not LOG_FILE.exists():
        console.print("[dim]No logs yet[/dim]")
        return

    if follow:
        # Use tail -f equivalent
        console.print(f"[dim]Following {LOG_FILE} (Ctrl+C to stop)[/dim]\n")
        try:
            process = subprocess.Popen(
                ["tail", "-f", str(LOG_FILE)],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            process.wait()
        except KeyboardInterrupt:
            process.terminate()
    else:
        # Show last N lines
        content = LOG_FILE.read_text()
        log_lines = content.splitlines()
        for line in log_lines[-lines:]:
            console.print(line)


@app.command("restart")
def restart_daemon(
    ctx: typer.Context,
    host: Annotated[
        str,
        typer.Option("--host", help="Host to bind HTTP server"),
    ] = "localhost",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port for HTTP server"),
    ] = 8000,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", envvar="MCP_API_KEY", help="API key for server auth"),
    ] = None,
) -> None:
    """Restart the background server."""
    pid = _get_pid()
    if pid:
        console.print("Stopping server...")
        stop_daemon(force=False)
        time.sleep(1)

    console.print("Starting server...")
    profile_name = ctx.obj.get("profile") if ctx.obj else None
    _start_daemon(host, port, api_key, profile_name)


def _run_stdio_server(config: Any) -> None:
    """Run the stdio MCP server."""
    from jama_mcp_server.core.stdio_server import JamaStdioMCPServer

    logger.info(f"Starting Jama MCP server v{__version__} in stdio mode")

    async def start_stdio() -> None:
        try:
            server = JamaStdioMCPServer(config=config)
            await server.run()
        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down...")
        except Exception as e:
            logger.error(f"Server error: {e}")
            raise typer.Exit(1) from e

    try:
        asyncio.run(start_stdio())
    except KeyboardInterrupt:
        logger.info("Server stopped")


def _run_http_server(config: Any, host: str, port: int, api_key: str | None) -> None:
    """Run the HTTP MCP server in foreground."""
    from jama_mcp_server.core.server import JamaMCPServer

    logger.info(f"Starting Jama MCP server v{__version__} on {host}:{port}")
    if api_key:
        logger.info("API key authentication enabled")

    async def start_http() -> int:
        server = JamaMCPServer(
            config=config,
            host=host,
            port=port,
            api_key=api_key,
        )

        try:
            await server.start()

            # Setup signal handlers
            shutdown_event = asyncio.Event()

            def signal_handler() -> None:
                logger.info("Received shutdown signal")
                shutdown_event.set()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                with suppress(NotImplementedError):
                    loop.add_signal_handler(sig, signal_handler)

            # Wait for shutdown
            await shutdown_event.wait()
            return 0

        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down...")
            return 0
        except Exception as e:
            logger.error(f"Server error: {e}")
            return 1
        finally:
            await server.stop()

    try:
        exit_code = asyncio.run(start_http())
        raise typer.Exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Server stopped")
