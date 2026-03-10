"""Diff commands for comparing items between projects/instances."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from jama_cli.config import get_profile_or_env, load_config
from jama_cli.core.client import JamaClient
from jama_cli.output import console, print_error

app = typer.Typer(name="diff", help="Compare items between projects or instances")


@app.command("projects")
def diff_projects(
    ctx: typer.Context,
    source_project: Annotated[int, typer.Argument(help="Source project ID")],
    target_project: Annotated[int, typer.Argument(help="Target project ID")],
    source_profile: Annotated[
        str | None,
        typer.Option("--from", "-f", help="Source profile (for cross-instance diff)"),
    ] = None,
    target_profile: Annotated[
        str | None,
        typer.Option("--to", "-t", help="Target profile (for cross-instance diff)"),
    ] = None,
    item_type: Annotated[
        int | None,
        typer.Option("--type", help="Compare only items of this type"),
    ] = None,
    key_field: Annotated[
        str,
        typer.Option("--key", "-k", help="Field to match items by (default: documentKey)"),
    ] = "documentKey",
    compare_fields: Annotated[
        str | None,
        typer.Option("--fields", help="Comma-separated fields to compare"),
    ] = None,
    show_unchanged: Annotated[
        bool,
        typer.Option("--show-unchanged", "-u", help="Show unchanged items too"),
    ] = False,
    summary_only: Annotated[
        bool,
        typer.Option("--summary", "-s", help="Show only summary, not details"),
    ] = False,
) -> None:
    """Compare items between two projects.

    Compares items by matching on a key field (default: documentKey) and
    reports differences in item fields.

    Examples:
        jama diff projects 123 456                        # Compare projects
        jama diff projects 123 456 --from dev --to prod   # Compare across instances
        jama diff projects 123 456 --type 45              # Compare only type 45
        jama diff projects 123 456 --fields name,desc     # Compare specific fields
        jama diff projects 123 456 --key name             # Match by name
    """
    config = load_config()

    # Determine source and target clients
    if source_profile and target_profile:
        # Cross-instance comparison
        source = config.profiles.get(source_profile)
        target = config.profiles.get(target_profile)

        if not source:
            print_error(f"Source profile '{source_profile}' not found")
            raise typer.Exit(1)
        if not target:
            print_error(f"Target profile '{target_profile}' not found")
            raise typer.Exit(1)

        source_client = JamaClient(source)
        target_client = JamaClient(target)

        console.print("[bold]Cross-Instance Diff[/bold]")
        console.print(f"  Source: {source.url} (project {source_project})")
        console.print(f"  Target: {target.url} (project {target_project})")
    else:
        # Same instance comparison
        profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

        if not profile:
            print_error("No profile configured. Run 'jama config init' to set up.")
            raise typer.Exit(1)

        source_client = JamaClient(profile)
        target_client = source_client

        console.print("[bold]Project Diff[/bold]")
        console.print(f"  Source: Project {source_project}")
        console.print(f"  Target: Project {target_project}")

    try:
        # Fetch items from both projects with progress
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task1 = progress.add_task(f"Fetching source project {source_project}...", total=None)
            source_items = source_client.get_items(source_project, item_type=item_type)
            progress.update(task1, completed=True, description=f"Source: {len(source_items)} items")

            task2 = progress.add_task(f"Fetching target project {target_project}...", total=None)
            target_items = target_client.get_items(target_project, item_type=item_type)
            progress.update(task2, completed=True, description=f"Target: {len(target_items)} items")

        # Determine fields to compare
        if compare_fields:
            fields_to_compare = compare_fields.split(",")
        else:
            fields_to_compare = ["name", "description", "status"]

        # Build lookup maps by key field
        source_map = _build_item_map(source_items, key_field)
        target_map = _build_item_map(target_items, key_field)

        # Calculate diff
        diff_result = _calculate_diff(
            source_map=source_map,
            target_map=target_map,
            fields_to_compare=fields_to_compare,
        )

        # Display results
        _display_diff_results(
            diff_result=diff_result,
            key_field=key_field,
            fields_to_compare=fields_to_compare,
            show_unchanged=show_unchanged,
            summary_only=summary_only,
        )

    except Exception as e:
        print_error(f"Diff failed: {e}")
        raise typer.Exit(1) from e


def _build_item_map(
    items: list[dict[str, Any]],
    key_field: str,
) -> dict[str, dict[str, Any]]:
    """Build a map of items by key field."""
    item_map: dict[str, dict[str, Any]] = {}

    for item in items:
        key = _get_item_key(item, key_field)
        if key:
            item_map[key] = item

    return item_map


def _get_item_key(item: dict[str, Any], key_field: str) -> str | None:
    """Get the key value from an item."""
    # Check top-level
    if key_field in item:
        value = item[key_field]
        return str(value) if value else None

    # Check in fields
    fields = item.get("fields", {})
    if key_field in fields:
        value = fields[key_field]
        return str(value) if value else None

    return None


def _get_field_value(item: dict[str, Any], field: str) -> Any:
    """Get a field value from an item."""
    # Check top-level
    if field in item:
        return item[field]

    # Check in fields
    fields = item.get("fields", {})
    if field in fields:
        return fields[field]

    return None


def _calculate_diff(
    source_map: dict[str, dict[str, Any]],
    target_map: dict[str, dict[str, Any]],
    fields_to_compare: list[str],
) -> dict[str, Any]:
    """Calculate differences between source and target items."""
    result = {
        "only_in_source": [],  # Items only in source
        "only_in_target": [],  # Items only in target
        "modified": [],  # Items that differ
        "unchanged": [],  # Items that match
    }

    all_keys = set(source_map.keys()) | set(target_map.keys())

    for key in all_keys:
        source_item = source_map.get(key)
        target_item = target_map.get(key)

        if source_item and not target_item:
            result["only_in_source"].append(
                {
                    "key": key,
                    "item": source_item,
                }
            )
        elif target_item and not source_item:
            result["only_in_target"].append(
                {
                    "key": key,
                    "item": target_item,
                }
            )
        else:
            # Both exist - compare fields
            differences = []
            for field in fields_to_compare:
                source_val = _get_field_value(source_item, field)
                target_val = _get_field_value(target_item, field)

                if source_val != target_val:
                    differences.append(
                        {
                            "field": field,
                            "source": source_val,
                            "target": target_val,
                        }
                    )

            if differences:
                result["modified"].append(
                    {
                        "key": key,
                        "source_item": source_item,
                        "target_item": target_item,
                        "differences": differences,
                    }
                )
            else:
                result["unchanged"].append(
                    {
                        "key": key,
                        "item": source_item,
                    }
                )

    return result


def _display_diff_results(
    diff_result: dict[str, Any],
    key_field: str,
    fields_to_compare: list[str],  # noqa: ARG001
    show_unchanged: bool = False,
    summary_only: bool = False,
) -> None:
    """Display diff results."""
    only_source = diff_result["only_in_source"]
    only_target = diff_result["only_in_target"]
    modified = diff_result["modified"]
    unchanged = diff_result["unchanged"]

    # Summary
    console.print("\n[bold]Diff Summary[/bold]")

    summary_table = Table(show_header=False, box=None)
    summary_table.add_column("Category", style="cyan", width=25)
    summary_table.add_column("Count", justify="right")

    summary_table.add_row("Only in source:", f"[red]{len(only_source)}[/red]")
    summary_table.add_row("Only in target:", f"[green]{len(only_target)}[/green]")
    summary_table.add_row("Modified:", f"[yellow]{len(modified)}[/yellow]")
    summary_table.add_row("Unchanged:", f"[dim]{len(unchanged)}[/dim]")
    summary_table.add_row("", "")
    summary_table.add_row(
        "[bold]Total compared:[/bold]",
        f"[bold]{len(only_source) + len(only_target) + len(modified) + len(unchanged)}[/bold]",
    )

    console.print(summary_table)

    if summary_only:
        return

    # Details
    if only_source:
        console.print(f"\n[bold red]Only in Source ({len(only_source)})[/bold red]")
        table = Table()
        table.add_column(key_field)
        table.add_column("Name")
        table.add_column("ID")

        for entry in only_source[:20]:  # Limit to 20
            item = entry["item"]
            table.add_row(
                entry["key"],
                str(_get_field_value(item, "name") or ""),
                str(item.get("id", "")),
            )

        if len(only_source) > 20:
            table.add_row(f"[dim]... and {len(only_source) - 20} more[/dim]", "", "")

        console.print(table)

    if only_target:
        console.print(f"\n[bold green]Only in Target ({len(only_target)})[/bold green]")
        table = Table()
        table.add_column(key_field)
        table.add_column("Name")
        table.add_column("ID")

        for entry in only_target[:20]:  # Limit to 20
            item = entry["item"]
            table.add_row(
                entry["key"],
                str(_get_field_value(item, "name") or ""),
                str(item.get("id", "")),
            )

        if len(only_target) > 20:
            table.add_row(f"[dim]... and {len(only_target) - 20} more[/dim]", "", "")

        console.print(table)

    if modified:
        console.print(f"\n[bold yellow]Modified ({len(modified)})[/bold yellow]")

        for entry in modified[:10]:  # Limit to 10
            console.print(f"\n  [cyan]{key_field}:[/cyan] {entry['key']}")

            diff_table = Table(show_header=True, box=None, padding=(0, 2))
            diff_table.add_column("Field")
            diff_table.add_column("Source", style="red")
            diff_table.add_column("Target", style="green")

            for diff in entry["differences"]:
                source_str = str(diff["source"])[:50] if diff["source"] else "[empty]"
                target_str = str(diff["target"])[:50] if diff["target"] else "[empty]"
                diff_table.add_row(diff["field"], source_str, target_str)

            console.print(diff_table)

        if len(modified) > 10:
            console.print(f"\n[dim]... and {len(modified) - 10} more modified items[/dim]")

    if show_unchanged and unchanged:
        console.print(f"\n[dim]Unchanged ({len(unchanged)})[/dim]")
        for entry in unchanged[:5]:
            console.print(f"  {entry['key']}")
        if len(unchanged) > 5:
            console.print(f"  [dim]... and {len(unchanged) - 5} more[/dim]")


@app.command("count")
def diff_count(
    ctx: typer.Context,
    source_project: Annotated[int, typer.Argument(help="Source project ID")],
    target_project: Annotated[int, typer.Argument(help="Target project ID")],
    source_profile: Annotated[
        str | None,
        typer.Option("--from", "-f", help="Source profile"),
    ] = None,
    target_profile: Annotated[
        str | None,
        typer.Option("--to", "-t", help="Target profile"),
    ] = None,
    item_type: Annotated[
        int | None,
        typer.Option("--type", help="Compare only items of this type"),
    ] = None,
) -> None:
    """Quick count comparison between projects.

    Shows item counts by type without detailed diff.

    Example:
        jama diff count 123 456
        jama diff count 123 456 --from dev --to prod
    """
    config = load_config()

    # Setup clients
    if source_profile and target_profile:
        source = config.profiles.get(source_profile)
        target = config.profiles.get(target_profile)
        if not source or not target:
            print_error("Profile not found")
            raise typer.Exit(1)
        source_client = JamaClient(source)
        target_client = JamaClient(target)
    else:
        profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
        if not profile:
            print_error("No profile configured")
            raise typer.Exit(1)
        source_client = JamaClient(profile)
        target_client = source_client

    try:
        # Get items
        source_items = source_client.get_items(source_project, item_type=item_type)
        target_items = target_client.get_items(target_project, item_type=item_type)

        # Count by type
        source_counts: dict[int, int] = {}
        target_counts: dict[int, int] = {}

        for item in source_items:
            t = item.get("itemType", 0)
            source_counts[t] = source_counts.get(t, 0) + 1

        for item in target_items:
            t = item.get("itemType", 0)
            target_counts[t] = target_counts.get(t, 0) + 1

        # Display
        all_types = set(source_counts.keys()) | set(target_counts.keys())

        table = Table(title="Item Count Comparison")
        table.add_column("Item Type")
        table.add_column("Source", justify="right")
        table.add_column("Target", justify="right")
        table.add_column("Diff", justify="right")

        total_source = 0
        total_target = 0

        for type_id in sorted(all_types):
            s = source_counts.get(type_id, 0)
            t = target_counts.get(type_id, 0)
            diff = t - s

            total_source += s
            total_target += t

            diff_str = f"+{diff}" if diff > 0 else str(diff)
            diff_style = "green" if diff > 0 else ("red" if diff < 0 else "dim")

            table.add_row(
                str(type_id),
                str(s),
                str(t),
                f"[{diff_style}]{diff_str}[/{diff_style}]",
            )

        # Total row
        total_diff = total_target - total_source
        total_diff_str = f"+{total_diff}" if total_diff > 0 else str(total_diff)

        table.add_row("", "", "", "")
        table.add_row(
            "[bold]Total[/bold]",
            f"[bold]{total_source}[/bold]",
            f"[bold]{total_target}[/bold]",
            f"[bold]{total_diff_str}[/bold]",
        )

        console.print(table)

    except Exception as e:
        print_error(f"Count failed: {e}")
        raise typer.Exit(1) from e
