"""Version history commands for items."""

from __future__ import annotations

import json
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import print_error, print_info
from jama_cli.output.formatters import OutputFormat, format_output

app = typer.Typer(name="history", help="View item version history and changes")
console = Console()


def _format_date(date_str: str | None) -> str:
    """Format date string for display."""
    if not date_str:
        return ""
    # Take first 19 chars (YYYY-MM-DDTHH:MM:SS)
    return date_str[:19].replace("T", " ") if len(date_str) >= 19 else date_str


@app.command("list")
def list_versions(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item ID")],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format"),
    ] = OutputFormat.TABLE,
) -> None:
    """List all versions of an item.

    Examples:
        jama history list 12345
        jama history list 12345 --format json
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        versions = client.get_item_versions(item_id)

        if not versions:
            print_info("No version history found")
            return

        # Simplify for display
        display_data = []
        for v in versions:
            display_data.append(
                {
                    "version": v.get("version", ""),
                    "type": v.get("type", v.get("versionedItem", {}).get("type", "")),
                    "created": _format_date(
                        v.get("createdDate", v.get("versionedItem", {}).get("createdDate"))
                    ),
                    "createdBy": (
                        v.get("createdBy", {}).get("username", "")
                        if isinstance(v.get("createdBy"), dict)
                        else ""
                    ),
                    "comment": v.get("comment", "")[:50] if v.get("comment") else "",
                }
            )

        # Sort by version descending
        display_data.sort(key=lambda x: x.get("version", 0), reverse=True)

        format_output(display_data, output_format, title=f"Version History - Item {item_id}")

    except Exception as e:
        print_error(f"Failed to get version history: {e}")
        raise typer.Exit(1) from e


@app.command("get")
def get_version(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item ID")],
    version: Annotated[int, typer.Argument(help="Version number")],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format"),
    ] = OutputFormat.TABLE,
) -> None:
    """Get a specific version of an item.

    Examples:
        jama history get 12345 3
        jama history get 12345 1 --format json
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        version_data = client.get_item_version(item_id, version)
        format_output(version_data, output_format, title=f"Item {item_id} - Version {version}")

    except Exception as e:
        print_error(f"Failed to get version: {e}")
        raise typer.Exit(1) from e


@app.command("diff")
def diff_versions(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item ID")],
    version1: Annotated[int, typer.Argument(help="First version (older)")],
    version2: Annotated[int, typer.Argument(help="Second version (newer)")],
    fields_only: Annotated[
        bool,
        typer.Option("--fields-only", help="Only compare fields"),
    ] = True,
) -> None:
    """Compare two versions of an item and show differences.

    Examples:
        jama history diff 12345 1 3
        jama history diff 12345 1 3 --no-fields-only
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        print_info(f"Comparing item {item_id}: version {version1} → version {version2}")

        v1_data = client.get_item_version(item_id, version1)
        v2_data = client.get_item_version(item_id, version2)

        # Extract the versioned item data
        v1_item = v1_data.get("versionedItem", v1_data)
        v2_item = v2_data.get("versionedItem", v2_data)

        if fields_only:
            v1_fields = v1_item.get("fields", {})
            v2_fields = v2_item.get("fields", {})
        else:
            v1_fields = v1_item
            v2_fields = v2_item

        # Find differences
        all_keys = set(v1_fields.keys()) | set(v2_fields.keys())

        diff_data = []
        for key in sorted(all_keys):
            v1_val = v1_fields.get(key)
            v2_val = v2_fields.get(key)

            if v1_val != v2_val:
                diff_data.append(
                    {
                        "field": key,
                        "old_value": _format_value(v1_val),
                        "new_value": _format_value(v2_val),
                        "change": _get_change_type(v1_val, v2_val),
                    }
                )

        if not diff_data:
            print_info("No differences found between versions")
            return

        # Display as table
        table = Table(title=f"Version Diff: {version1} → {version2}")
        table.add_column("Field", style="cyan")
        table.add_column("Change", style="bold")
        table.add_column("Old Value")
        table.add_column("New Value")

        for row in diff_data:
            change = row["change"]
            if change == "added":
                style = "green"
            elif change == "removed":
                style = "red"
            else:
                style = "yellow"

            table.add_row(
                row["field"],
                f"[{style}]{change}[/{style}]",
                _truncate(row["old_value"], 40),
                _truncate(row["new_value"], 40),
            )

        console.print(table)
        console.print(f"\n[dim]{len(diff_data)} field(s) changed[/dim]")

    except Exception as e:
        print_error(f"Version diff failed: {e}")
        raise typer.Exit(1) from e


def _format_value(value: Any) -> str:
    """Format a value for display."""
    if value is None:
        return "(none)"
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    if isinstance(value, list):
        return json.dumps(value, default=str)
    return str(value)


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _get_change_type(old_val: Any, new_val: Any) -> str:
    """Determine the type of change."""
    if old_val is None:
        return "added"
    if new_val is None:
        return "removed"
    return "modified"
