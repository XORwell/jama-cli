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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from loguru import logger

from jama_cli.core.exceptions import CoreException, UnauthorizedException
from jama_cli.core.session_store import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    SOURCE_BROWSER_PREFIX,
    SOURCE_FORM,
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
    # None | "firefox" (also accepts a "browser-" prefix). Chrome/Edge are rejected.
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
class LogoutResult:
    """What a logout did. Truthy if there was a stored session."""

    had_session: bool
    # Where the removed session came from ("login", "form", "browser-firefox"), if any.
    source: str | None = None
    # Whether ``logout.req`` was called, i.e. the session was ended on the server.
    server_session_ended: bool = False

    def __bool__(self) -> bool:
        return self.had_session


@dataclass
class ProbeResult:
    """Outcome of the authenticated probe."""

    ok: bool
    username: str | None = None
    status_code: int | None = None
    # The probe changed the session (new cookie or CSRF token); callers that
    # keep the session should save it.
    changed: bool = False


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


def is_csrf_rejected(response: httpx.Response) -> bool:
    """True if the response is a CSRF token problem on a live session.

    Jama checks the ``jama-csrf-token`` header on every call, reads included,
    and answers a wrong or missing one with a 401 "CSRF Exception". The session
    itself is fine; only the token has to be repaired.
    """
    return response.status_code == 401 and "csrf" in response_message(response).lower()


def is_session_rejected(response: httpx.Response) -> bool:
    """True if the response means the web session is dead or not accepted.

    - 3xx whose ``Location`` points at the login/SAML machinery, or
    - 401 with an empty or generic message.

    Two kinds of 401 are *not* a dead session: a message mentioning
    "permission" is a missing permission on a perfectly valid session and must
    never trigger a re-login, and a message mentioning "csrf" is a token
    problem (see :func:`is_csrf_rejected`).
    """
    code = response.status_code
    if 300 <= code < 400:
        location = response.headers.get("Location", "").lower()
        return any(marker in location for marker in _LOGIN_REDIRECT_MARKERS)
    if code == 401:
        message = response_message(response).lower()
        return "permission" not in message and "csrf" not in message
    return False


def is_auth_rejected(response: httpx.Response) -> bool:
    """True if the request was not accepted for either reason: dead session or CSRF."""
    return is_session_rejected(response) or is_csrf_rejected(response)


