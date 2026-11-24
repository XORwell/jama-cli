"""Browser login against the fake Jama over real HTTP.

Skipped when Playwright or its Chromium build is not installed.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("playwright.async_api")

from jama_cli.core.browser_login import browser_login  # noqa: E402
from jama_cli.core.exceptions import CoreException, UnauthorizedException  # noqa: E402
from jama_cli.core.session import SessionSettings  # noqa: E402
from tests.fake_jama import FakeJama  # noqa: E402


def _serve(fake: FakeJama) -> Iterator[tuple[FakeJama, str]]:
    server, base_url = fake.serve()
    try:
        yield fake, base_url
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def sso_jama() -> Iterator[tuple[FakeJama, str]]:
    """SSO instance whose IdP already knows the user (silent SSO)."""
    yield from _serve(FakeJama(sso=True))


@pytest.fixture
def interactive_jama() -> Iterator[tuple[FakeJama, str]]:
    """SSO instance whose IdP asks for a password."""
    yield from _serve(FakeJama(sso=True, idp_interactive=True))


def _settings(base_url: str, tmp_path: Path) -> SessionSettings:
    profile = tmp_path / "profile"
    profile.mkdir()
    # A non-empty profile dir is what makes the silent (headless) attempt run.
    (profile / "marker").write_text("existing profile")
    return SessionSettings(
        base_url=base_url,
        browser_profile_dir=profile,
        debug_dir=tmp_path / "debug",
        login_timeout=30,
    )


async def _login(settings: SessionSettings, **kwargs: object) -> object:
    try:
        return await browser_login(settings, allow_headful=False, **kwargs)  # type: ignore[arg-type]
    except CoreException as e:
        if "Could not start the browser" in str(e):
            pytest.skip("Chromium for Playwright is not installed")
        raise


async def test_silent_sso_login(sso_jama: tuple[FakeJama, str], tmp_path: Path) -> None:
    fake, base_url = sso_jama
    settings = _settings(base_url, tmp_path)

    session = await _login(settings)

    assert session.username == "alice"  # type: ignore[attr-defined]
    assert fake.is_authenticated(session.cookie_value("JSESSIONID"))  # type: ignore[attr-defined]
    assert session.csrf_token  # type: ignore[attr-defined]
    assert fake.login_count == 1
    # The SSO button was found and the SAML chain was followed.
    paths = [path for _method, path in fake.requests]
    assert "/contour/saml/login" in paths and "/idp/auth" in paths
    # --debug-dir: one screenshot per step.
    assert any(p.name.endswith("authenticated.png") for p in (tmp_path / "debug").iterdir())


async def test_repeated_login_stays_silent(sso_jama: tuple[FakeJama, str], tmp_path: Path) -> None:
    fake, base_url = sso_jama
    settings = _settings(base_url, tmp_path)

    first = await _login(settings)
    second = await _login(settings)

    # JSESSIONID is a session cookie, so the browser profile does not keep it:
    # the second run goes through the IdP again, still without any window.
    assert fake.login_count == 2
    assert fake.is_authenticated(second.cookie_value("JSESSIONID"))  # type: ignore[attr-defined]
    assert not fake.is_authenticated(first.cookie_value("JSESSIONID"))  # type: ignore[attr-defined]


async def test_headless_stops_when_interaction_is_needed(
    interactive_jama: tuple[FakeJama, str], tmp_path: Path
) -> None:
    fake, base_url = interactive_jama
    settings = _settings(base_url, tmp_path)

    with pytest.raises(UnauthorizedException) as exc:
        await _login(settings, silent_timeout=15)

    assert "jama login" in str(exc.value)
    assert fake.login_count == 0
