"""Pick lists commands."""
from __future__ import annotations

from typing import Annotated

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import OutputFormat, format_output, format_single_item, print_error

app = typer.Typer(name="picklists", help="View pick lists and their options")


@app.command("list")
def list_pick_lists(
    ctx: typer.Context,
) -> None:
    """List all pick lists."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        pick_lists = client.get_pick_lists()

        format_output(
            pick_lists,
            format=output_format,
            title="Pick Lists",
            columns=["id", "name", "description"],
        )

    except Exception as e:
        print_error(f"Failed to list pick lists: {e}")
        raise typer.Exit(1) from e


@app.command("get")
def get_pick_list(
    ctx: typer.Context,
    pick_list_id: Annotated[int, typer.Argument(help="Pick list ID")],
) -> None:
    """Get details of a specific pick list."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        pick_list = client.get_pick_list(pick_list_id)

        format_single_item(
            pick_list,
            format=output_format,
            title=f"Pick List {pick_list_id}",
        )

    except Exception as e:
        print_error(f"Failed to get pick list: {e}")
        raise typer.Exit(1) from e


@app.command("options")
def list_options(
    ctx: typer.Context,
    pick_list_id: Annotated[int, typer.Argument(help="Pick list ID")],
) -> None:
    """List options for a pick list."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        options = client.get_pick_list_options(pick_list_id)

        format_output(
            options,
            format=output_format,
            title=f"Options for Pick List {pick_list_id}",
            columns=["id", "name", "value", "default", "active"],
        )

    except Exception as e:
        print_error(f"Failed to get pick list options: {e}")
        raise typer.Exit(1) from e
