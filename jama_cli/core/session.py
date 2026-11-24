"""Browser-session ("SSO cookie") authentication for the Jama REST API.

A Jama web session is the cookie pair ``JSESSIONID`` + ``jama-csrf-token``.
REST calls under ``<base>/rest/v1/`` accept it when the cookies are sent along
with a ``jama-csrf-token`` header. This module holds everything that does not
need a browser: the settings, the authenticated probe, the native form login,
logout, and :class:`SessionManager`, which keeps one session per account in a
store shared by all processes.

Nothing in here logs or raises cookie values, CSRF tokens or passwords.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from loguru import logger

from jama_cli.core.exceptions import CoreException, UnauthorizedException
from jama_cli.core.session_store import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    SessionStore,
    StoredSession,
    default_session_dir,
    default_session_file,
)

DEFAULT_SSO_SELECTORS: tuple[str, ...] = ("#loginWithSSOButton", 'input[name="submitWithSSO"]')
DEFAULT_LOGIN_TIMEOUT = 300.0
LOGIN_HINT = "No valid Jama session. Run `jama login` to sign in."

# A redirect to one of these means "you are not logged in".
_LOGIN_REDIRECT_MARKERS = ("/login", "/saml", "j_acegi")

LoginFunc = Callable[["SessionSettings", str], Awaitable[StoredSession]]


@dataclass
class SessionSettings:
    """Everything needed to obtain and reuse a Jama web session."""

    base_url: str
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    login_mode: str = "browser"  # browser | form
    login_timeout: float = DEFAULT_LOGIN_TIMEOUT
    login_interactive: str = "auto"  # auto | always | never
    browser_channel: str | None = None
    browser_profile_dir: Path | None = None
    sso_selectors: tuple[str, ...] = DEFAULT_SSO_SELECTORS
    debug_dir: Path | None = None
    session_file: Path | None = None
    keepalive_minutes: float = 0.0
    # Reuse the session from the user's own browser instead of logging in again.
    # None | "firefox" | "chrome" | "edge" (also accepts a "browser-" prefix).
    session_source: str | None = None
    browser_cookie_profile: str | None = None
    browser_cookies_path: Path | None = None

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    @property
    def store_path(self) -> Path:
        """Session file for this ``(base_url, account)``."""
        return self.session_file or default_session_file(self.base_url, self.username)

    @property
    def profile_dir(self) -> Path:
        """Persistent browser profile directory (keeps the IdP's "remember me")."""
        if self.browser_profile_dir:
            return self.browser_profile_dir
        return default_session_dir().parent / "browser-profile"


@dataclass
class ProbeResult:
    """Outcome of the authenticated probe."""

    ok: bool
    username: str | None = None
    status_code: int | None = None


def response_message(response: httpx.Response) -> str:
    """Extract ``meta.message`` from a Jama error envelope, if present."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    meta = body.get("meta")
    message = meta.get("message") if isinstance(meta, dict) else None
    return message if isinstance(message, str) else ""


def is_session_rejected(response: httpx.Response) -> bool:
    """True if the response means the web session is dead or not accepted.

    - 3xx whose ``Location`` points at the login/SAML machinery, or
    - 401 with an empty or generic message.

    A 401 whose message mentions "permission" is a missing permission on a
    perfectly valid session and must never trigger a re-login.
    """
    code = response.status_code
    if 300 <= code < 400:
        location = response.headers.get("Location", "").lower()
        return any(marker in location for marker in _LOGIN_REDIRECT_MARKERS)
    if code == 401:
        return "permission" not in response_message(response).lower()
    return False


def merge_response_cookies(session: StoredSession, response: httpx.Response) -> bool:
    """Fold ``Set-Cookie`` headers of a response into the session.

    Returns True if the session changed. A new ``jama-csrf-token`` cookie also
    updates the header value, since Jama compares the two.
    """
    changed = False
    for cookie in response.cookies.jar:
        if cookie.value is None:
            continue
        if cookie.name == CSRF_COOKIE:
            changed = session.set_csrf(cookie.value) or changed
        else:
            changed = (
                session.set_cookie(cookie.name, cookie.value, cookie.domain, cookie.path) or changed
            )
    return changed


def _new_client(
    transport: httpx.AsyncBaseTransport | None, timeout: float = 30.0
) -> httpx.AsyncClient:
    """Plain client for login/probe/logout calls: no cookie reuse, manual redirects."""
    return httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False)


async def probe(
    base_url: str,
    session: StoredSession,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProbeResult:
    """Check whether a session is really authenticated.

    Jama hands out a ``JSESSIONID`` to anyone who opens the login page, so the
    presence of cookies proves nothing. The only proof is an authenticated REST
    call: ``users/current`` (which also tells us who we are), falling back to
    ``projects?maxResults=1`` on instances where that endpoint is unavailable.
    """
    api = f"{base_url.rstrip('/')}/rest/v1/"
    headers = {"Accept": "application/json", **session.auth_headers()}
    async with _new_client(transport) as client:
        try:
            response = await client.get(api + "users/current", headers=headers)
            if response.status_code == 200:
                merge_response_cookies(session, response)
                username = None
                try:
                    data = response.json().get("data", {})
                    username = data.get("username") if isinstance(data, dict) else None
                except (ValueError, AttributeError):
                    pass
                return ProbeResult(True, username, 200)
            if is_session_rejected(response):
                return ProbeResult(False, None, response.status_code)

            response = await client.get(api + "projects", params={"maxResults": 1}, headers=headers)
            if response.status_code == 200:
                merge_response_cookies(session, response)
                return ProbeResult(True, None, 200)
            return ProbeResult(False, None, response.status_code)
        except httpx.HTTPError as e:
            raise CoreException(f"Could not reach Jama at {base_url}: {type(e).__name__}") from e


def _jar_to_cookies(jar: httpx.Cookies) -> list[dict[str, str]]:
    return [
        {"name": c.name, "value": c.value or "", "domain": c.domain, "path": c.path}
        for c in jar.jar
    ]


async def form_login(
    settings: SessionSettings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> StoredSession:
    """Native Jama login without a browser (non-SSO instances, service accounts)."""
    if not settings.username or not settings.password:
        raise UnauthorizedException(
            "Form login needs a username and password "
            "(JAMA_USERNAME / JAMA_PASSWORD or the profile)."
        )

    base = settings.base_url
    async with _new_client(transport) as client:
        try:
            # 1. Visit the login page to collect the (still unauthenticated) cookies.
            await client.get(f"{base}/login")
            csrf = client.cookies.get(CSRF_COOKIE, default="") or ""

            # 2. Submit the credentials.
            response = await client.post(
                f"{base}/j_acegi_security_check",
                data={
                    "j_username": settings.username,
                    "j_password": settings.password,
                    "j_hash": "",
                },
                headers={CSRF_COOKIE: csrf},
            )
            location = response.headers.get("Location", "")
            if "login_error" in location:
                raise UnauthorizedException("Jama rejected the username or password.")

            # 3. Follow the redirect once; it may set further cookies.
            if location:
                await client.get(urljoin(f"{base}/", location))
        except httpx.HTTPError as e:
            raise CoreException(f"Jama login request failed: {type(e).__name__}") from e

        cookies = _jar_to_cookies(client.cookies)

    now = time.time()
    session = StoredSession(base_url=base, cookies=cookies, created_at=now)
    session.csrf_token = session.cookie_value(CSRF_COOKIE) or ""

    # 4. Cookies prove nothing: only the authenticated probe counts.
    result = await probe(base, session, transport)
    if not result.ok:
        raise UnauthorizedException(
            "Jama login did not produce an authenticated session. "
            "If this instance uses SSO, use the browser login mode."
        )
    session.username = result.username or settings.username
    session.last_validated_at = time.time()
    return session


async def end_session(
    base_url: str,
    session: StoredSession,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Log out on the server so the license seat is released.

    The CSRF header is required: without it Jama answers 200 and keeps the
    session alive.
    """
    async with _new_client(transport) as client:
        try:
            await client.get(f"{base_url.rstrip('/')}/logout.req", headers=session.auth_headers())
        except httpx.HTTPError as e:
            raise CoreException(f"Jama logout request failed: {type(e).__name__}") from e


async def browser_cookie_login(
    settings: SessionSettings,
    browser: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> StoredSession:
    """Reuse the Jama session the user's own browser holds (no second login).

    Reads only ``JSESSIONID`` and ``jama-csrf-token`` for the configured host,
    validates them with the authenticated probe, and returns the session. This
    is non-interactive, so it works under ``login_interactive: never``.
    """
    # Imported here so the dependency is only touched for this mode.
    from jama_cli.core.browser_cookies import read_browser_session

    session = read_browser_session(
        settings.base_url,
        browser,
        profile=settings.browser_cookie_profile,
        cookies_path=settings.browser_cookies_path,
    )
    result = await probe(settings.base_url, session, transport)
    if not result.ok:
        raise UnauthorizedException(
            f"The Jama session found in {browser} is not valid. Sign in to Jama in the browser "
            "first; if you just signed out, that session is gone on purpose."
        )
    session.username = result.username
    session.last_validated_at = time.time()
    logger.info(f"Reused the Jama session from {browser}")
    return session


async def _default_login(settings: SessionSettings, interactive: str) -> StoredSession:
    """Obtain a fresh session according to the login mode and interactivity."""
    from jama_cli.core.browser_cookies import normalise_source

    browser = normalise_source(settings.session_source)
    if browser is not None:
        # Non-interactive: read the browser's existing session, even with "never".
        return await browser_cookie_login(settings, browser)

    if settings.login_mode == "form":
        return await form_login(settings)
    if interactive == "never":
        raise UnauthorizedException(LOGIN_HINT)

    # Imported lazily: Playwright is an optional extra.
    from jama_cli.core.browser_login import browser_login

    return await browser_login(settings, silent_first=interactive != "always")


class SessionManager:
    """Keeps the current session for one account and repairs it when it dies.

    The session lives in a :class:`SessionStore` shared by every process using
    the same account. Jama allows only one live session per account, so the rule
    is: before logging in, always look whether somebody else already did.
    """

    def __init__(
        self,
        settings: SessionSettings,
        transport: httpx.AsyncBaseTransport | None = None,
        login_func: LoginFunc | None = None,
    ) -> None:
        self.settings = settings
        self.store = SessionStore(settings.store_path)
        self._transport = transport
        self._session: StoredSession | None = None
        self._loaded = False
        # Serialises recovery between coroutines of this process; the file lock
        # serialises it between processes.
        self._recover_lock = asyncio.Lock()
        if login_func is not None:
            self._login_func: LoginFunc = login_func
        elif transport is not None:
            self._login_func = self._login_with_transport
        else:
            self._login_func = _default_login

    async def _login_with_transport(
        self, settings: SessionSettings, interactive: str
    ) -> StoredSession:
        from jama_cli.core.browser_cookies import normalise_source

        browser = normalise_source(settings.session_source)
        if browser is not None:
            return await browser_cookie_login(settings, browser, self._transport)
        if settings.login_mode == "form":
            return await form_login(settings, self._transport)
        return await _default_login(settings, interactive)

    @property
    def _lock_timeout(self) -> float:
        # Long enough to sit out another process's interactive login.
        return self.settings.login_timeout + 60.0

    def current(self) -> StoredSession | None:
        """The session in use, loaded lazily from the store on first access."""
        if not self._loaded:
            self._session = self.store.load()
            self._loaded = True
        return self._session

    async def persist(self) -> None:
        """Write the in-memory session back to the shared store."""
        if self._session is None:
            return
        async with self.store.locked(self._lock_timeout):
            self.store.save(self._session)

    def adopt_newer(self, dead: StoredSession | None) -> StoredSession | None:
        """Re-read the store; adopt and return its session if it differs from ``dead``."""
        stored = self.store.load()
        if stored is None or stored.same_as(dead):
            return None
        self._session = stored
        self._loaded = True
        logger.debug("Picked up a Jama session written by another process")
        return stored

    async def refresh_csrf(self, session: StoredSession) -> bool:
        """Fetch a fresh CSRF token with one authenticated GET.

        Returns False if the GET itself was rejected (the session is dead).
        The token comes from the response's ``Set-Cookie``; if the server did
        not send one, the token already in the cookie jar is used.
        """
        result = await probe(self.settings.base_url, session, self._transport)
        if not result.ok:
            return False
        cookie_token = session.cookie_value(CSRF_COOKIE)
        if cookie_token:
            session.set_csrf(cookie_token)
        session.last_validated_at = time.time()
        await self.persist()
        logger.debug("Refreshed the Jama CSRF token")
        return True

    async def recover(
        self, dead: StoredSession | None, interactive: str | None = None
    ) -> StoredSession:
        """Replace a dead session, logging in at most once across all processes.

        Under the lock the store is read again (double-checked locking): if
        another process or coroutine replaced the session while we waited, that
        one is validated and used. Only if the store still holds the same dead
        session do we log in.
        """
        mode = interactive or self.settings.login_interactive
        async with self._recover_lock, self.store.locked(self._lock_timeout):
            stored = self.store.load()
            if stored is not None and not stored.same_as(dead):
                result = await probe(self.settings.base_url, stored, self._transport)
                if result.ok:
                    self._session, self._loaded = stored, True
                    logger.debug("Using the Jama session another process logged in with")
                    return stored

            logger.info("Jama session missing or expired, logging in")
            session = await self._login_func(self.settings, mode)
            self.store.save(session)
            self._session, self._loaded = session, True
            logger.info(f"Logged in to Jama as {session.username or 'unknown user'}")
            return session

    async def login(self, interactive: str = "auto", force: bool = False) -> StoredSession:
        """Explicit login (``jama login``). Reuses a still-valid session unless forced."""
        async with self._recover_lock, self.store.locked(self._lock_timeout):
            stored = self.store.load()
            if stored is not None and not force:
                result = await probe(self.settings.base_url, stored, self._transport)
                if result.ok:
                    stored.username = result.username or stored.username
                    stored.last_validated_at = time.time()
                    self.store.save(stored)
                    self._session, self._loaded = stored, True
                    return stored
            session = await self._login_func(self.settings, interactive)
            self.store.save(session)
            self._session, self._loaded = session, True
            return session

    async def logout(self) -> bool:
        """End the session on the server and delete the store entry.

        Returns True if there was a stored session.
        """
        async with self._recover_lock, self.store.locked(self._lock_timeout):
            stored = self.store.load()
            try:
                if stored is not None:
                    await end_session(self.settings.base_url, stored, self._transport)
            finally:
                self.store.delete()
                self._session, self._loaded = None, True
            return stored is not None

    async def status(self) -> dict[str, Any]:
        """Non-secret description of the stored session, including a live probe."""
        stored = self.store.load()
        info: dict[str, Any] = {
            "base_url": self.settings.base_url,
            "logged_in": False,
            "username": None,
            "created_at": None,
            "last_validated_at": None,
            "age_seconds": None,
            "valid": False,
        }
        if stored is None:
            return info

        result = await probe(self.settings.base_url, stored, self._transport)
        if result.ok:
            stored.username = result.username or stored.username
            stored.last_validated_at = time.time()
            async with self.store.locked(self._lock_timeout):
                # Do not resurrect a session another process just replaced or removed.
                latest = self.store.load()
                if latest is not None and latest.cookie_value(
                    SESSION_COOKIE
                ) == stored.cookie_value(SESSION_COOKIE):
                    self.store.save(stored)
        info.update(
            logged_in=True,
            username=stored.username,
            created_at=stored.created_at,
            last_validated_at=stored.last_validated_at,
            age_seconds=max(0.0, time.time() - stored.created_at),
            valid=result.ok,
        )
        return info

    async def keepalive(self) -> bool:
        """One cheap authenticated GET. Never logs in; returns whether it passed."""
        session = self.current()
        if session is None:
            return False
        return (await probe(self.settings.base_url, session, self._transport)).ok
