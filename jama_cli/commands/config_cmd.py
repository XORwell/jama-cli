"""Configuration management commands."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from jama_cli.config import CONFIG_FILE, get_config_path, load_config, save_config
from jama_cli.models import JamaProfile
from jama_cli.output import console, print_error, print_success

app = typer.Typer(name="config", help="Manage CLI configuration and profiles")


@app.command("init")
def init_config() -> None:
    """Initialize configuration interactively."""
    config = load_config()

    console.print("\n[bold]Jama CLI Configuration[/bold]\n")

    # Get profile name
    profile_name = console.input("Profile name [bold][default][/bold]: ").strip()
    if not profile_name:
        profile_name = "default"

    # Get Jama URL
    url = console.input("Jama URL (e.g., https://company.jamacloud.com): ").strip()
    if not url:
        print_error("URL is required")
        raise typer.Exit(1)

    # Get auth type
    console.print("\nAuthentication types:")
    console.print("  1. API Key (recommended)")
    console.print("  2. OAuth2 Client Credentials")
    console.print("  3. Username/Password")
    auth_choice = console.input("\nAuth type [bold][1][/bold]: ").strip() or "1"

    auth_type: str
    api_key: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    username: str | None = None
    password: str | None = None

    if auth_choice == "1":
        auth_type = "api_key"
        api_key = console.input("API Key: ", password=True).strip()
        if not api_key:
            print_error("API key is required")
            raise typer.Exit(1)
    elif auth_choice == "2":
        auth_type = "oauth"
        client_id = console.input("Client ID: ").strip()
        client_secret = console.input("Client Secret: ", password=True).strip()
        if not client_id or not client_secret:
            print_error("Client ID and secret are required")
            raise typer.Exit(1)
    else:
        auth_type = "basic"
        username = console.input("Username: ").strip()
        password = console.input("Password: ", password=True).strip()
        if not username or not password:
            print_error("Username and password are required")
            raise typer.Exit(1)

    # Create profile
    profile = JamaProfile(
        url=url,
        auth_type=auth_type,
        api_key=api_key,
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
    )

    # Add to config
    config.profiles[profile_name] = profile
    if len(config.profiles) == 1:
        config.default_profile = profile_name

    # Save
    save_config(config)
    print_success(f"Configuration saved to {get_config_path()}")

    # Offer to test connection
    if console.input("\nTest connection? [bold][Y/n][/bold]: ").strip().lower() != "n":
        try:
            from jama_cli.core.client import JamaClient

            client = JamaClient(profile)
            user = client.get_current_user()
            print_success(f"Connected as: {user.get('username', 'unknown')}")
        except Exception as e:
            print_error(f"Connection failed: {e}")


@app.command("list")
def list_profiles() -> None:
    """List all configured profiles."""
    config = load_config()

    if not config.profiles:
        console.print("[dim]No profiles configured. Run 'jama config init' to set up.[/dim]")
        raise typer.Exit(1)

    table = Table(title="Configured Profiles")
    table.add_column("Name")
    table.add_column("URL")
    table.add_column("Auth Type")
    table.add_column("Default")

    for name, profile in config.profiles.items():
        is_default = "Yes" if name == config.default_profile else ""
        table.add_row(name, profile.url, profile.auth_type, is_default)

    console.print(table)
    console.print(f"\n[dim]Config file: {get_config_path()}[/dim]")


@app.command("show")
def show_profile(
    name: Annotated[str | None, typer.Argument(help="Profile name")] = None,
) -> None:
    """Show details of a profile."""
    config = load_config()

    profile_name = name or config.default_profile
    profile = config.profiles.get(profile_name)

    if not profile:
        print_error(f"Profile '{profile_name}' not found")
        raise typer.Exit(1)

    table = Table(title=f"Profile: {profile_name}")
    table.add_column("Setting")
    table.add_column("Value")

    masked = profile.get_masked_display()
    for key, value in masked.items():
        if value:  # Only show non-empty values
            table.add_row(key, str(value))

    console.print(table)


@app.command("add")
def add_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    url: Annotated[str, typer.Option("--url", "-u", help="Jama URL")],
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", "-k", help="API key"),
    ] = None,
    client_id: Annotated[
        str | None,
        typer.Option("--client-id", help="OAuth client ID"),
    ] = None,
    client_secret: Annotated[
        str | None,
        typer.Option("--client-secret", help="OAuth client secret"),
    ] = None,
    username: Annotated[
        str | None,
        typer.Option("--username", "-U", help="Username"),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option("--password", "-P", help="Password"),
    ] = None,
) -> None:
    """Add a new profile."""
    config = load_config()

    # Determine auth type
    if api_key:
        auth_type = "api_key"
    elif client_id and client_secret:
        auth_type = "oauth"
    elif username and password:
        auth_type = "basic"
    else:
        print_error(
            "Credentials required: --api-key, --client-id/--client-secret, "
            "or --username/--password"
        )
        raise typer.Exit(1)

    profile = JamaProfile(
        url=url,
        auth_type=auth_type,
        api_key=api_key,
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
    )

    config.profiles[name] = profile
    save_config(config)
    print_success(f"Added profile '{name}'")


@app.command("remove")
def remove_profile(
    name: Annotated[str, typer.Argument(help="Profile name to remove")],
) -> None:
    """Remove a profile."""
    config = load_config()

    if name not in config.profiles:
        print_error(f"Profile '{name}' not found")
        raise typer.Exit(1)

    del config.profiles[name]

    # Update default if needed
    if config.default_profile == name:
        config.default_profile = next(iter(config.profiles.keys()), "default")

    save_config(config)
    print_success(f"Removed profile '{name}'")


@app.command("set-default")
def set_default(
    name: Annotated[str, typer.Argument(help="Profile name to set as default")],
) -> None:
    """Set the default profile."""
    config = load_config()

    if name not in config.profiles:
        print_error(f"Profile '{name}' not found")
        raise typer.Exit(1)

    config.default_profile = name
    save_config(config)
    print_success(f"Default profile set to '{name}'")


@app.command("path")
def show_path() -> None:
    """Show the configuration file path."""
    config_path = get_config_path()
    exists = config_path.exists()

    console.print(f"Config file: {config_path}")
    console.print(f"Exists: {'Yes' if exists else 'No'}")
    console.print(f"Default location: {CONFIG_FILE}")


@app.command("cache")
def cache_info(
    clear: Annotated[
        bool,
        typer.Option("--clear", "-c", help="Clear the cache"),
    ] = False,
    show_files: Annotated[
        bool,
        typer.Option("--files", "-f", help="Show cached files on disk"),
    ] = False,
) -> None:
    """Show cache statistics or clear the cache.

    The CLI uses two cache layers:
    - Memory cache: Item types, pick lists (within session)
    - Disk cache: Project items, relationships (persists between runs)

    Examples:
        jama config cache              # Show cache stats
        jama config cache --clear      # Clear all caches
        jama config cache --files      # Show cached files
    """
    import json
    import time

    from jama_cli.config import get_profile_or_env
    from jama_cli.core.client import CACHE_DIR, JamaClient

    # Get profile to access the client
    profile = get_profile_or_env(None)
    if not profile:
        print_error("No profile configured. Run 'jama config init' to set up.")
        raise typer.Exit(1)

    client = JamaClient(profile)

    if clear:
        client.clear_cache()
        # Also clear disk cache directory
        if CACHE_DIR.exists():
            import shutil

            shutil.rmtree(CACHE_DIR, ignore_errors=True)
        print_success("All caches cleared (memory + disk)")
        return

    # Show cache statistics
    stats = client.get_cache_stats()

    # Memory cache stats
    console.print("\n[bold]Memory Cache[/bold] (session only)")
    mem_stats = stats.get("memory", {})
    table = Table()
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Entries", str(mem_stats.get("size", 0)))
    table.add_row("Hits", str(mem_stats.get("hits", 0)))
    table.add_row("Misses", str(mem_stats.get("misses", 0)))
    table.add_row("Hit Rate", f"{mem_stats.get('hit_rate', 0)}%")
    console.print(table)

    # Disk cache stats
    console.print("\n[bold]Disk Cache[/bold] (persists between runs)")
    disk_stats = stats.get("disk", {})
    if disk_stats:
        table2 = Table()
        table2.add_column("Metric")
        table2.add_column("Value")
        table2.add_row("Location", disk_stats.get("cache_dir", str(CACHE_DIR)))
        table2.add_row("Hits", str(disk_stats.get("hits", 0)))
        table2.add_row("Misses", str(disk_stats.get("misses", 0)))
        console.print(table2)

    # Count and show disk cache files
    if CACHE_DIR.exists():
        cache_files = list(CACHE_DIR.rglob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)
        console.print(f"  Files: {len(cache_files)}")
        console.print(f"  Size: {total_size / 1024:.1f} KB")

        if show_files and cache_files:
            console.print("\n[bold]Cached Files:[/bold]")
            file_table = Table()
            file_table.add_column("Type")
            file_table.add_column("Age")
            file_table.add_column("Expires")
            file_table.add_column("Size")

            for f in sorted(cache_files)[:20]:  # Limit to 20 files
                try:
                    with open(f) as fp:
                        data = json.load(fp)
                    key = data.get("key", "unknown")
                    created = data.get("created_at", 0)
                    expires = data.get("expires_at", 0)

                    # Parse key type
                    key_type = key.split(":")[0] if ":" in key else "unknown"

                    # Calculate age
                    age_sec = time.time() - created
                    if age_sec < 60:
                        age_str = f"{int(age_sec)}s ago"
                    elif age_sec < 3600:
                        age_str = f"{int(age_sec/60)}m ago"
                    else:
                        age_str = f"{int(age_sec/3600)}h ago"

                    # Time until expiry
                    ttl = expires - time.time()
                    if ttl < 0:
                        ttl_str = "[red]expired[/red]"
                    elif ttl < 60:
                        ttl_str = f"{int(ttl)}s"
                    elif ttl < 3600:
                        ttl_str = f"{int(ttl/60)}m"
                    else:
                        ttl_str = f"{int(ttl/3600)}h"

                    size_str = f"{f.stat().st_size / 1024:.1f} KB"

                    file_table.add_row(key_type, age_str, ttl_str, size_str)
                except Exception:
                    pass

            console.print(file_table)
            if len(cache_files) > 20:
                console.print(f"[dim]... and {len(cache_files) - 20} more files[/dim]")
    else:
        console.print("  [dim]No disk cache yet[/dim]")

    console.print(
        "\n[dim]Tip: Use --clear to clear caches, or --refresh on commands to bypass cache[/dim]"
    )
