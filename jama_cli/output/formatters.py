"""Output formatters for different output formats."""
from __future__ import annotations

import csv
import io
import json
from enum import Enum
from typing import Any

import yaml
from rich.table import Table

from jama_cli.output.console import console


class OutputFormat(str, Enum):
    """Supported output formats."""

    TABLE = "table"
    JSON = "json"
    CSV = "csv"
    YAML = "yaml"


def format_output(
    data: list[dict[str, Any]] | dict[str, Any],
    format: OutputFormat = OutputFormat.TABLE,
    title: str | None = None,
    columns: list[str] | None = None,
) -> None:
    """Format and print data in the specified format.

    Args:
        data: Data to format (list of dicts or single dict)
        format: Output format
        title: Optional title for table output
        columns: Optional list of columns to display (for table/csv)
    """
    # Normalize to list
    if isinstance(data, dict):
        data = [data]

    if not data:
        console.print("[dim]No data to display[/dim]")
        return

    if format == OutputFormat.TABLE:
        _print_table(data, title=title, columns=columns)
    elif format == OutputFormat.JSON:
        _print_json(data)
    elif format == OutputFormat.CSV:
        _print_csv(data, columns=columns)
    elif format == OutputFormat.YAML:
        _print_yaml(data)


def _print_table(
    data: list[dict[str, Any]],
    title: str | None = None,
    columns: list[str] | None = None,
) -> None:
    """Print data as a rich table."""
    if not data:
        return

    # Determine columns
    if columns is None:
        # Use keys from first item, prioritizing common fields
        priority_fields = ["id", "name", "key", "status", "type", "project", "modified", "created"]
        all_keys = list(data[0].keys())
        columns = [k for k in priority_fields if k in all_keys]
        columns.extend([k for k in all_keys if k not in columns])

    # Create table
    table = Table(title=title, show_header=True, header_style="bold cyan")

    # Add columns
    for col in columns:
        table.add_column(_format_column_name(col))

    # Add rows
    for item in data:
        row = []
        for col in columns:
            value = item.get(col, "")
            row.append(_format_cell_value(value))
        table.add_row(*row)

    console.print(table)


def _format_column_name(name: str) -> str:
    """Format column name for display."""
    return name.replace("_", " ").title()


def _format_cell_value(value: Any) -> str:
    """Format cell value for display."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, dict):
        # For nested dicts, show a summary or specific field
        if "name" in value:
            return str(value["name"])
        if "id" in value:
            return f"[{value['id']}]"
        return "[...]"
    if isinstance(value, list):
        if len(value) == 0:
            return ""
        if len(value) <= 3:
            return ", ".join(str(v) for v in value)
        return f"{len(value)} items"
    return str(value)


def _print_json(data: list[dict[str, Any]]) -> None:
    """Print data as JSON."""
    # If single item, unwrap the list
    output = data[0] if len(data) == 1 else data
    console.print_json(json.dumps(output, indent=2, default=str))


def _print_csv(
    data: list[dict[str, Any]],
    columns: list[str] | None = None,
) -> None:
    """Print data as CSV."""
    if not data:
        return

    # Determine columns
    if columns is None:
        columns = list(data[0].keys())

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()

    for item in data:
        # Flatten nested values
        flat_item = {}
        for col in columns:
            value = item.get(col, "")
            if isinstance(value, dict | list):
                flat_item[col] = json.dumps(value)
            else:
                flat_item[col] = value
        writer.writerow(flat_item)

    console.print(output.getvalue().strip())


def _print_yaml(data: list[dict[str, Any]]) -> None:
    """Print data as YAML."""
    # If single item, unwrap the list
    output = data[0] if len(data) == 1 else data
    console.print(yaml.dump(output, default_flow_style=False, sort_keys=False))


def format_single_item(
    data: dict[str, Any],
    format: OutputFormat = OutputFormat.TABLE,
    title: str | None = None,
) -> None:
    """Format and print a single item with all fields."""
    if format == OutputFormat.TABLE:
        _print_item_details(data, title=title)
    else:
        format_output(data, format=format, title=title)


def _print_item_details(data: dict[str, Any], title: str | None = None) -> None:
    """Print a single item's details as key-value pairs."""
    table = Table(title=title, show_header=False, box=None)
    table.add_column("Field", style="cyan", width=20)
    table.add_column("Value")

    for key, value in data.items():
        formatted_value = _format_cell_value(value)
        if isinstance(value, dict) and value:
            # Pretty print nested dicts
            formatted_value = json.dumps(value, indent=2, default=str)
        table.add_row(_format_column_name(key), formatted_value)

    console.print(table)