def merge_response_cookies(
    session: StoredSession, response: httpx.Response, csrf_only: bool = False
) -> bool:
    """Fold ``Set-Cookie`` headers of a response into the session.

    Returns True if the session changed. A new ``jama-csrf-token`` cookie also
    updates the header value, since Jama compares the two. With ``csrf_only``
    every other cookie is ignored; that is the safe choice for a response that
    did not accept the request.
    """
    changed = False
    for cookie in response.cookies.jar:
        if not cookie.value:
            continue
        if cookie.name == CSRF_COOKIE:
            changed = session.set_csrf(cookie.value) or changed
        elif not csrf_only:
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

    The CSRF header is checked on reads too. If the probe is answered with a
    CSRF rejection, the token is taken from the ``jama-csrf-token`` cookie
    (including one the rejection itself may have set) and the probe is sent
    once more. ``session`` is updated in place; ``changed`` reports that.
    """
    api = f"{base_url.rstrip('/')}/rest/v1/"
    changed = False

    async def get(client: httpx.AsyncClient, resource: str, **kwargs: Any) -> httpx.Response:
        nonlocal changed
        retried = False
        while True:
            sent_token = session.csrf_token
            headers = {"Accept": "application/json", **session.auth_headers()}
            response = await client.get(api + resource, headers=headers, **kwargs)
            # httpx would otherwise replay collected cookies next to our header.
            client.cookies.clear()
            if response.status_code == 200:
                changed = merge_response_cookies(session, response) or changed
                return response
            if is_csrf_rejected(response) and not retried:
                merge_response_cookies(session, response, csrf_only=True)
                if session.adopt_cookie_csrf(sent_token):
                    changed = True
                    retried = True
                    continue
            return response

    async with _new_client(transport) as client:
        try:
            response = await get(client, "users/current")
            if response.status_code == 200:
                username = None
                try:
                    data = response.json().get("data", {})
                    username = data.get("username") if isinstance(data, dict) else None
                except (ValueError, AttributeError):
                    pass
                return ProbeResult(True, username, 200, changed)
            if is_auth_rejected(response):
                return ProbeResult(False, None, response.status_code, changed)

            response = await get(client, "projects", params={"maxResults": 1})
            if response.status_code == 200:
                return ProbeResult(True, None, 200, changed)
            return ProbeResult(False, None, response.status_code, changed)
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
    session = StoredSession(base_url=base, cookies=cookies, created_at=now, source=SOURCE_FORM)
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
    session.source = SOURCE_BROWSER_PREFIX + browser
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

    async def persist(self, session: StoredSession, session_id: str | None = None) -> bool:
        """Write an updated session back to the shared store.

        ``session_id`` is the ``JSESSIONID`` the session had before the update
        (default: the one it has now). The store is only written if it still
        holds that session, so an update never overwrites a newer login made by
        another process and never brings back a session that was logged out.
        Returns whether the store was written.
        """
        expected = session_id or session.cookie_value(SESSION_COOKIE)
        async with self.store.locked(self._lock_timeout):
            stored = self.store.load()
            if stored is None or stored.cookie_value(SESSION_COOKIE) != expected:
                return False
            self.store.save(session)
            return True

    async def absorb(self, session: StoredSession, response: httpx.Response) -> None:
        """Take over ``Set-Cookie`` values of a response and save them if they changed.

        Jama may replace ``jama-csrf-token`` or ``JSESSIONID`` in the middle of
        a session. A response that accepted the request is trusted with every
        cookie; a CSRF rejection only with the token cookie; a dead-session
        response with nothing, because the anonymous cookies it may carry must
        not replace the stored session.
        """
        if is_session_rejected(response):
            return
        session_id = session.cookie_value(SESSION_COOKIE)
        if merge_response_cookies(session, response, csrf_only=is_csrf_rejected(response)):
            await self.persist(session, session_id)
            logger.debug("Jama replaced a session cookie, session updated")

    async def adopt_cookie_csrf(self, session: StoredSession, sent_token: str) -> bool:
        """Use the token from the ``jama-csrf-token`` cookie as the header value.

        ``sent_token`` is the header value that was just rejected. Returns True
        if the cookie holds a different token, which is then saved.
        """
        if not session.adopt_cookie_csrf(sent_token):
            return False
        await self.persist(session)
        logger.debug("Took the Jama CSRF token from the session cookie")
        return True

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
        """Fetch the current CSRF token with one authenticated GET.

        The GET sends the token from the cookie as the header (never a header
        value that is known to be wrong) and takes over any ``Set-Cookie`` of
        the answer. Returns False if the GET itself was not accepted.
        """
        session_id = session.cookie_value(SESSION_COOKIE)
        changed = session.adopt_cookie_csrf(None)
        result = await probe(self.settings.base_url, session, self._transport)
        if not result.ok:
            return False
        session.last_validated_at = time.time()
        await self.persist(session, session_id)
        if changed or result.changed:
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
                    if result.changed:
                        self.store.save(stored)
                    self._session, self._loaded = stored, True
                    logger.debug("Using the Jama session another process logged in with")
                    return stored

            logger.info("Jama session missing or expired, logging in")
            session = await self._login_func(self._recovery_settings(dead, stored), mode)
            self.store.save(session)
            self._session, self._loaded = session, True
            logger.info(f"Logged in to Jama as {session.username or 'unknown user'}")
            return session

    def _recovery_settings(
        self, dead: StoredSession | None, stored: StoredSession | None
    ) -> SessionSettings:
        """Settings for replacing a dead session: the way it was obtained wins.

        A session that was taken over from the user's browser is replaced by
        reading the browser again, even in a process whose own configuration
        has no ``session_source`` (for example an MCP server started without
        ``JAMA_SESSION_SOURCE``). Logging in here instead would open a second
        Jama session and could sign the user out in the browser.
        """
        if self.settings.session_source:
            return self.settings
        for candidate in (stored, dead):
            if candidate is not None and candidate.from_browser:
                logger.debug("The dead session came from the browser; reading it again there")
                return replace(self.settings, session_source=candidate.source)
        return self.settings

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

    async def logout(self, end_server_session: bool | None = None) -> LogoutResult:
        """Delete the store entry and, where appropriate, end the session on the server.

        A session this tool logged in itself (``login`` / ``form``) is ended on
        the server, which releases the license seat. A session taken over from
        the user's browser *is* the browser's session: ending it would sign the
        user out there too, so by default only the local entry is removed.

        ``end_server_session`` overrides the default: True always calls
        ``logout.req``, False never does.
        """
        async with self._recover_lock, self.store.locked(self._lock_timeout):
            stored = self.store.load()
            if stored is None:
                self.store.delete()
                self._session, self._loaded = None, True
                return LogoutResult(had_session=False)

            end_on_server = (
                not stored.from_browser if end_server_session is None else end_server_session
            )
            try:
                if end_on_server:
                    await end_session(self.settings.base_url, stored, self._transport)
            finally:
                self.store.delete()
                self._session, self._loaded = None, True
            return LogoutResult(
                had_session=True, source=stored.source, server_session_ended=end_on_server
            )

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
            "source": None,
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
            source=stored.source,
        )
        return info

    async def keepalive(self) -> bool:
        """One cheap authenticated GET. Never logs in; returns whether it passed."""
        session = self.current()
        if session is None:
            return False
        session_id = session.cookie_value(SESSION_COOKIE)
        result = await probe(self.settings.base_url, session, self._transport)
        if result.ok and result.changed:
            await self.persist(session, session_id)
        return result.ok
