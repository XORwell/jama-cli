"""Search commands for finding items across Jama."""
from __future__ import annotations

import re
from typing import Annotated, Any

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import OutputFormat, console, format_output, print_error

app = typer.Typer(name="search", help="Search for items in Jama")


@app.command("items")
def search_items(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Search query (text or regex pattern)")],
    project_id: Annotated[
        int | None,
        typer.Option("--project", "-p", help="Limit search to specific project"),
    ] = None,
    item_type: Annotated[
        int | None,
        typer.Option("--type", "-t", help="Filter by item type ID"),
    ] = None,
    field: Annotated[
        str,
        typer.Option("--field", "-f", help="Field to search in (default: name)"),
    ] = "name",
    regex: Annotated[
        bool,
        typer.Option("--regex", "-r", help="Treat query as regex pattern"),
    ] = False,
    case_sensitive: Annotated[
        bool,
        typer.Option("--case-sensitive", "-c", help="Case-sensitive search"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum results to return"),
    ] = 50,
    fields_display: Annotated[
        str | None,
        typer.Option("--fields", help="Comma-separated fields to display"),
    ] = None,
) -> None:
    """Search for items matching a query.

    Searches item fields for matching text. By default searches the 'name' field.

    Examples:
        jama search items "login"                     # Search all projects
        jama search items "login" --project 123      # Search in project 123 only
        jama search items "REQ-" --field documentKey # Search by document key
        jama search items "^REQ-\\d+" --regex        # Search with regex
        jama search items "test" --type 45           # Search specific item type
        jama search items "error" -f description     # Search in description field
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        # Get items to search
        console.print(f"[dim]Searching for '{query}' in {field}...[/dim]")

        if project_id:
            items = client.get_items(project_id, item_type=item_type)
        else:
            # Search across all projects
            projects = client.get_projects()
            items = []
            for proj in projects:
                proj_id = proj.get("id")
                if proj_id:
                    try:
                        proj_items = client.get_items(proj_id, item_type=item_type)
                        items.extend(proj_items)
                    except Exception:
                        # Skip projects we can't access
                        pass

        # Filter items by query
        matches = _search_items(
            items=items,
            query=query,
            field=field,
            regex=regex,
            case_sensitive=case_sensitive,
        )

        # Apply limit
        if len(matches) > limit:
            matches = matches[:limit]
            console.print(f"[dim]Showing first {limit} results. Use --limit to change.[/dim]")

        if not matches:
            console.print(f"[yellow]No items found matching '{query}'[/yellow]")
            return

        console.print(f"[green]Found {len(matches)} matching items[/green]\n")

        # Determine display columns
        columns = ["id", "documentKey", "name", "itemType", "project"]
        if fields_display:
            columns = fields_display.split(",")

        # Flatten items for display
        display_items = []
        for item in matches:
            display_item = {
                "id": item.get("id"),
                "documentKey": item.get("documentKey"),
                "name": item.get("fields", {}).get("name", ""),
                "itemType": item.get("itemType"),
                "project": item.get("project"),
            }
            # Include the searched field if it's in fields
            if field != "name":
                display_item[field] = _get_nested_value(item, field)

            # Add any extra requested fields
            if fields_display:
                for col in columns:
                    if col not in display_item:
                        display_item[col] = _get_nested_value(item, col)

            display_items.append(display_item)

        format_output(
            display_items,
            format=output_format,
            title=f"Search Results for '{query}'",
            columns=columns,
        )

    except Exception as e:
        print_error(f"Search failed: {e}")
        raise typer.Exit(1) from e


def _search_items(
    items: list[dict[str, Any]],
    query: str,
    field: str,
    regex: bool = False,
    case_sensitive: bool = False,
) -> list[dict[str, Any]]:
    """Filter items by search query.

    Args:
        items: List of items to search
        query: Search query
        field: Field to search in
        regex: Whether to treat query as regex
        case_sensitive: Whether search is case-sensitive

    Returns:
        List of matching items
    """
    matches = []

    # Compile regex pattern
    if regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}") from e
    else:
        pattern = None
        if not case_sensitive:
            query = query.lower()

    for item in items:
        # Get field value
        value = _get_nested_value(item, field)
        if value is None:
            continue

        value_str = str(value)
        if not case_sensitive and not regex:
            value_str = value_str.lower()

        # Check for match
        if regex and pattern:
            if pattern.search(value_str):
                matches.append(item)
        elif query in value_str:
            matches.append(item)

    return matches


def _get_nested_value(item: dict[str, Any], field: str) -> Any:
    """Get a potentially nested field value from an item.

    Supports:
    - Top-level fields: "id", "documentKey"
    - Nested fields: "fields.name", "location.parent"
    - Fields dict shorthand: "name" -> fields.name
    """
    # Direct top-level access
    if field in item:
        return item[field]

    # Check in fields dict (common case)
    if "fields" in item and field in item["fields"]:
        return item["fields"][field]

    # Handle dot notation
    if "." in field:
        parts = field.split(".")
        value = item
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return value

    return None


@app.command("fields")
def list_searchable_fields(
    ctx: typer.Context,
    project_id: Annotated[int, typer.Argument(help="Project ID to inspect")],
    item_type: Annotated[
        int | None,
        typer.Option("--type", "-t", help="Item type ID to show fields for"),
    ] = None,
) -> None:
    """List searchable fields for items in a project.

    Shows the available fields you can search with --field.

    Example:
        jama search fields 123           # Show fields for project 123
        jama search fields 123 --type 45 # Show fields for specific item type
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        # Get a sample item to show available fields
        items = client.get_items(project_id, item_type=item_type)

        if not items:
            console.print("[yellow]No items found in project[/yellow]")
            return

        # Collect all unique fields
        top_level_fields = set()
        nested_fields = set()

        for item in items[:10]:  # Sample first 10 items
            top_level_fields.update(item.keys())
            if "fields" in item:
                nested_fields.update(item["fields"].keys())

        console.print("\n[bold]Searchable Fields[/bold]\n")

        console.print("[cyan]Top-level fields:[/cyan]")
        for field in sorted(top_level_fields):
            console.print(f"  {field}")

        console.print("\n[cyan]Item fields (use directly or with 'fields.' prefix):[/cyan]")
        for field in sorted(nested_fields):
            console.print(f"  {field}")

        console.print("\n[dim]Example: jama search 'query' --field description[/dim]")

    except Exception as e:
        print_error(f"Failed to list fields: {e}")
        raise typer.Exit(1) from e
