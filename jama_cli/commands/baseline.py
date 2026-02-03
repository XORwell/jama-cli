"""Baseline management and comparison commands."""
from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import print_error, print_info, print_success
from jama_cli.output.formatters import OutputFormat, format_output

app = typer.Typer(name="baseline", help="Baseline management and comparison")
console = Console()


def _get_item_name(item: dict[str, Any]) -> str:
    """Get display name for an item."""
    fields = item.get("fields", {})
    name = fields.get("name", item.get("name", ""))
    doc_key = item.get("documentKey", "")
    if doc_key:
        return f"{doc_key}: {name}"
    return name or f"Item {item.get('id')}"


@app.command("list")
def list_baselines(
    ctx: typer.Context,
    project_id: Annotated[int, typer.Argument(help="Project ID")],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format"),
    ] = OutputFormat.TABLE,
) -> None:
    """List all baselines in a project.
    
    Examples:
        jama baseline list 1172
        jama baseline list 1172 --format json
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        baselines = client.get_baselines(project_id)
        
        if not baselines:
            print_info("No baselines found")
            return
        
        # Simplify for display
        display_data = []
        for b in baselines:
            display_data.append({
                "id": b.get("id"),
                "name": b.get("name", ""),
                "description": b.get("description", "")[:50] if b.get("description") else "",
                "created": b.get("createdDate", "")[:10] if b.get("createdDate") else "",
            })
        
        format_output(display_data, output_format, title=f"Baselines - Project {project_id}")
        
    except Exception as e:
        print_error(f"Failed to list baselines: {e}")
        raise typer.Exit(1) from e


@app.command("get")
def get_baseline(
    ctx: typer.Context,
    baseline_id: Annotated[int, typer.Argument(help="Baseline ID")],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format"),
    ] = OutputFormat.TABLE,
) -> None:
    """Get baseline details.
    
    Examples:
        jama baseline get 100
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        baseline = client.get_baseline(baseline_id)
        format_output(baseline, output_format, title=f"Baseline {baseline_id}")
        
    except Exception as e:
        print_error(f"Failed to get baseline: {e}")
        raise typer.Exit(1) from e


@app.command("items")
def baseline_items(
    ctx: typer.Context,
    baseline_id: Annotated[int, typer.Argument(help="Baseline ID")],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format"),
    ] = OutputFormat.TABLE,
) -> None:
    """List items in a baseline.
    
    Examples:
        jama baseline items 100
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        items = client.get_baseline_versioned_items(baseline_id)
        
        if not items:
            print_info("No items in baseline")
            return
        
        # Simplify for display
        display_data = []
        for item in items:
            display_data.append({
                "id": item.get("id"),
                "documentKey": item.get("documentKey", ""),
                "name": _get_item_name(item),
                "version": item.get("version", ""),
                "type": item.get("itemType", ""),
            })
        
        format_output(display_data, output_format, title=f"Items in Baseline {baseline_id}")
        
    except Exception as e:
        print_error(f"Failed to get baseline items: {e}")
        raise typer.Exit(1) from e


@app.command("diff")
def diff_baselines(
    ctx: typer.Context,
    baseline1_id: Annotated[int, typer.Argument(help="First baseline ID (older)")],
    baseline2_id: Annotated[int, typer.Argument(help="Second baseline ID (newer)")],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format"),
    ] = OutputFormat.TABLE,
) -> None:
    """Compare two baselines and show differences.
    
    Shows items that were added, removed, or modified between two baselines.
    
    Examples:
        jama baseline diff 100 101
        jama baseline diff 100 101 --format json
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        
        print_info(f"Comparing baselines {baseline1_id} and {baseline2_id}...")
        
        # Get baseline info
        baseline1 = client.get_baseline(baseline1_id)
        baseline2 = client.get_baseline(baseline2_id)
        
        # Get items from both baselines
        items1 = client.get_baseline_versioned_items(baseline1_id)
        items2 = client.get_baseline_versioned_items(baseline2_id)
        
        # Build lookup by item ID
        items1_map: dict[int, dict[str, Any]] = {}
        for item in items1:
            item_id = item.get("id")
            if item_id:
                items1_map[item_id] = item
        
        items2_map: dict[int, dict[str, Any]] = {}
        for item in items2:
            item_id = item.get("id")
            if item_id:
                items2_map[item_id] = item
        
        # Find differences
        diff_data = []
        
        # Added items (in baseline2 but not in baseline1)
        for item_id, item in items2_map.items():
            if item_id not in items1_map:
                diff_data.append({
                    "change": "Added",
                    "id": item_id,
                    "documentKey": item.get("documentKey", ""),
                    "name": _get_item_name(item),
                    "old_version": "-",
                    "new_version": item.get("version", ""),
                })
        
        # Removed items (in baseline1 but not in baseline2)
        for item_id, item in items1_map.items():
            if item_id not in items2_map:
                diff_data.append({
                    "change": "Removed",
                    "id": item_id,
                    "documentKey": item.get("documentKey", ""),
                    "name": _get_item_name(item),
                    "old_version": item.get("version", ""),
                    "new_version": "-",
                })
        
        # Modified items (version changed)
        for item_id, item2 in items2_map.items():
            if item_id in items1_map:
                item1 = items1_map[item_id]
                v1 = item1.get("version")
                v2 = item2.get("version")
                if v1 != v2:
                    diff_data.append({
                        "change": "Modified",
                        "id": item_id,
                        "documentKey": item2.get("documentKey", ""),
                        "name": _get_item_name(item2),
                        "old_version": v1,
                        "new_version": v2,
                    })
        
        if not diff_data:
            print_success("Baselines are identical")
            return
        
        # Sort by change type
        change_order = {"Added": 0, "Modified": 1, "Removed": 2}
        diff_data.sort(key=lambda x: (change_order.get(x["change"], 3), x.get("documentKey", "")))
        
        if output_format == OutputFormat.TABLE:
            table = Table(title=f"Baseline Diff: {baseline1.get('name', baseline1_id)} → {baseline2.get('name', baseline2_id)}")
            table.add_column("Change", style="bold")
            table.add_column("Key")
            table.add_column("Name")
            table.add_column("Old Ver", justify="right")
            table.add_column("New Ver", justify="right")
            
            for row in diff_data:
                change = row["change"]
                if change == "Added":
                    style = "green"
                    prefix = "+"
                elif change == "Removed":
                    style = "red"
                    prefix = "-"
                else:
                    style = "yellow"
                    prefix = "~"
                
                table.add_row(
                    f"[{style}]{prefix} {change}[/{style}]",
                    row["documentKey"],
                    row["name"][:40],
                    str(row["old_version"]),
                    str(row["new_version"]),
                )
            
            console.print(table)
            console.print()
            
            # Summary
            added = len([d for d in diff_data if d["change"] == "Added"])
            removed = len([d for d in diff_data if d["change"] == "Removed"])
            modified = len([d for d in diff_data if d["change"] == "Modified"])
            console.print(f"[green]+{added} added[/green], [yellow]~{modified} modified[/yellow], [red]-{removed} removed[/red]")
        else:
            format_output(diff_data, output_format)
        
    except Exception as e:
        print_error(f"Baseline diff failed: {e}")
        raise typer.Exit(1) from e
