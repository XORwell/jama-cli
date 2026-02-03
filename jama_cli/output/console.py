"""Console output utilities using Rich."""
from __future__ import annotations

import sys

from rich.console import Console

# Main console for stdout
console = Console()

# Error console for stderr
error_console = Console(stderr=True)


def print_error(message: str, details: str | None = None) -> None:
    """Print an error message to stderr."""
    error_console.print(f"[bold red]Error:[/bold red] {message}")
    if details:
        error_console.print(f"[dim]{details}[/dim]")


def print_warning(message: str) -> None:
    """Print a warning message to stderr."""
    error_console.print(f"[bold yellow]Warning:[/bold yellow] {message}")


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[bold green]Success:[/bold green] {message}")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[bold blue]Info:[/bold blue] {message}")


def confirm(message: str, default: bool = False) -> bool:
    """Ask for confirmation."""
    suffix = " [Y/n]" if default else " [y/N]"
    response = console.input(f"{message}{suffix} ").strip().lower()

    if not response:
        return default
    return response in ("y", "yes")


def is_interactive() -> bool:
    """Check if running in an interactive terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()
