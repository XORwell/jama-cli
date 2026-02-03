"""Relationships commands."""
from __future__ import annotations

from typing import Annotated

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import (
    OutputFormat,
    confirm,
    console,
    format_output,
    print_error,
    print_success,
)

app = typer.Typer(name="relationships", help="Manage item relationships")


@app.command("list")
def list_relationships(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item ID")],
    direction: Annotated[
        str,
        typer.Option("--direction", "-d", help="Direction: up, down, or both"),
    ] = "both",
) -> None:
    """List relationships for an item."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    if direction not in ("up", "down", "both"):
        print_error("Direction must be 'up', 'down', or 'both'")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        all_relationships = []

        if direction in ("up", "both"):
            upstream = client.get_item_upstream_relationships(item_id)
            for rel in upstream:
                rel["direction"] = "upstream"
            all_relationships.extend(upstream)

        if direction in ("down", "both"):
            downstream = client.get_item_downstream_relationships(item_id)
            for rel in downstream:
                rel["direction"] = "downstream"
            all_relationships.extend(downstream)

        format_output(
            all_relationships,
            format=output_format,
            title=f"Relationships for Item {item_id}",
            columns=["id", "fromItem", "toItem", "relationshipType", "direction"],
        )

    except Exception as e:
        print_error(f"Failed to list relationships: {e}")
        raise typer.Exit(1) from e


@app.command("upstream")
def upstream_items(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item ID")],
    fields: Annotated[
        str | None,
        typer.Option("--fields", "-f", help="Comma-separated fields to display"),
    ] = None,
) -> None:
    """Get items upstream (traced from) of this item."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        items = client.get_item_upstream_related(item_id)

        columns = fields.split(",") if fields else ["id", "documentKey", "name", "itemType"]

        format_output(
            items,
            format=output_format,
            title=f"Upstream Items for {item_id}",
            columns=columns,
        )

    except Exception as e:
        print_error(f"Failed to get upstream items: {e}")
        raise typer.Exit(1) from e


@app.command("downstream")
def downstream_items(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item ID")],
    fields: Annotated[
        str | None,
        typer.Option("--fields", "-f", help="Comma-separated fields to display"),
    ] = None,
) -> None:
    """Get items downstream (traced to) of this item."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        items = client.get_item_downstream_related(item_id)

        columns = fields.split(",") if fields else ["id", "documentKey", "name", "itemType"]

        format_output(
            items,
            format=output_format,
            title=f"Downstream Items for {item_id}",
            columns=columns,
        )

    except Exception as e:
        print_error(f"Failed to get downstream items: {e}")
        raise typer.Exit(1) from e


@app.command("create")
def create_relationship(
    ctx: typer.Context,
    from_item: Annotated[int, typer.Option("--from", "-f", help="Source item ID")],
    to_item: Annotated[int, typer.Option("--to", "-t", help="Target item ID")],
    relationship_type: Annotated[
        int | None,
        typer.Option("--type", help="Relationship type ID"),
    ] = None,
) -> None:
    """Create a relationship between two items."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        rel_id = client.create_relationship(from_item, to_item, relationship_type)
        print_success(f"Created relationship {rel_id}: {from_item} -> {to_item}")

    except Exception as e:
        print_error(f"Failed to create relationship: {e}")
        raise typer.Exit(1) from e


@app.command("delete")
def delete_relationship(
    ctx: typer.Context,
    relationship_id: Annotated[int, typer.Argument(help="Relationship ID")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
) -> None:
    """Delete a relationship."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        if not force:
            rel = client.get_relationship(relationship_id)
            if not confirm(
                f"Delete relationship {relationship_id} "
                f"({rel.get('fromItem')} -> {rel.get('toItem')})?"
            ):
                console.print("[dim]Cancelled.[/dim]")
                raise typer.Exit(0)

        client.delete_relationship(relationship_id)
        print_success(f"Deleted relationship {relationship_id}")

    except Exception as e:
        print_error(f"Failed to delete relationship: {e}")
        raise typer.Exit(1) from e
