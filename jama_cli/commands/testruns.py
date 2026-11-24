"""Test run result commands: actual results and screenshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

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

app = typer.Typer(name="testruns", help="Edit test run results (actual results, screenshots)")


def _wants_json(ctx: typer.Context, json_flag: bool) -> bool:
    """JSON output if asked for with ``--json`` or the global ``--output json``."""
    return json_flag or bool(ctx.obj and ctx.obj.get("output") == OutputFormat.JSON)


def _target(test_run_id: int, step: int | None) -> str:
    return f"step {step} of test run {test_run_id}" if step else f"test run {test_run_id}"


def _report(ctx: typer.Context, json_flag: bool, result: dict[str, Any], message: str) -> None:
    for warning in result.get("warnings", []):
        print_warning(warning)
    if _wants_json(ctx, json_flag):
        typer.echo(json.dumps(result, indent=2))
    elif result.get("updated"):
        print_success(message)
    else:
        print_info("Nothing to change; the test run was not modified.")


@app.command("get")
def get_test_run(
    ctx: typer.Context,
    test_run_id: Annotated[int, typer.Argument(help="Test run ID")],
) -> None:
    """Get a test run with its steps."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = (
        ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE
    )

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        run = client.get_test_run(test_run_id)

        format_single_item(run, format=output_format, title=f"Test Run {test_run_id}")

    except Exception as e:
        print_error(f"Failed to get test run: {e}")
        raise typer.Exit(1) from e


@app.command("add-screenshot")
def add_screenshot(
    ctx: typer.Context,
    test_run_id: Annotated[int, typer.Argument(help="Test run ID")],
    files: Annotated[list[Path], typer.Argument(help="Image file(s) to upload and embed")],
    step: Annotated[
        int | None,
        typer.Option(
            "--step", min=1, help="Step number (from 1). Default: the run-level actual results"
        ),
    ] = None,
    caption: Annotated[
        str | None, typer.Option("--caption", help="Text shown above each image")
    ] = None,
    project_id: Annotated[
        int | None,
        typer.Option("--project", help="Project for the attachments (default: the run's project)"),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Upload even if the same file was uploaded before"),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the result as JSON (for scripts)")
    ] = False,
) -> None:
    """Upload screenshots and embed them in a test run's actual results.

    The images are appended to the existing content; nothing is replaced.
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    for file_path in files:
        if not file_path.is_file():
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        result = client.attach_screenshots_to_test_run(
            test_run_id,
            list(files),
            step=step,
            caption=caption,
            project_id=project_id,
            use_cache=not no_cache,
        )
        count = len(result["embedded"])
        _report(
            ctx,
            json_output,
            result,
            f"Embedded {count} image(s) in the actual results of {_target(test_run_id, step)}",
        )
        if not _wants_json(ctx, json_output):
            for attachment in result["attachments"]:
                typer.echo(
                    f"Attachment {attachment['attachment_id']} (file {attachment['file_id']}): "
                    f"{attachment['embed_url']}"
                )

    except Exception as e:
        print_error(f"Failed to add screenshot: {e}")
        raise typer.Exit(1) from e


@app.command("set-actual")
def set_actual(
    ctx: typer.Context,
    test_run_id: Annotated[int, typer.Argument(help="Test run ID")],
    html: Annotated[str | None, typer.Option("--html", help="HTML to add")] = None,
    file: Annotated[
        Path | None, typer.Option("--file", help="File with the HTML to add (UTF-8)")
    ] = None,
    step: Annotated[
        int | None,
        typer.Option(
            "--step", min=1, help="Step number (from 1). Default: the run-level actual results"
        ),
    ] = None,
    replace: Annotated[
        bool,
        typer.Option("--replace", help="Replace the field's content instead of appending to it"),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the result as JSON (for scripts)")
    ] = False,
) -> None:
    """Write the actual results of a test run or of one of its steps.

    Without --step this is the run-level "Actual results" field; with --step N
    it is the "Result" column of that step. Appends to the existing content
    unless --replace is given. Other steps, their statuses and all other fields
    stay as they are.
    """
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    if (html is None) == (file is None):
        print_error("Give exactly one of --html or --file.")
        raise typer.Exit(1)

    if file is not None:
        if not file.is_file():
            print_error(f"File not found: {file}")
            raise typer.Exit(1)
        html = file.read_text(encoding="utf-8")
    assert html is not None

    try:
        client = JamaClient(profile)
        result = client.append_to_actual_results(
            test_run_id, html, step=step, mode="replace" if replace else "append"
        )
        verb = "Replaced" if replace else "Appended to"
        _report(
            ctx, json_output, result, f"{verb} the actual results of {_target(test_run_id, step)}"
        )

    except Exception as e:
        print_error(f"Failed to set actual results: {e}")
        raise typer.Exit(1) from e
