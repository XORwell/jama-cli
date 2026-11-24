"""Login, logout and status for the browser-session ("SSO cookie") auth mode."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated, Any

import typer

from jama_cli.config import get_profile_or_env
from jama_cli.core.session import SessionManager
from jama_cli.models import JamaProfile
from jama_cli.output import OutputFormat, format_single_item, print_error, print_success


def _session_profile(ctx: typer.Context) -> JamaProfile:
    """Resolve the active profile and make sure it uses session auth."""
    profile = get_profile_or_env(ctx.obj.get("profile") if ctx.obj else None)
    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)
    if profile.auth_type != "session":
        print_error(
            f"This profile uses auth_type '{profile.auth_type}'. Login sessions only apply "
            "to auth_type 'session' (set it in the profile or JAMA_AUTH_TYPE=session)."
        )
        raise typer.Exit(1)
    return profile


def _format_time(timestamp: float | None) -> str:
    if not timestamp:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def _format_age(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def login(
    ctx: typer.Context,
    mode: Annotated[
        str | None,
        typer.Option("--mode", "-m", help="Login mode: browser (default) or form"),
    ] = None,
    browser_channel: Annotated[
        str | None,
        typer.Option(
            "--browser-channel", help="Browser to use, e.g. chrome or msedge (default: Chromium)"
        ),
    ] = None,
    profile_dir: Annotated[
        Path | None,
        typer.Option("--browser-profile-dir", help="Persistent browser profile directory"),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Seconds to wait for the login to finish"),
    ] = None,
    debug_dir: Annotated[
        Path | None,
        typer.Option("--debug-dir", help="Save a screenshot of each login step here"),
    ] = None,
    headful: Annotated[
        bool,
        typer.Option("--headful", help="Skip the silent attempt and open a window right away"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Log in again even if the stored session is valid"),
    ] = False,
) -> None:
    """Log in to Jama as yourself and store the web session.

    The browser mode opens a real browser, so SSO, MFA and consent screens work.
    Your password is never read or stored. Later logins are usually silent.

    Examples:
        jama login                          # Browser login (SSO or native form)
        jama login --browser-channel msedge # Use the installed Edge
        jama login --mode form              # No browser; JAMA_USERNAME / JAMA_PASSWORD
        jama login --debug-dir ./login-dbg  # Screenshots for diagnosing a failed login
    """
    profile = _session_profile(ctx)
    settings = profile.session_settings()
    if mode:
        if mode not in ("browser", "form"):
            print_error("--mode must be 'browser' or 'form'")
            raise typer.Exit(1)
        settings.login_mode = mode
    if browser_channel:
        settings.browser_channel = browser_channel
    if profile_dir:
        settings.browser_profile_dir = profile_dir
    if timeout:
        settings.login_timeout = timeout
    if debug_dir:
        settings.debug_dir = debug_dir

    try:
        manager = SessionManager(settings)
        session = asyncio.run(manager.login("always" if headful else "auto", force=force))
    except Exception as e:
        print_error(f"Login failed: {e}")
        raise typer.Exit(1) from e

    print_success(f"Logged in to {settings.base_url} as {session.username or 'unknown user'}")


def logout(ctx: typer.Context) -> None:
    """Log out of Jama, release the license seat and delete the stored session."""
    profile = _session_profile(ctx)
    try:
        had_session = asyncio.run(SessionManager(profile.session_settings()).logout())
    except Exception as e:
        print_error(f"Logout failed (the stored session was removed anyway): {e}")
        raise typer.Exit(1) from e

    if had_session:
        print_success("Logged out and removed the stored session")
    else:
        print_success("No stored session")


def status(ctx: typer.Context) -> None:
    """Show the stored Jama session and whether it is still valid.

    Cookie and token values are never shown.
    """
    profile = _session_profile(ctx)
    output_format: OutputFormat = (
        ctx.obj.get("output", OutputFormat.TABLE) if ctx.obj else OutputFormat.TABLE
    )
    try:
        info = asyncio.run(SessionManager(profile.session_settings()).status())
    except Exception as e:
        print_error(f"Could not check the session: {e}")
        raise typer.Exit(1) from e

    display: dict[str, Any] = {
        "base_url": info["base_url"],
        "logged_in": info["logged_in"],
        "username": info["username"] or "-",
        "age": _format_age(info["age_seconds"]),
        "created": _format_time(info["created_at"]),
        "last_validated": _format_time(info["last_validated_at"]),
        "valid": info["valid"],
    }
    format_single_item(display, format=output_format, title="Jama Session")
    if not info["valid"]:
        raise typer.Exit(1)
