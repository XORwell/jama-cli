"""Traceability commands for requirements coverage analysis."""
from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.tree import Tree

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import print_error, print_info
from jama_cli.output.formatters import OutputFormat, format_output

app = typer.Typer(name="trace", help="Traceability analysis and coverage reports")
console = Console()


def _get_item_name(item: dict[str, Any]) -> str:
    """Get display name for an item."""
    fields = item.get("fields", {})
    name = fields.get("name", item.get("name", ""))
    doc_key = item.get("documentKey", "")
    if doc_key:
        return f"{doc_key}: {name}"
    return name or f"Item {item.get('id')}"


def _get_item_type_name(item: dict[str, Any], item_types: dict[int, str]) -> str:
    """Get item type name."""
    type_id = item.get("itemType")
    return item_types.get(type_id, f"Type {type_id}")


@app.command("matrix")
def trace_matrix(
    ctx: typer.Context,
    project_id: Annotated[int, typer.Argument(help="Project ID to analyze")],
    source_type: Annotated[
        int | None,
        typer.Option("--source", "-s", help="Source item type ID (e.g., requirements)"),
    ] = None,
    target_type: Annotated[
        int | None,
        typer.Option("--target", "-t", help="Target item type ID (e.g., test cases)"),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format"),
    ] = OutputFormat.TABLE,
    show_untraced: Annotated[
        bool,
        typer.Option("--untraced", "-u", help="Show only items without traces"),
    ] = False,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", "-r", help="Bypass cache and fetch fresh data"),
    ] = False,
) -> None:
    """Generate a traceability matrix showing relationships between items.

    Shows which source items (e.g., requirements) trace to which target items
    (e.g., test cases), and identifies gaps in coverage.

    Uses bulk fetching and caching for fast performance on large projects.
    Use --refresh to bypass cache if data may have changed.

    Examples:
        jama trace matrix 1172                          # All relationships
        jama trace matrix 1172 --source 33 --target 45  # Specific types
        jama trace matrix 1172 --untraced               # Show gaps only
        jama trace matrix 1172 --refresh                # Force fresh data
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        use_cache = not refresh

        if refresh:
            console.print("[dim]Cache bypassed - fetching fresh data...[/dim]")

        # Use optimized bulk fetching (2 API calls instead of N+1)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task1 = progress.add_task(f"Fetching items from project {project_id}...", total=None)
            items = client.get_items_bulk(project_id, use_cache=use_cache)
            progress.update(task1, completed=True, description=f"Fetched {len(items)} items")

            task2 = progress.add_task("Fetching relationships (bulk)...", total=None)
            relationship_map = client.build_relationship_map(project_id, use_cache=use_cache)
            progress.update(task2, completed=True, description="Built relationship map")

        if not items:
            print_error("No items found in project")
            raise typer.Exit(1)

        console.print(f"  [dim]Analyzing {len(items)} items with {len(relationship_map)} relationship entries[/dim]")

        # Build item lookup
        item_map: dict[int, dict[str, Any]] = {item["id"]: item for item in items}

        # Get item types for display
        item_types_list = client.get_item_types()
        item_types: dict[int, str] = {t["id"]: t.get("display", t.get("name", "")) for t in item_types_list}

        # Filter by type if specified
        source_items = items
        if source_type:
            source_items = [i for i in items if i.get("itemType") == source_type]

        # Build traceability data using the pre-built map (no additional API calls!)
        trace_data: list[dict[str, Any]] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Analyzing relationships...", total=len(source_items))

            for item in source_items:
                item_id = item["id"]

                # Get downstream from pre-built map (instant lookup, no API call!)
                item_rels = relationship_map.get(item_id, {"downstream": []})
                downstream_ids = [rel.get("toItem") for rel in item_rels["downstream"]]

                # Build downstream items from our item_map
                downstream = [item_map[tid] for tid in downstream_ids if tid in item_map]

                # Filter by target type if specified
                if target_type:
                    downstream = [d for d in downstream if d.get("itemType") == target_type]

                # Skip if we only want untraced and this has traces
                if show_untraced and downstream:
                    progress.advance(task)
                    continue

                if downstream:
                    for target in downstream:
                        trace_data.append({
                            "source_id": item_id,
                            "source_key": item.get("documentKey", ""),
                            "source_name": _get_item_name(item),
                            "source_type": _get_item_type_name(item, item_types),
                            "target_id": target.get("id"),
                            "target_key": target.get("documentKey", ""),
                            "target_name": _get_item_name(target),
                            "target_type": _get_item_type_name(target, item_types),
                        })
                else:
                    # No downstream relationships - untraced item
                    trace_data.append({
                        "source_id": item_id,
                        "source_key": item.get("documentKey", ""),
                        "source_name": _get_item_name(item),
                        "source_type": _get_item_type_name(item, item_types),
                        "target_id": None,
                        "target_key": "",
                        "target_name": "(no coverage)",
                        "target_type": "",
                    })

                progress.advance(task)

        if not trace_data:
            print_info("No traceability data found")
            return

        # Calculate coverage stats
        total_sources = len(source_items)
        traced_sources = len({d["source_id"] for d in trace_data if d["target_id"]})
        coverage_pct = (traced_sources / total_sources * 100) if total_sources > 0 else 0

        # Output
        if output_format == OutputFormat.TABLE:
            table = Table(title=f"Traceability Matrix - Project {project_id}")
            table.add_column("Source", style="cyan")
            table.add_column("Source Type", style="dim")
            table.add_column("→", style="dim")
            table.add_column("Target", style="green")
            table.add_column("Target Type", style="dim")

            for row in trace_data:
                target_style = "red" if not row["target_id"] else "green"
                table.add_row(
                    row["source_name"][:50],
                    row["source_type"],
                    "→",
                    f"[{target_style}]{row['target_name'][:50]}[/{target_style}]",
                    row["target_type"],
                )

            console.print(table)
            console.print()
            console.print(f"[bold]Coverage:[/bold] {traced_sources}/{total_sources} ({coverage_pct:.1f}%)")
            if traced_sources < total_sources:
                console.print(f"[yellow]Warning:[/yellow] {total_sources - traced_sources} items have no downstream traces")
            if not refresh:
                console.print("[dim]Using cached data. Use --refresh for fresh data.[/dim]")
        else:
            format_output(trace_data, output_format)

    except Exception as e:
        print_error(f"Trace analysis failed: {e}")
        raise typer.Exit(1) from e


@app.command("coverage")
def trace_coverage(
    ctx: typer.Context,
    project_id: Annotated[int, typer.Argument(help="Project ID to analyze")],
    item_type: Annotated[
        int | None,
        typer.Option("--type", "-t", help="Item type ID to analyze coverage for"),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format"),
    ] = OutputFormat.TABLE,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", "-r", help="Bypass cache and fetch fresh data"),
    ] = False,
) -> None:
    """Show coverage summary by item type.

    Displays how many items of each type have upstream/downstream relationships.
    Uses bulk fetching for fast performance on large projects.

    Examples:
        jama trace coverage 1172
        jama trace coverage 1172 --type 33
        jama trace coverage 1172 --refresh    # Force fresh data
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        use_cache = not refresh

        if refresh:
            console.print("[dim]Cache bypassed - fetching fresh data...[/dim]")

        # Use optimized bulk fetching
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task1 = progress.add_task(f"Fetching items from project {project_id}...", total=None)
            items = client.get_items_bulk(project_id, use_cache=use_cache)
            progress.update(task1, completed=True, description=f"Fetched {len(items)} items")

            task2 = progress.add_task("Fetching relationships (bulk)...", total=None)
            relationship_map = client.build_relationship_map(project_id, use_cache=use_cache)
            progress.update(task2, completed=True, description="Built relationship map")

        if item_type:
            items = [i for i in items if i.get("itemType") == item_type]

        console.print(f"  [dim]Analyzing {len(items)} items[/dim]")

        # Get item types for display
        item_types_list = client.get_item_types()
        item_types: dict[int, str] = {t["id"]: t.get("display", t.get("name", "")) for t in item_types_list}

        # Analyze coverage per type using the pre-built map (no additional API calls!)
        coverage_by_type: dict[int, dict[str, int]] = defaultdict(lambda: {
            "total": 0,
            "has_upstream": 0,
            "has_downstream": 0,
        })

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Analyzing coverage...", total=len(items))

            for item in items:
                type_id = item.get("itemType")
                item_id = item["id"]
                coverage_by_type[type_id]["total"] += 1

                # Use pre-built relationship map (instant lookup!)
                item_rels = relationship_map.get(item_id, {"upstream": [], "downstream": []})

                if item_rels["upstream"]:
                    coverage_by_type[type_id]["has_upstream"] += 1
                if item_rels["downstream"]:
                    coverage_by_type[type_id]["has_downstream"] += 1

                progress.advance(task)

        # Build output
        coverage_data = []
        for type_id, stats in coverage_by_type.items():
            total = stats["total"]
            upstream_pct = (stats["has_upstream"] / total * 100) if total > 0 else 0
            downstream_pct = (stats["has_downstream"] / total * 100) if total > 0 else 0

            coverage_data.append({
                "type_id": type_id,
                "type_name": item_types.get(type_id, f"Type {type_id}"),
                "total_items": total,
                "has_upstream": stats["has_upstream"],
                "upstream_pct": f"{upstream_pct:.1f}%",
                "has_downstream": stats["has_downstream"],
                "downstream_pct": f"{downstream_pct:.1f}%",
            })

        if output_format == OutputFormat.TABLE:
            table = Table(title=f"Coverage Summary - Project {project_id}")
            table.add_column("Item Type", style="cyan")
            table.add_column("Total", justify="right")
            table.add_column("Has Upstream", justify="right")
            table.add_column("↑ %", justify="right")
            table.add_column("Has Downstream", justify="right")
            table.add_column("↓ %", justify="right")

            for row in coverage_data:
                table.add_row(
                    row["type_name"],
                    str(row["total_items"]),
                    str(row["has_upstream"]),
                    row["upstream_pct"],
                    str(row["has_downstream"]),
                    row["downstream_pct"],
                )

            console.print(table)
            if not refresh:
                console.print("\n[dim]Using cached data. Use --refresh for fresh data.[/dim]")
        else:
            format_output(coverage_data, output_format)

    except Exception as e:
        print_error(f"Coverage analysis failed: {e}")
        raise typer.Exit(1) from e


