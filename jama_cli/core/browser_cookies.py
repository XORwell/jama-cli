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

Only **Firefox** is supported. It keeps cookie values in clear text, so
everything happens by reading files; no Windows component, no decryption.
Jama's ``JSESSIONID`` and ``jama-csrf-token`` are *session* cookies (no expiry),
and Firefox never writes session cookies to ``cookies.sqlite``. While Firefox
runs they are only in its session store, ``sessionstore-backups/recovery.jsonlz4``
(rewritten about every 15 seconds; ``sessionstore.jsonlz4`` after a shutdown with
session restore). Both places are read: ``cookies.sqlite`` first, the session
store for whatever is still missing. Only cookies of the default context are
used, never those of private windows, containers or partitioned storage.

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
import json
import os
import shutil
import sqlite3
import subprocess
import sys
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

# Firefox session store files that may hold session cookies, relative to the
# profile directory. The newest readable one wins.
_SESSION_STORE_FILES = (
    "sessionstore-backups/recovery.jsonlz4",
    "sessionstore-backups/recovery.baklz4",
    "sessionstore.jsonlz4",
)
_MOZLZ4_MAGIC = b"mozLz40\0"


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
            "sign in first, then try again. Firefox saves session cookies about every "
            "15 seconds, so right after signing in wait a moment."
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


# Where WSL mounts the Windows system drive; the other drives are its siblings.
WSL_WINDOWS_DRIVE = Path("/mnt/c")
# A Windows user's Firefox directory, relative to the user's home.
WINDOWS_FIREFOX_DIR = "AppData/Roaming/Mozilla/Firefox"


