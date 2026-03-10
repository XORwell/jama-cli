"""Test management commands."""

from __future__ import annotations

from typing import Annotated

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import OutputFormat, format_output, format_single_item, print_error

app = typer.Typer(name="tests", help="View test cycles and runs")


@app.command("cycle")
def get_test_cycle(
    ctx: typer.Context,
    test_cycle_id: Annotated[int, typer.Argument(help="Test cycle ID")],
) -> None:
    """Get details of a specific test cycle."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = (
        ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE
    )

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        cycle = client.get_test_cycle(test_cycle_id)

        format_single_item(
            cycle,
            format=output_format,
            title=f"Test Cycle {test_cycle_id}",
        )

    except Exception as e:
        print_error(f"Failed to get test cycle: {e}")
        raise typer.Exit(1) from e


@app.command("runs")
def list_test_runs(
    ctx: typer.Context,
    test_cycle_id: Annotated[int, typer.Argument(help="Test cycle ID")],
) -> None:
    """List test runs for a test cycle."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = (
        ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE
    )

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        runs = client.get_test_runs(test_cycle_id)

        format_output(
            runs,
            format=output_format,
            title=f"Test Runs for Cycle {test_cycle_id}",
            columns=["id", "name", "testCase", "status", "assignedTo"],
        )

    except Exception as e:
        print_error(f"Failed to list test runs: {e}")
        raise typer.Exit(1) from e
