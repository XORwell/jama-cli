"""Item types commands."""
from __future__ import annotations

from typing import Annotated

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import OutputFormat, format_output, format_single_item, print_error

app = typer.Typer(name="types", help="View item types and their fields")


@app.command("list")
def list_types(
    ctx: typer.Context,
    fields: Annotated[
        str | None,
        typer.Option("--fields", "-f", help="Comma-separated fields to display"),
    ] = None,
) -> None:
    """List all item types."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        types = client.get_item_types()

        columns = fields.split(",") if fields else ["id", "typeKey", "display", "category"]

        format_output(
            types,
            format=output_format,
            title="Item Types",
            columns=columns,
        )

    except Exception as e:
        print_error(f"Failed to list item types: {e}")
        raise typer.Exit(1) from e


@app.command("get")
def get_type(
    ctx: typer.Context,
    type_id: Annotated[int, typer.Argument(help="Item type ID")],
) -> None:
    """Get details of a specific item type."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        item_type = client.get_item_type(type_id)

        format_single_item(
            item_type,
            format=output_format,
            title=f"Item Type {type_id}",
        )

    except Exception as e:
        print_error(f"Failed to get item type: {e}")
        raise typer.Exit(1) from e