def _windows_userprofile() -> str | None:
    """``%USERPROFILE%`` as Windows reports it, e.g. ``C:\\Users\\me``.

    ``cmd.exe`` is tried from ``PATH`` first and then by its absolute path, because
    WSL leaves the Windows directories off ``PATH`` with ``appendWindowsPath=false``
    and an MCP client may start the server with a reduced environment.
    """
    executables = ("cmd.exe", str(WSL_WINDOWS_DRIVE / "Windows/System32/cmd.exe"))
    cwd = str(WSL_WINDOWS_DRIVE) if WSL_WINDOWS_DRIVE.is_dir() else None
    for executable in executables:
        try:
            out = subprocess.run(
                [executable, "/c", "echo %USERPROFILE%"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=cwd,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        profile = out.stdout.strip()
        if profile and "%USERPROFILE%" not in profile and profile[1:3] == ":\\":
            return profile
    return None


def _only_windows_user_with_firefox() -> Path | None:
    """The one Windows user home under ``/mnt/c/Users`` that has a Firefox profile.

    Used when Windows programs cannot be started from WSL at all (interop off).
    With several such users there is no safe choice, so None is returned rather
    than reading another user's session.
    """
    homes: list[Path] = []
    try:
        entries = list((WSL_WINDOWS_DRIVE / "Users").iterdir())
    except OSError:
        return None
    for entry in entries:
        try:
            if (entry / WINDOWS_FIREFOX_DIR / "profiles.ini").is_file():
                homes.append(entry)
        except OSError:
            continue
    return homes[0] if len(homes) == 1 else None


def windows_user_home() -> Path | None:
    """The Windows user's home as a WSL path (``/mnt/c/Users/<user>``), if found.

    The Windows user name need not match the WSL one, so it is asked of Windows
    (``cmd.exe``) rather than guessed. Only if Windows cannot be asked, the single
    Windows user with a Firefox profile is used.
    """
    profile = _windows_userprofile()
    if profile:
        drive = profile[0].lower()
        rest = profile[3:].replace("\\", "/")
        path = WSL_WINDOWS_DRIVE.parent / drive / rest
        if path.exists():
            return path
    home = _only_windows_user_with_firefox()
    if home is not None:
        logger.debug(
            "Windows could not be asked for the user profile; using the only one with Firefox"
        )
    return home


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


def firefox_root_candidates() -> list[Path]:
    """Directories that may hold a Firefox ``profiles.ini`` on this machine, in order.

    Under WSL the Windows host's Firefox comes first, then a Firefox inside WSL.
    On Linux the classic, XDG, Snap and Flatpak locations are all considered.
    """
    roots: list[Path] = []
    if in_wsl():
        home = windows_user_home()
        if home is not None:
            roots.append(home / WINDOWS_FIREFOX_DIR)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData/Roaming"
        roots.append(base / "Mozilla/Firefox")
    elif sys.platform == "darwin":
        roots.append(Path.home() / "Library/Application Support/Firefox")
    else:
        home = Path.home()
        roots += [
            home / ".mozilla/firefox",
            home / ".config/mozilla/firefox",
            home / "snap/firefox/common/.mozilla/firefox",
            home / ".var/app/org.mozilla.firefox/.mozilla/firefox",
        ]
    return roots


def firefox_profile_roots() -> list[Path]:
    """The candidate directories that actually contain a ``profiles.ini``."""
    return [root for root in firefox_root_candidates() if (root / "profiles.ini").is_file()]


def _profile_freshness(profile_dir: Path) -> float:
    """Newest modification time of the files the Jama cookies are read from."""
    names = ("cookies.sqlite", "cookies.sqlite-wal", *_SESSION_STORE_FILES)
    times = [p.stat().st_mtime for p in (profile_dir / n for n in names) if p.is_file()]
    return max(times, default=0.0)


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


def lz4_block_decompress(src: bytes) -> bytes:
    """Decompress one raw LZ4 block (the payload of Firefox's ``mozLz4`` files)."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        length = token >> 4
        if length == 15:
            while True:
                extra = src[i]
                i += 1
                length += extra
                if extra != 255:
                    break
        out += src[i : i + length]
        i += length
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(out):
            raise ValueError("corrupt LZ4 block")
        length = (token & 15) + 4
        if (token & 15) == 15:
            while True:
                extra = src[i]
                i += 1
                length += extra
                if extra != 255:
                    break
        start = len(out) - offset
        if length <= offset:
            out += out[start : start + length]
        else:
            # Overlapping match: the copied bytes repeat with period ``offset``.
            chunk = bytes(out[start:])
            out += (chunk * (length // offset + 1))[:length]
    return bytes(out)


def read_mozlz4(path: Path) -> Any:
    """Parse a Firefox ``.jsonlz4`` / ``.baklz4`` file into JSON."""
    raw = path.read_bytes()
    if raw[:8] != _MOZLZ4_MAGIC or len(raw) < 12:
        raise ValueError("not a mozLz4 file")
    size = int.from_bytes(raw[8:12], "little")
    data = lz4_block_decompress(raw[12:])
    if len(data) != size:
        raise ValueError("mozLz4 size mismatch")
    return json.loads(data)


def _is_default_context(attributes: Any) -> bool:
    """True for cookies outside private windows, containers and partitioned storage."""
    if isinstance(attributes, str):  # cookies.sqlite: "" or "^userContextId=1&..."
        return attributes == ""
    if isinstance(attributes, dict):  # session store: {} or {"userContextId": 1, ...}
        return not any(
            attributes.get(key) for key in ("userContextId", "privateBrowsingId", "partitionKey")
        )
    return attributes is None


def _session_store_values(profile_dir: Path, host: str) -> dict[str, str]:
    """Jama session cookies from the newest readable Firefox session store file."""
    candidates = [profile_dir / rel for rel in _SESSION_STORE_FILES]
    existing = sorted(
        (path for path in candidates if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in existing:
        try:
            data = read_mozlz4(path)
        except (OSError, ValueError) as e:
            logger.debug(f"Skipping Firefox session store {path.name} ({type(e).__name__})")
            continue
        values: dict[str, str] = {}
        for cookie in data.get("cookies", []) if isinstance(data, dict) else []:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            if (
                name in _WANTED
                and cookie.get("value")
                and host_matches(str(cookie.get("host", "")), host)
                and _is_default_context(cookie.get("originAttributes"))
            ):
                values[name] = str(cookie["value"])
        logger.debug(f"Read the Firefox session store {path.name}")
        return values
    return {}


def read_firefox(base_url: str, cookies_db: Path) -> StoredSession:
    """Read the Jama session cookies from a Firefox profile.

    ``cookies.sqlite`` holds persistent cookies only; Jama's session cookies are
    taken from the session store next to it.
    """
    host = _jama_host(base_url)
    tmp_dir, copy = _copy_locked_db(cookies_db)
    try:
        rows = _read_rows(copy, "SELECT name, value, host, originAttributes FROM moz_cookies")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    values: dict[str, str] = {}
    for name, value, cookie_host, attributes in rows:
        if (
            name in _WANTED
            and value
            and host_matches(cookie_host or "", host)
            and _is_default_context(attributes)
        ):
            values[name] = value
    if any(not values.get(name) for name in _WANTED):
        for name, value in _session_store_values(cookies_db.parent, host).items():
            values.setdefault(name, value)
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
        return read_firefox(base_url, cookies_path)

    roots = [cookies_path] if cookies_path else firefox_profile_roots()
    if not roots:
        searched = ", ".join(str(root) for root in firefox_root_candidates()) or "-"
        raise BrowserCookieError(
            f"No Firefox profile found (looked in: {searched}). Open Firefox once, or pass "
            "--browser-cookies-path (a cookies.sqlite or the directory with profiles.ini)."
        )

    dbs: list[Path] = []
    last_error: BrowserCookieError | None = None
    for root in roots:
        try:
            dbs.append(_find_firefox_cookie_db(root, profile))
        except BrowserCookieError as e:
            last_error = e
    # Several Firefox installs (e.g. Windows and WSL): the most recently used one first.
    dbs.sort(key=lambda db: _profile_freshness(db.parent), reverse=True)
    for db in dbs:
        try:
            return read_firefox(base_url, db)
        except BrowserCookieError as e:
            last_error = e
    assert last_error is not None
    raise last_error
