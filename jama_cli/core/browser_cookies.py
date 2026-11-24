"""Reuse the Jama web session the user's own Firefox already holds.

``auth_type: session`` normally logs in through its own Playwright profile, which
is a *second* session. On an instance that allows only one session per account,
that second login evicts the user's real browser session (and vice versa), so the
user and the MCP server cannot work at the same time. This module avoids that: it
reads the two Jama cookies Firefox already has and reuses them, so browser, CLI
and MCP server share one session.

Only the two cookies ``JSESSIONID`` and ``jama-csrf-token``, and only for the
configured Jama host, are ever read. Their values are never logged or put into an
exception message.

Runtime target: CLI/MCP under Linux (WSL2), browser on the Windows host. The
Windows file tree is reachable from WSL under ``/mnt/c/...``.

Only **Firefox** is supported. It keeps cookie values in clear text
(``cookies.sqlite`` → ``moz_cookies``), so everything happens by reading a file;
no Windows component, no decryption.

Chrome and Edge are deliberately **not** supported. Since version 127 they bind
the cookie key to the Windows user (App-Bound Encryption), and unwrapping it from
outside the browser is exactly what credential-stealing malware does. A tool that
did so would be flagged by endpoint security on a managed machine, so asking for
Chrome/Edge fails fast with a clear message instead.

The locked live cookie database is never opened in place: it is copied (together
with its ``-wal``/``-shm`` sidecars) to a temporary file, opened read-only, and
the copy is deleted afterwards.
"""

from __future__ import annotations

import configparser
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from loguru import logger

from jama_cli.core.exceptions import CoreException
from jama_cli.core.session_store import CSRF_COOKIE, SESSION_COOKIE, StoredSession

# The cookies that make up a Jama web session. Nothing else is read.
_WANTED = (SESSION_COOKIE, CSRF_COOKIE)

# Browser sources, as used in ``session_source`` and ``jama login --from-browser``.
FIREFOX = "firefox"
BROWSERS = (FIREFOX,)

# Chromium-family names people will try; they get a specific explanation.
_CHROMIUM_NAMES = ("chrome", "edge", "msedge", "chromium", "brave")

CHROMIUM_UNSUPPORTED = (
    "Reading Chrome/Edge cookies is not supported (App-Bound Encryption). "
    "Use --from-browser firefox, or `jama login`."
)


class BrowserCookieError(CoreException):
    """The Jama session could not be read from the browser's cookie store."""


def normalise_source(value: str | None) -> str | None:
    """Map a ``session_source`` value to a browser name, or None for the default.

    Accepts ``firefox`` / ``browser-firefox``; ``login`` or an empty value means
    "log in as before". Chrome and Edge are rejected with an explanation, and
    there is no fallback to a fresh login.
    """
    if not value:
        return None
    name = value.strip().lower()
    name = name[len("browser-") :] if name.startswith("browser-") else name
    if name in ("", "login", "playwright"):
        return None
    if name in _CHROMIUM_NAMES:
        raise BrowserCookieError(CHROMIUM_UNSUPPORTED)
    if name not in BROWSERS:
        raise BrowserCookieError(
            f"Unknown browser source '{value}'. Only 'firefox' is supported "
            "(or leave it unset to log in with `jama login`)."
        )
    return name


def host_matches(cookie_host: str, jama_host: str) -> bool:
    """True if a cookie's host applies to the Jama host.

    Matches an exact host or a dot-prefixed domain cookie (``.example.com``).
    """
    cookie_host = cookie_host.lstrip(".").lower()
    jama_host = jama_host.lower()
    return jama_host == cookie_host or jama_host.endswith("." + cookie_host)


def _jama_host(base_url: str) -> str:
    host = urlsplit(base_url).hostname
    if not host:
        raise BrowserCookieError(f"Could not read a host name from the Jama URL '{base_url}'.")
    return host


def _build_session(base_url: str, values: dict[str, str]) -> StoredSession:
    """Turn the two cookie values into a StoredSession for the configured host."""
    missing = [name for name in _WANTED if not values.get(name)]
    if missing:
        raise BrowserCookieError(
            "The browser has no current Jama session for this host "
            f"(missing cookie: {', '.join(missing)}). Open the Jama site in the browser and "
            "sign in first, then try again."
        )
    host = _jama_host(base_url)
    session = StoredSession(base_url=base_url.rstrip("/"), created_at=time.time())
    for name in _WANTED:
        session.set_cookie(name, values[name], domain=host, path="/")
    session.csrf_token = values[CSRF_COOKIE]
    return session


# ---------------------------------------------------------------------------
# WSL / Windows paths
# ---------------------------------------------------------------------------


def in_wsl() -> bool:
    """Best-effort detection of WSL (so Windows cookie stores are reachable)."""
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False


