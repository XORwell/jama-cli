"""Projects commands."""
from __future__ import annotations

from typing import Annotated

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.client import JamaClient
from jama_cli.output import OutputFormat, format_output, format_single_item, print_error

app = typer.Typer(name="projects", help="Manage Jama projects")


@app.command("list")
def list_projects(
    ctx: typer.Context,
    fields: Annotated[
        str | None,
        typer.Option("--fields", "-f", help="Comma-separated fields to display"),
    ] = None,
) -> None:
    """List all accessible projects."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        projects = client.get_projects()

        # Parse fields
        columns = fields.split(",") if fields else None

        format_output(
            projects,
            format=output_format,
            title="Projects",
            columns=columns,
        )

    except Exception as e:
        print_error(f"Failed to list projects: {e}")
        raise typer.Exit(1) from e


@app.command("get")
def get_project(
    ctx: typer.Context,
    project_id: Annotated[int, typer.Argument(help="Project ID")],
) -> None:
    """Get details of a specific project."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    output_format: OutputFormat = ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE

    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    try:
        client = JamaClient(profile)
        project = client.get_project(project_id)

        format_single_item(
            project,
            format=output_format,
            title=f"Project {project_id}",
        )

    except Exception as e:
        print_error(f"Failed to get project: {e}")
        raise typer.Exit(1) from e