@app.command("tree")
def trace_tree(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item ID to trace from")],
    direction: Annotated[
        str,
        typer.Option("--direction", "-d", help="Direction: upstream, downstream, or both"),
    ] = "both",
    depth: Annotated[
        int,
        typer.Option("--depth", help="Maximum depth to traverse"),
    ] = 3,
) -> None:
    """Show trace tree for a specific item.

    Displays upstream and/or downstream relationships as a tree structure.

    Examples:
        jama trace tree 12345
        jama trace tree 12345 --direction upstream
        jama trace tree 12345 --depth 5
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)

        # Get the root item
        root_item = client.get_item(item_id)
        root_name = _get_item_name(root_item)

        # Get item types for display
        item_types_list = client.get_item_types()
        item_types: dict[int, str] = {t["id"]: t.get("display", t.get("name", "")) for t in item_types_list}

        tree = Tree(f"[bold cyan]{root_name}[/bold cyan] ({_get_item_type_name(root_item, item_types)})")

        visited: set[int] = {item_id}

        def add_branch(parent_tree: Tree, item_id: int, dir_label: str, get_related, current_depth: int) -> None:
            if current_depth >= depth:
                return

            related = get_related(item_id)
            for rel_item in related:
                rel_id = rel_item.get("id")
                if rel_id in visited:
                    continue
                visited.add(rel_id)

                rel_name = _get_item_name(rel_item)
                rel_type = _get_item_type_name(rel_item, item_types)

                style = "green" if dir_label == "↓" else "blue"
                branch = parent_tree.add(f"[{style}]{dir_label}[/{style}] {rel_name} ({rel_type})")

                # Recurse
                add_branch(branch, rel_id, dir_label, get_related, current_depth + 1)

        if direction in ("upstream", "both"):
            upstream_branch = tree.add("[blue]Upstream (traces from)[/blue]")
            add_branch(upstream_branch, item_id, "↑", client.get_item_upstream_related, 0)

        if direction in ("downstream", "both"):
            downstream_branch = tree.add("[green]Downstream (traces to)[/green]")
            add_branch(downstream_branch, item_id, "↓", client.get_item_downstream_related, 0)

        console.print(tree)

    except Exception as e:
        print_error(f"Trace tree failed: {e}")
        raise typer.Exit(1) from e
