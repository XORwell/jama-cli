"""Users commands."""

from __future__ import annotations

from typing import Annotated

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import OutputFormat, format_output, format_single_item, print_error

app = typer.Typer(name="users", help="View users and current user info")


@app.command("list")
def list_users(
    ctx: typer.Context,
    fields: Annotated[
        str | None,
        typer.Option("--fields", "-f", help="Comma-separated fields to display"),
    ] = None,
) -> None:
    """List all users."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = (
        ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE
    )

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        users = client.get_users()

        columns = (
            fields.split(",")
            if fields
            else ["id", "username", "firstName", "lastName", "email", "active"]
        )

        format_output(
            users,
            format=output_format,
            title="Users",
            columns=columns,
        )

    except Exception as e:
        print_error(f"Failed to list users: {e}")
        raise typer.Exit(1) from e


@app.command("me")
def current_user(
    ctx: typer.Context,
) -> None:
    """Get current user information."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = (
        ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE
    )

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        user = client.get_current_user()

        format_single_item(
            user,
            format=output_format,
            title="Current User",
        )

    except Exception as e:
        print_error(f"Failed to get current user: {e}")
        raise typer.Exit(1) from e
