"""On-disk store for Jama web sessions, shared across processes.

One file per ``(base_url, account)``. Every process that talks to the same
Jama account reads and writes the same file, so a login done by one process is
picked up by all others instead of each one logging in on its own.

The file holds secrets (session cookies, CSRF token). It is written atomically
with mode 0600 and is never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from jama_cli.core.exceptions import CoreException

SESSION_COOKIE = "JSESSIONID"
CSRF_COOKIE = "jama-csrf-token"

# Where a stored session came from. A browser-sourced session *is* the user's
# browser session, so it must not be ended on the server by a plain logout.
SOURCE_LOGIN = "login"  # this tool's own browser (Playwright) login
SOURCE_FORM = "form"  # this tool's native form login
SOURCE_BROWSER_PREFIX = "browser-"  # e.g. "browser-firefox": read from the user's browser

# How often a waiting process re-checks the lock.
_LOCK_POLL_SECONDS = 0.1


def default_session_dir() -> Path:
    """Directory that holds session files.

    ``JAMA_SESSION_DIR`` wins; otherwise sessions live next to the existing
    config file in ``~/.jama`` (the directory this tool already uses on every
    platform).
    """
    env_dir = os.environ.get("JAMA_SESSION_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".jama" / "sessions"


def session_key(base_url: str, account: str | None) -> str:
    """Stable, non-reversible file name stem for a ``(base_url, account)`` pair."""
    raw = f"{base_url.rstrip('/').lower()}|{(account or '').lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def default_session_file(base_url: str, account: str | None) -> Path:
    """Default store location for a ``(base_url, account)`` pair."""
    return default_session_dir() / f"{session_key(base_url, account)}.json"


@dataclass
class StoredSession:
    """A captured Jama web session.

    ``repr`` deliberately leaves out cookie and token values so that a session
    can never leak through a log line or an exception message.
    """

    base_url: str
    username: str | None = None
    cookies: list[dict[str, str]] = field(default_factory=list, repr=False)
    csrf_token: str = field(default="", repr=False)
    created_at: float = 0.0
    last_validated_at: float = 0.0
    source: str = SOURCE_LOGIN

    @property
    def from_browser(self) -> bool:
        """True if the session was taken over from the user's own browser."""
        return self.source.startswith(SOURCE_BROWSER_PREFIX)

    def cookie_header(self) -> str:
        """Value for the ``Cookie`` request header."""
        return "; ".join(f"{c['name']}={c['value']}" for c in self.cookies)

    def auth_headers(self) -> dict[str, str]:
        """Headers that authenticate a request with this session."""
        return {"Cookie": self.cookie_header(), CSRF_COOKIE: self.csrf_token}

    def cookie_value(self, name: str) -> str | None:
        """Value of the first cookie with this name, if any."""
        for cookie in self.cookies:
            if cookie["name"] == name:
                return cookie["value"]
        return None

    def set_cookie(self, name: str, value: str, domain: str = "", path: str = "/") -> bool:
        """Add or update a cookie. Returns True if anything changed."""
        for cookie in self.cookies:
            if cookie["name"] == name:
                if cookie["value"] == value:
                    return False
                cookie["value"] = value
                return True
        self.cookies.append({"name": name, "value": value, "domain": domain, "path": path})
        return True

    def set_csrf(self, token: str) -> bool:
        """Update the CSRF token in both the header value and the cookie."""
        changed = self.csrf_token != token
        self.csrf_token = token
        return self.set_cookie(CSRF_COOKIE, token) or changed

    def adopt_cookie_csrf(self, sent_token: str | None) -> bool:
        """Make the header token follow the ``jama-csrf-token`` cookie.

        Returns True if the cookie holds a token that differs from
        ``sent_token`` (default: the current header token), i.e. if sending the
        request again can have a different outcome.
        """
        cookie_token = self.cookie_value(CSRF_COOKIE)
        reference = self.csrf_token if sent_token is None else sent_token
        if not cookie_token or cookie_token == reference:
            return False
        self.csrf_token = cookie_token
        return True

    def same_as(self, other: StoredSession | None) -> bool:
        """True if both objects describe the same server-side session state."""
        if other is None:
            return False
        mine = sorted((c["name"], c["value"]) for c in self.cookies)
        theirs = sorted((c["name"], c["value"]) for c in other.cookies)
        return mine == theirs and self.csrf_token == other.csrf_token

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "username": self.username,
            "cookies": [
                {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ""),
                    "path": c.get("path", "/"),
                }
                for c in self.cookies
            ],
            "csrf_token": self.csrf_token,
            "created_at": self.created_at,
            "last_validated_at": self.last_validated_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredSession:
        return cls(
            base_url=str(data["base_url"]),
            username=data.get("username"),
            cookies=[
                {
                    "name": str(c["name"]),
                    "value": str(c["value"]),
                    "domain": str(c.get("domain", "")),
                    "path": str(c.get("path", "/")),
                }
                for c in data.get("cookies", [])
            ],
            csrf_token=str(data.get("csrf_token", "")),
            created_at=float(data.get("created_at", 0.0)),
            last_validated_at=float(data.get("last_validated_at", 0.0)),
            # Files written before the key existed came from this tool's own login.
            source=str(data.get("source") or SOURCE_LOGIN),
        )


def _restrict_to_user(path: Path) -> None:
    """Make a file readable and writable by the current user only."""
    if sys.platform == "win32":
        user = os.environ.get("USERNAME")
        if not user:
            return
        # Drop inherited ACEs and grant full control to the current user only.
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                check=False,
                capture_output=True,
                timeout=10,
            )
    else:
        os.chmod(path, 0o600)


class SessionStore:
    """Reads and writes one session file, guarded by a cross-process lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = FileLock(str(path) + ".lock")

    def load(self) -> StoredSession | None:
        """Read the stored session. Missing or unreadable files yield None."""
        try:
            with open(self.path, encoding="utf-8") as f:
                return StoredSession.from_dict(json.load(f))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            # Corrupt or foreign file: treat as "no session", never echo its content.
            return None

    def save(self, session: StoredSession) -> None:
        """Atomically write the session (temp file in the same directory + rename)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            with contextlib.suppress(OSError):
                os.chmod(self.path.parent, 0o700)

        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".session-", suffix=".tmp")
        tmp_path = Path(tmp_name)
        try:
            # mkstemp creates the file with mode 0600 on POSIX.
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f)
                f.flush()
                os.fsync(f.fileno())
            _restrict_to_user(tmp_path)
            os.replace(tmp_path, self.path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    def delete(self) -> None:
        """Remove the stored session."""
        self.path.unlink(missing_ok=True)

    @contextlib.asynccontextmanager
    async def locked(self, timeout: float) -> AsyncIterator[None]:
        """Hold the cross-process lock without blocking the event loop.

        The lock is polled rather than acquired in a worker thread, so it is
        taken and released on the same thread and other coroutines keep running
        while this one waits (for example for another process's login).
        """
        deadline = time.monotonic() + timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._lock.acquire(timeout=0)
                break
            except Timeout:
                if time.monotonic() >= deadline:
                    raise CoreException(
                        "Timed out waiting for the Jama session lock; "
                        "another process may be logging in."
                    ) from None
                await asyncio.sleep(_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            self._lock.release()
