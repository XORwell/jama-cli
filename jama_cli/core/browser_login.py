"""Interactive Jama login through a real browser (Playwright).

The user signs in exactly as they would by hand, including SSO, MFA and consent
screens. This module never reads, fills or stores a password: it only opens the
login page, clicks the "Log in with SSO" button if there is one, and waits until
the browser's cookies pass the authenticated probe.

A *persistent* browser profile is used, so the identity provider remembers the
user and later logins usually complete without any window (headless, "silent
SSO"). Only when that does not work is a visible window opened.

Playwright is an optional dependency: ``pip install "jama-cli[browser]"`` and
``playwright install chromium``.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from jama_cli.core.exceptions import CoreException, UnauthorizedException
from jama_cli.core.session import SessionSettings, probe
from jama_cli.core.session_store import CSRF_COOKIE, SESSION_COOKIE, StoredSession

# How long a headless attempt may take before we fall back to a visible window.
SILENT_LOGIN_TIMEOUT = 20.0
POLL_INTERVAL = 0.5

# Visible inputs that mean "a human has to type something here".
_INTERACTIVE_SELECTORS = (
    'input[type="password"]',
    'input[type="email"]',
    'input[name="loginfmt"]',
    'input[name="j_username"]',
)

PLAYWRIGHT_MISSING = (
    "Browser login needs Playwright, which is not installed. Install it with:\n"
    '    pip install "jama-cli[browser]"\n'
    "    playwright install chromium\n"
    "or use the form login mode (JAMA_LOGIN_MODE=form) on non-SSO instances."
)


class InteractionRequired(Exception):
    """A headless login reached a page that needs the user."""


def in_container() -> bool:
    """Best-effort detection of Docker/Podman/Kubernetes."""
    return (
        os.path.exists("/.dockerenv")
        or os.path.exists("/run/.containerenv")
        or bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
        or bool(os.environ.get("container"))  # noqa: SIM112 (set by podman/systemd)
    )


def launch_args() -> list[str]:
    """Extra Chromium flags; containers need the sandbox and /dev/shm workarounds."""
    return ["--no-sandbox", "--disable-dev-shm-usage"] if in_container() else []


class _DebugShots:
    """Numbered screenshots of each login step, written only when a debug dir is set."""

    def __init__(self, debug_dir: Path | None, phase: str) -> None:
        self._dir = debug_dir
        self._phase = phase
        self._n = 0
        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)

    async def shot(self, page: Any, step: str) -> None:
        if not self._dir:
            return
        self._n += 1
        target = self._dir / f"{self._phase}-{self._n:02d}-{step}.png"
        try:
            await page.screenshot(path=str(target))
        except Exception:
            # The page may be mid-navigation or already closed; debugging aid only.
            logger.debug(f"Could not take login screenshot '{step}'")


async def _visible(page: Any, selector: str) -> bool:
    try:
        return bool(await page.locator(selector).first.is_visible())
    except Exception:
        # Navigations during the SAML redirect chain destroy the execution context.
        return False


async def _cookies_for(context: Any, base_url: str) -> list[dict[str, str]]:
    raw = await context.cookies([base_url])
    return [
        {
            "name": str(c["name"]),
            "value": str(c["value"]),
            "domain": str(c.get("domain", "")),
            "path": str(c.get("path", "/")),
        }
        for c in raw
    ]


async def _attempt(
    playwright: Any,
    settings: SessionSettings,
    headless: bool,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
) -> StoredSession:
    """One browser run. Returns an authenticated session or raises."""
    base = settings.base_url
    phase = "headless" if headless else "headful"
    shots = _DebugShots(settings.debug_dir, phase)
    settings.profile_dir.mkdir(parents=True, exist_ok=True)

    launch_kwargs: dict[str, Any] = {"headless": headless, "args": launch_args()}
    if settings.browser_channel:
        launch_kwargs["channel"] = settings.browser_channel

    try:
        context = await playwright.chromium.launch_persistent_context(
            str(settings.profile_dir), **launch_kwargs
        )
    except Exception as e:
        message = str(e).splitlines()[0] if str(e) else type(e).__name__
        raise CoreException(
            f"Could not start the browser ({phase}): {message}. "
            "Run `playwright install chromium`, or pass --browser-channel chrome/msedge. "
            "A visible window needs a display on the machine running this process."
        ) from e

    try:
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(f"{base}/login.req", wait_until="domcontentloaded")
        except Exception:
            # A redirect straight into the IdP can interrupt the navigation.
            logger.debug("Navigation to the Jama login page was interrupted")
        await shots.shot(page, "login-page")

        sso_clicked = False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # The one and only success criterion: the cookies pass the probe.
            # The landing URL after SAML varies between instances, so it is ignored.
            try:
                cookies = await _cookies_for(context, base)
            except Exception as e:
                if not context.pages:
                    raise UnauthorizedException(
                        "The browser window was closed before the login finished."
                    ) from e
                cookies = []

            if any(c["name"] == SESSION_COOKIE for c in cookies):
                session = StoredSession(base_url=base, cookies=cookies, created_at=time.time())
                session.csrf_token = session.cookie_value(CSRF_COOKIE) or ""
                result = await probe(base, session, transport)
                if result.ok:
                    session.username = result.username
                    session.last_validated_at = time.time()
                    await shots.shot(page, "authenticated")
                    return session

            # Tolerate pages being replaced or closed during the redirect chain.
            try:
                if not context.pages:
                    raise UnauthorizedException(
                        "The browser window was closed before the login finished."
                    )
                page = context.pages[-1]

                if not sso_clicked:
                    for selector in settings.sso_selectors:
                        if await _visible(page, selector):
                            await shots.shot(page, "sso-button")
                            await page.locator(selector).first.click()
                            sso_clicked = True
                            logger.debug("Clicked the SSO login button")
                            break

                if headless:
                    # A login form next to a not-yet-left SSO button is not a dead
                    # end; a form without one is, because nobody can type into it.
                    on_sso_page = False
                    for selector in settings.sso_selectors:
                        if await _visible(page, selector):
                            on_sso_page = True
                            break
                    if not on_sso_page:
                        for selector in _INTERACTIVE_SELECTORS:
                            if await _visible(page, selector):
                                await shots.shot(page, "needs-interaction")
                                raise InteractionRequired(selector)
            except (InteractionRequired, UnauthorizedException):
                raise
            except Exception:
                logger.debug("Transient browser error during login, retrying")

            await asyncio.sleep(POLL_INTERVAL)

        await shots.shot(page, "timeout")
        if headless:
            raise InteractionRequired("timeout")
        raise UnauthorizedException(
            f"Jama login timed out after {int(timeout)}s without an authenticated session."
        )
    finally:
        try:
            await context.close()
        except Exception:
            logger.debug("Browser context was already closed")


async def browser_login(
    settings: SessionSettings,
    silent_first: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
    silent_timeout: float = SILENT_LOGIN_TIMEOUT,
    allow_headful: bool = True,
) -> StoredSession:
    """Log in through a browser and return the captured session.

    With ``silent_first`` and an existing profile, a headless run is tried
    first; the IdP often signs the user in without any interaction. If that
    needs the user (login form, MFA, timeout), a visible window is opened and
    the user finishes there.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise CoreException(PLAYWRIGHT_MISSING) from e

    profile_exists = settings.profile_dir.exists() and any(settings.profile_dir.iterdir())

    async with async_playwright() as playwright:
        if silent_first and profile_exists:
            try:
                return await _attempt(
                    playwright,
                    settings,
                    headless=True,
                    timeout=min(silent_timeout, settings.login_timeout),
                    transport=transport,
                )
            except InteractionRequired:
                logger.info("Silent SSO login needs interaction, opening a browser window")

        if not allow_headful:
            raise UnauthorizedException(
                "Silent login was not possible and no browser window may be opened. "
                "Run `jama login`."
            )
        logger.info("Opening a browser window for the Jama login")
        return await _attempt(
            playwright,
            settings,
            headless=False,
            timeout=settings.login_timeout,
            transport=transport,
        )
