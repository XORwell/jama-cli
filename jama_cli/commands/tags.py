"""Tags commands."""
from __future__ import annotations

from typing import Annotated

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import OutputFormat, format_output, print_error

app = typer.Typer(name="tags", help="View tags and tagged items")


@app.command("list")
def list_tags(
    ctx: typer.Context,
    project_id: Annotated[int, typer.Argument(help="Project ID")],
) -> None:
    """List all tags in a project."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        tags = client.get_tags(project_id)

        format_output(
            tags,
            format=output_format,
            title=f"Tags in Project {project_id}",
            columns=["id", "name"],
        )

    except Exception as e:
        print_error(f"Failed to list tags: {e}")
        raise typer.Exit(1) from e


@app.command("items")
def list_tagged_items(
    ctx: typer.Context,
    tag_id: Annotated[int, typer.Argument(help="Tag ID")],
    fields: Annotated[
        str | None,
        typer.Option("--fields", "-f", help="Comma-separated fields to display"),
    ] = None,
) -> None:
    """List items with a specific tag."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        items = client.get_tagged_items(tag_id)

        columns = fields.split(",") if fields else ["id", "documentKey", "name", "itemType"]

        format_output(
            items,
            format=output_format,
            title=f"Items with Tag {tag_id}",
            columns=columns,
        )

    except Exception as e:
        print_error(f"Failed to get tagged items: {e}")
        raise typer.Exit(1) from e