def windows_user_home() -> Path | None:
    """The Windows user's home as a WSL path (``/mnt/c/Users/<user>``), if found.

    The Windows user name need not match the WSL one, so it is asked of Windows
    (``cmd.exe``) rather than guessed.
    """
    try:
        out = subprocess.run(
            ["cmd.exe", "/c", "echo %USERPROFILE%"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd="/mnt/c",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    profile = out.stdout.strip()
    if not profile or "%USERPROFILE%" in profile or profile[1:3] != ":\\":
        return None
    drive = profile[0].lower()
    rest = profile[3:].replace("\\", "/")
    path = Path(f"/mnt/{drive}/{rest}")
    return path if path.exists() else None


def _copy_locked_db(db_path: Path) -> tuple[Path, Path]:
    """Copy a (possibly locked) SQLite db plus its WAL/SHM sidecars to a temp dir.

    Returns the temp directory (to delete afterwards) and the copied db path.
    """
    if not db_path.exists():
        raise BrowserCookieError(f"Browser cookie database not found at {db_path}.")
    tmp_dir = Path(tempfile.mkdtemp(prefix="jama-cookies-"))
    target = tmp_dir / db_path.name
    try:
        for suffix in ("", "-wal", "-shm"):
            src = db_path.parent / (db_path.name + suffix)
            if src.exists():
                shutil.copy2(src, tmp_dir / src.name)
    except OSError as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise BrowserCookieError(
            f"Could not read the browser cookie database ({type(e).__name__}). "
            "Close the browser or check the path."
        ) from e
    return tmp_dir, target


def _read_rows(db_path: Path, query: str) -> list[tuple[Any, ...]]:
    """Open a copied SQLite db read-only and run one query."""
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            return list(conn.execute(query))
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise BrowserCookieError(
            f"Could not read the browser cookie database ({type(e).__name__})."
        ) from e


# ---------------------------------------------------------------------------
# Firefox (plain text, read entirely from WSL)
# ---------------------------------------------------------------------------


def firefox_profiles_dir(override_home: Path | None = None) -> Path:
    """Firefox profiles directory, on the Windows host when running under WSL."""
    if override_home is not None:
        return override_home
    if in_wsl():
        home = windows_user_home()
        if home is None:
            raise BrowserCookieError(
                "Could not locate the Windows user profile from WSL. Pass the cookies path "
                "explicitly (browser_cookies_path / --browser-cookies-path)."
            )
        return home / "AppData/Roaming/Mozilla/Firefox"
    return Path.home() / ".mozilla/firefox"


def _find_firefox_cookie_db(profiles_root: Path, profile_name: str | None) -> Path:
    """Pick a Firefox profile's cookies.sqlite via profiles.ini (or a named profile)."""
    if profile_name:
        db = profiles_root / "Profiles" / profile_name / "cookies.sqlite"
        if db.exists():
            return db
        db = profiles_root / profile_name / "cookies.sqlite"
        if db.exists():
            return db
        raise BrowserCookieError(f"Firefox profile '{profile_name}' has no cookies.sqlite.")

    ini = profiles_root / "profiles.ini"
    if not ini.exists():
        raise BrowserCookieError(
            f"No Firefox profiles.ini under {profiles_root}. Pass --browser-cookies-path."
        )
    parser = configparser.ConfigParser()
    parser.read(ini)

    # Prefer an [Install...] section's Default, then a profile marked Default=1 or
    # a ``*.default-release``, then any remaining profile.
    preferred: list[str] = []
    rest: list[str] = []
    for section in parser.sections():
        if section.startswith("Install") and parser.has_option(section, "Default"):
            preferred.append(parser.get(section, "Default"))
    for section in parser.sections():
        if not parser.has_option(section, "Path"):
            continue
        path = parser.get(section, "Path")
        is_default = parser.get(section, "Default", fallback="0") == "1"
        if is_default or path.endswith(".default-release"):
            preferred.append(path)
        else:
            rest.append(path)

    candidates = preferred + rest
    seen: set[str] = set()
    for rel in candidates:
        if rel in seen:
            continue
        seen.add(rel)
        db = (profiles_root / rel) / "cookies.sqlite"
        if db.exists():
            return db
    raise BrowserCookieError(
        f"No cookies.sqlite found via {ini}. Open Firefox once, or pass --browser-cookies-path."
    )


def read_firefox(base_url: str, cookies_db: Path) -> StoredSession:
    """Read the Jama session cookies from a Firefox cookies.sqlite (clear text)."""
    host = _jama_host(base_url)
    tmp_dir, copy = _copy_locked_db(cookies_db)
    try:
        rows = _read_rows(copy, "SELECT name, value, host FROM moz_cookies")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    values: dict[str, str] = {}
    for name, value, cookie_host in rows:
        if name in _WANTED and host_matches(cookie_host or "", host):
            values[name] = value or ""
    return _build_session(base_url, values)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def read_browser_session(
    base_url: str,
    browser: str,
    profile: str | None = None,
    cookies_path: Path | None = None,
) -> StoredSession:
    """Read the current Jama web session from the user's Firefox.

    ``cookies_path`` overrides auto-detection: the path to a ``cookies.sqlite``,
    or to the Firefox directory that holds ``profiles.ini``.
    """
    # Validates the name; Chrome/Edge and unknown names raise here.
    name = normalise_source(browser)
    if name != FIREFOX:
        raise BrowserCookieError(
            "No browser source given. Use --from-browser firefox, or `jama login`."
        )
    logger.debug("Reading the Jama session from Firefox")

    if cookies_path and cookies_path.is_file():
        db = cookies_path
    else:
        root = firefox_profiles_dir(cookies_path if cookies_path else None)
        db = _find_firefox_cookie_db(root, profile)
    return read_firefox(base_url, db)
