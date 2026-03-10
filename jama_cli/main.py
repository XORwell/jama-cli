"""Main CLI entry point."""

from __future__ import annotations

import sys
from typing import Annotated

import typer
from loguru import logger

from jama_cli import __version__
from jama_cli.commands import (
    attachments,
    baseline,
    config_cmd,
    diff,
    history,
    items,
    migrate,
    picklists,
    projects,
    relationships,
    search,
    serve,
    tags,
    tests,
    trace,
    types,
    users,
)
from jama_cli.output import OutputFormat

# Create main app
app = typer.Typer(
    name="jama",
    help="Jama CLI - Command-line interface for Jama requirements management",
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
)

# Add subcommands
app.add_typer(projects.app, name="projects")
app.add_typer(items.app, name="items")
app.add_typer(relationships.app, name="relationships")
app.add_typer(types.app, name="types")
app.add_typer(config_cmd.app, name="config")
app.add_typer(serve.app, name="serve")
app.add_typer(migrate.app, name="migrate")
app.add_typer(search.app, name="search")
app.add_typer(diff.app, name="diff")
app.add_typer(attachments.app, name="attachments")
app.add_typer(picklists.app, name="picklists")
app.add_typer(tags.app, name="tags")
app.add_typer(tests.app, name="tests")
app.add_typer(users.app, name="users")
app.add_typer(trace.app, name="trace")
app.add_typer(baseline.app, name="baseline")
app.add_typer(history.app, name="history")


def version_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        typer.echo(f"Jama CLI v{__version__}")
        raise typer.Exit()


def configure_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level."""
    logger.remove()

    if verbosity == 0:
        # Only errors
        level = "ERROR"
    elif verbosity == 1:
        level = "WARNING"
    elif verbosity == 2:
        level = "INFO"
    else:
        level = "DEBUG"

    logger.add(
        sys.stderr,
        level=level,
        format="<dim>{time:HH:mm:ss}</dim> | <level>{level: <8}</level> | {message}",
        colorize=True,
    )


@app.callback()
def main(
    ctx: typer.Context,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Profile name from config",
            envvar="JAMA_PROFILE",
        ),
    ] = None,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            help="Output format",
            case_sensitive=False,
        ),
    ] = OutputFormat.TABLE,
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="Increase verbosity (-v, -vv, -vvv)",
        ),
    ] = 0,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress non-error output"),
    ] = False,
    version: Annotated[  # noqa: ARG001
        bool | None,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show version",
        ),
    ] = None,
) -> None:
    """Jama CLI - Command-line interface for Jama requirements management.

    Configure profiles with 'jama config init' before use.

    Examples:

        jama projects list                  # List all projects
        jama items list 123                 # List items in project 123
        jama items get 456                  # Get item details
        jama serve --stdio                  # Start MCP server for Claude
    """
    # Configure logging
    if quiet:
        configure_logging(0)
    else:
        configure_logging(verbose)

    # Store context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
    ctx.obj["output"] = output
    ctx.obj["verbose"] = verbose


def run() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    run()
