"""Items commands."""
from __future__ import annotations

import json
from typing import Annotated, Any

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import (
    OutputFormat,
    confirm,
    console,
    format_output,
    format_single_item,
    print_error,
    print_success,
)

app = typer.Typer(name="items", help="Manage Jama items")


def _flatten_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten items by merging fields dict into top level for display."""
    result = []
    for item in items:
        flat = dict(item)  # Copy top-level fields
        # Merge fields dict (contains name, description, etc.)
        if "fields" in item:
            for key, value in item["fields"].items():
                if key not in flat:  # Don't overwrite top-level keys
                    flat[key] = value
        result.append(flat)
    return result


@app.command("list")
def list_items(
    ctx: typer.Context,
    project_id: Annotated[int, typer.Argument(help="Project ID")],
    item_type: Annotated[
        int | None,
        typer.Option("--type", "-t", help="Filter by item type ID"),
    ] = None,
    fields: Annotated[
        str | None,
        typer.Option("--fields", "-f", help="Comma-separated fields to display"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum items to return (default 50, use 0 for all)"),
    ] = 50,
) -> None:
    """List items in a project.

    By default returns first 50 items for fast response.
    Use --limit 0 to fetch all items (slower for large projects).
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        # Use max_results for server-side limiting (much faster)
        max_results = limit if limit > 0 else None
        items = client.get_items(project_id, item_type=item_type, max_results=max_results)

        # Show info about limiting
        if limit > 0 and len(items) == limit:
            console.print(f"[dim]Showing first {limit} items. Use --limit 0 for all.[/dim]")

        # Parse fields
        columns = fields.split(",") if fields else ["id", "documentKey", "name", "itemType", "status"]

        # Flatten items for display (merge fields dict into top level)
        display_items = _flatten_items(items)

        format_output(
            display_items,
            format=output_format,
            title=f"Items in Project {project_id}",
            columns=columns,
        )

    except Exception as e:
        print_error(f"Failed to list items: {e}")
        raise typer.Exit(1) from e


@app.command("get")
def get_item(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item API ID (numeric, shown in 'id' column)")],
) -> None:
    """Get details of a specific item.

    Use the numeric API ID (from 'items list' output), not the Global ID.

    Examples:
        jama items get 1241247    # Using API ID

    Tip: Find API ID with 'jama items list <project>' or in Jama URL after /items/
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        item = client.get_item(item_id)

        format_single_item(
            item,
            format=output_format,
            title=f"Item {item_id}",
        )

    except Exception as e:
        print_error(f"Failed to get item: {e}")
        raise typer.Exit(1) from e


@app.command("children")
def get_children(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Parent item API ID (numeric)")],
    fields: Annotated[
        str | None,
        typer.Option("--fields", "-f", help="Comma-separated fields to display"),
    ] = None,
) -> None:
    """Get children of an item."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        children = client.get_item_children(item_id)

        columns = fields.split(",") if fields else ["id", "documentKey", "name", "itemType"]

        # Flatten items for display
        display_children = _flatten_items(children)

        format_output(
            display_children,
            format=output_format,
            title=f"Children of Item {item_id}",
            columns=columns,
        )

    except Exception as e:
        print_error(f"Failed to get children: {e}")
        raise typer.Exit(1) from e


@app.command("create")
def create_item(
    ctx: typer.Context,
    project_id: Annotated[int, typer.Argument(help="Project ID")],
    item_type_id: Annotated[int, typer.Option("--type", "-t", help="Item type ID")],
    name: Annotated[str, typer.Option("--name", "-n", help="Item name")],
    parent_id: Annotated[
        int | None,
        typer.Option("--parent", "-p", help="Parent item ID"),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Item description"),
    ] = None,
    fields_json: Annotated[
        str | None,
        typer.Option("--fields", help="Additional fields as JSON"),
    ] = None,
) -> None:
    """Create a new item."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        # Build fields
        fields: dict[str, Any] = {"name": name}
        if description:
            fields["description"] = description

        # Merge additional fields
        if fields_json:
            try:
                additional = json.loads(fields_json)
                fields.update(additional)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON in --fields: {e}")
                raise typer.Exit(1) from e

        # Build location - py_jama_rest_client wraps this in {"parent": location}
        location: dict[str, Any] = {}
        if parent_id:
            location["item"] = parent_id

        # Create item
        new_id = client.create_item(
            project_id=project_id,
            item_type_id=item_type_id,
            child_item_type_id=item_type_id,  # Usually same as item_type_id
            location=location,
            fields=fields,
        )

        print_success(f"Created item with ID: {new_id}")

        # Show created item
        if output_format != OutputFormat.TABLE:
            item = client.get_item(new_id)
            format_single_item(item, format=output_format)

    except Exception as e:
        print_error(f"Failed to create item: {e}")
        raise typer.Exit(1) from e


@app.command("update")
def update_item(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item API ID (numeric)")],
    name: Annotated[str | None, typer.Option("--name", "-n", help="New name")] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="New description"),
    ] = None,
    fields_json: Annotated[
        str | None,
        typer.Option("--fields", help="Fields to update as JSON"),
    ] = None,
    field: Annotated[
        list[str] | None,
        typer.Option("--field", "-f", help="Field to update (key=value format)"),
    ] = None,
) -> None:
    """Update an existing item."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        # Build fields to update
        fields: dict[str, Any] = {}

        if name:
            fields["name"] = name
        if description:
            fields["description"] = description

        # Parse --field options (key=value)
        if field:
            for f in field:
                if "=" not in f:
                    print_error(f"Invalid field format: {f}. Use key=value.")
                    raise typer.Exit(1)
                key, value = f.split("=", 1)
                fields[key] = value

        # Parse JSON fields
        if fields_json:
            try:
                additional = json.loads(fields_json)
                fields.update(additional)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON in --fields: {e}")
                raise typer.Exit(1) from e

        if not fields:
            print_error("No fields to update. Use --name, --field, or --fields.")
            raise typer.Exit(1)

        # Update item
        client.update_item(item_id, fields)
        print_success(f"Updated item {item_id}")

    except Exception as e:
        print_error(f"Failed to update item: {e}")
        raise typer.Exit(1) from e


@app.command("delete")
def delete_item(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item API ID (numeric)")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
) -> None:
    """Delete an item."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        # Confirm deletion
        if not force:
            item = client.get_item(item_id)
            item_name = item.get("fields", {}).get("name", f"Item {item_id}")
            if not confirm(f"Delete '{item_name}' (ID: {item_id})?"):
                console.print("[dim]Cancelled.[/dim]")
                raise typer.Exit(0)

        # Delete item
        client.delete_item(item_id)
        print_success(f"Deleted item {item_id}")

    except Exception as e:
        print_error(f"Failed to delete item: {e}")
        raise typer.Exit(1) from e
