"""Attachments commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import (
    OutputFormat,
    format_single_item,
    print_error,
    print_info,
    print_success,
    print_warning,
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


def _wants_json(ctx: typer.Context, json_flag: bool) -> bool:
    """JSON output if asked for with ``--json`` or the global ``--output json``."""
    return json_flag or bool(ctx.obj and ctx.obj.get("output") == OutputFormat.JSON)


@app.command("upload")
def upload_attachment(
    ctx: typer.Context,
    item_id: Annotated[int, typer.Argument(help="Item ID to attach file to")],
    file_path: Annotated[Path, typer.Argument(help="File to upload")],
    name: Annotated[
        str | None, typer.Option("--name", help="Attachment name (default: the file name)")
    ] = None,
    description: Annotated[str, typer.Option("--description", help="Attachment description")] = "",
    project_id: Annotated[
        int | None,
        typer.Option(
            "--project",
            help="Project for the attachment (default: the project of the item or test run)",
        ),
    ] = None,
    no_link: Annotated[
        bool,
        typer.Option("--no-link", help="Do not link the attachment to the item's Attachments tab"),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Upload even if the same file was uploaded before"),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the result as JSON (for scripts)")
    ] = False,
) -> None:
    """Upload a file as an attachment to an item.

    Prints the attachment ID, the stored file's ID and the embed URL to use for
    an inline image.

    The ID may also be a test run. Test runs are not items in the REST API, so
    the attachment is created in the run's project but cannot be linked (there
    is no Attachments tab to link to); the embed URL works without the link.
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    if not file_path.exists():
        print_error(f"File not found: {file_path}")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        result = client.upload_attachment(
            item_id,
            file_path,
            name=name,
            description=description,
            project_id=project_id,
            link=not no_link,
            use_cache=not no_cache,
        )
        for warning in result.get("warnings", []):
            print_warning(warning)
        for note in result.get("info", []):
            print_info(note)
        if _wants_json(ctx, json_output):
            typer.echo(json.dumps(result, indent=2))
            return
        verb = "Reused" if result.get("reused") else "Uploaded"
        print_success(f"{verb} attachment with ID: {result['attachment_id']}")
        typer.echo(f"File ID: {result['file_id']}")
        typer.echo(f"Embed URL: {result['embed_url']}")
        target = "test run" if result.get("target_is_test_run") else "item"
        typer.echo(f"Linked to {target} {item_id}: {'yes' if result.get('linked') else 'no'}")

    except Exception as e:
        print_error(f"Failed to upload attachment: {e}")
        raise typer.Exit(1) from e


@app.command("download")
def download_attachment(
    ctx: typer.Context,
    attachment_id: Annotated[int, typer.Argument(help="Attachment ID")],
    output_path: Annotated[
        Path, typer.Option("--output-path", "-o", help="File to write the attachment to")
    ],
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the result as JSON (for scripts)")
    ] = False,
) -> None:
    """Download an attachment's file."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        path = client.download_attachment(attachment_id, output_path)
        size = path.stat().st_size
        if _wants_json(ctx, json_output):
            typer.echo(
                json.dumps({"attachment_id": attachment_id, "path": str(path), "bytes": size})
            )
            return
        print_success(f"Saved attachment {attachment_id} to {path} ({size} bytes)")

    except Exception as e:
        print_error(f"Failed to download attachment: {e}")
        raise typer.Exit(1) from e


@app.command("download-url")
def download_url(
    ctx: typer.Context,
    url: Annotated[str, typer.Argument(help="Embed URL of the file (e.g. an inline image)")],
    output_path: Annotated[
        Path, typer.Option("--output-path", "-o", help="File to write the content to")
    ],
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the result as JSON (for scripts)")
    ] = False,
) -> None:
    """Download an embedded file (e.g. an inline image) by its URL."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        path = client.download_embedded(url, output_path)
        size = path.stat().st_size
        if _wants_json(ctx, json_output):
            typer.echo(json.dumps({"url": url, "path": str(path), "bytes": size}))
            return
        print_success(f"Saved {path} ({size} bytes)")

    except Exception as e:
        print_error(f"Failed to download file: {e}")
        raise typer.Exit(1) from e
