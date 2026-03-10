"""Attachments commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import (
    OutputFormat,
    format_single_item,
    print_error,
    print_success,
)

app = typer.Typer(name="attachments", help="Manage item attachments")


@app.command("get")
def get_attachment(
    ctx: typer.Context,
    attachment_id: Annotated[int, typer.Argument(help="Attachment ID")],
) -> None:
    """Get attachment metadata."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = (
        ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE
    )

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        attachment = client.get_attachment(attachment_id)

        format_single_item(
            attachment,
            format=output_format,
            title=f"Attachment {attachment_id}",
        )

    except Exception as e:
        print_error(f"Failed to get attachment: {e}")
        raise typer.Exit(1) from e


@app.command("upload")
def upload_attachment(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item ID to attach file to")],
    file_path: Annotated[Path, typer.Argument(help="File to upload")],
) -> None:
    """Upload a file as an attachment to an item."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    if not file_path.exists():
        print_error(f"File not found: {file_path}")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        attachment_id = client.upload_attachment(item_id, file_path)
        print_success(f"Uploaded attachment with ID: {attachment_id}")

    except Exception as e:
        print_error(f"Failed to upload attachment: {e}")
        raise typer.Exit(1) from e
