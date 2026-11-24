"""Tests for reusing the browser's Jama session (``jama login --from-browser``).

Firefox is exercised against a real (temporary) ``cookies.sqlite``, so no browser
is needed. Chrome and Edge are not supported and must be refused.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jama_cli.core.browser_cookies import (
    BROWSERS,
    CHROMIUM_UNSUPPORTED,
    BrowserCookieError,
    host_matches,
    normalise_source,
    read_browser_session,
    read_firefox,
)
from jama_cli.core.session import SessionManager, SessionSettings, browser_cookie_login
from jama_cli.core.session_store import SessionStore
from tests.fake_jama import FakeJama

BASE = "https://jama.example.com/contour"
HOST = "jama.example.com"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def make_firefox_db(path: Path, cookies: list[tuple[str, str, str]]) -> None:
    """Write a minimal Firefox cookies.sqlite with (name, value, host) rows."""
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE moz_cookies "
        "(id INTEGER PRIMARY KEY, name TEXT, value TEXT, host TEXT, path TEXT, "
        "expiry INTEGER, isSecure INTEGER, isHttpOnly INTEGER)"
    )
    conn.executemany(
        "INSERT INTO moz_cookies (name, value, host, path, expiry, isSecure, isHttpOnly) "
        "VALUES (?, ?, ?, '/', 0, 1, 1)",
        cookies,
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_normalise_source(self) -> None:
        assert normalise_source("firefox") == "firefox"
        assert normalise_source("browser-firefox") == "firefox"
        assert normalise_source("FireFox") == "firefox"
        assert normalise_source(None) is None
        assert normalise_source("login") is None
        assert normalise_source("") is None
        with pytest.raises(BrowserCookieError):
            normalise_source("safari")

    def test_host_matches(self) -> None:
        assert host_matches("jama.example.com", "jama.example.com")
        assert host_matches(".example.com", "jama.example.com")
        assert not host_matches("other.com", "jama.example.com")
        assert not host_matches("example.com", "notexample.com")


# ---------------------------------------------------------------------------
# Firefox (plain text)
# ---------------------------------------------------------------------------


class TestFirefox:
    def test_reads_both_cookies_for_the_host(self, tmp_path: Path) -> None:
        db = tmp_path / "cookies.sqlite"
        make_firefox_db(
            db,
            [
                ("JSESSIONID", "sid-abc", HOST),
                ("jama-csrf-token", "csrf-xyz", ".example.com"),
                ("unrelated", "nope", "other.com"),
                ("JSESSIONID", "someone-else", "other.com"),
            ],
        )
        session = read_firefox(BASE, db)
        assert session.cookie_value("JSESSIONID") == "sid-abc"
        assert session.cookie_value("jama-csrf-token") == "csrf-xyz"
        assert session.csrf_token == "csrf-xyz"
        assert session.base_url == BASE

    def test_missing_session_cookie_is_a_clear_error(self, tmp_path: Path) -> None:
        db = tmp_path / "cookies.sqlite"
        make_firefox_db(db, [("jama-csrf-token", "csrf", HOST)])
        with pytest.raises(BrowserCookieError) as exc:
            read_firefox(BASE, db)
        assert "JSESSIONID" in str(exc.value)

    def test_locked_db_with_wal_is_copied_not_opened_in_place(self, tmp_path: Path) -> None:
        db = tmp_path / "cookies.sqlite"
        make_firefox_db(db, [("JSESSIONID", "s", HOST), ("jama-csrf-token", "c", HOST)])
        (tmp_path / "cookies.sqlite-wal").write_bytes(b"")  # sidecar present
        session = read_firefox(BASE, db)
        assert session.cookie_value("JSESSIONID") == "s"
        # Nothing of ours is left behind next to the original.
        assert not list(tmp_path.glob("jama-cookies-*"))

    def test_find_profile_via_profiles_ini(self, tmp_path: Path) -> None:
        prof = tmp_path / "Profiles" / "abc.default-release"
        prof.mkdir(parents=True)
        make_firefox_db(
            prof / "cookies.sqlite",
            [("JSESSIONID", "s", HOST), ("jama-csrf-token", "c", HOST)],
        )
        (tmp_path / "profiles.ini").write_text(
            "[Profile0]\nName=default\nIsRelative=1\nPath=Profiles/abc.default-release\n"
            "Default=1\n\n[Install123]\nDefault=Profiles/abc.default-release\n"
        )
        session = read_browser_session(BASE, "firefox", cookies_path=tmp_path)
        assert session.cookie_value("JSESSIONID") == "s"


# ---------------------------------------------------------------------------
# Chrome / Edge: refused, never a fallback to a fresh login
# ---------------------------------------------------------------------------


class TestChromiumIsRefused:
    @pytest.mark.parametrize(
        "source", ["chrome", "edge", "browser-chrome", "browser-edge", "Chrome", "msedge"]
    )
    def test_source_is_rejected_with_the_explanation(self, source: str) -> None:
        with pytest.raises(BrowserCookieError) as exc:
            normalise_source(source)
        assert str(exc.value) == CHROMIUM_UNSUPPORTED
        assert "App-Bound Encryption" in str(exc.value)
        assert "--from-browser firefox" in str(exc.value)

    def test_reading_refuses_before_touching_any_file(self, tmp_path: Path) -> None:
        with pytest.raises(BrowserCookieError) as exc:
            read_browser_session(BASE, "chrome", cookies_path=tmp_path / "does-not-exist")
        assert str(exc.value) == CHROMIUM_UNSUPPORTED

    async def test_configured_chrome_source_fails_and_never_logs_in(self, tmp_path: Path) -> None:
        fake = FakeJama()
        settings = SessionSettings(
            base_url=BASE,
            username="alice",
            password="s3cret-pw-alice",
            login_mode="form",  # a login would be possible; it must not happen
            session_source="browser-edge",
            session_file=tmp_path / "s.json",
        )
        manager = SessionManager(settings, transport=fake.transport())
        with pytest.raises(BrowserCookieError) as exc:
            await manager.login()
        assert str(exc.value) == CHROMIUM_UNSUPPORTED
        assert fake.login_count == 0
        assert SessionStore(settings.store_path).load() is None

    def test_cli_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner

        from jama_cli.main import app

        for name in ("JAMA_SESSION_SOURCE", "JAMA_API_KEY", "JAMA_CLIENT_ID", "JAMA_USERNAME"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("JAMA_URL", BASE)
        monkeypatch.setenv("JAMA_AUTH_TYPE", "session")
        result = CliRunner().invoke(app, ["login", "--from-browser", "chrome"])
        assert result.exit_code == 1
        assert "Reading Chrome/Edge cookies is not supported" in result.output.replace("\n", " ")

    def test_no_helper_script_is_shipped(self) -> None:
        from jama_cli import core

        package_dir = Path(core.__file__).parent
        assert list(package_dir.glob("*.ps1")) == []
        assert "powershell" not in (package_dir / "browser_cookies.py").read_text().lower()
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        assert ".ps1" not in pyproject.read_text()


# ---------------------------------------------------------------------------
# No secrets leak through logs or errors
# ---------------------------------------------------------------------------


class TestNoLeaks:
    def test_cookie_values_never_appear_in_errors(self, tmp_path: Path) -> None:
        db = tmp_path / "cookies.sqlite"
        make_firefox_db(db, [("JSESSIONID", "super-secret-sid", HOST)])  # csrf missing
        with pytest.raises(BrowserCookieError) as exc:
            read_firefox(BASE, db)
        assert "super-secret-sid" not in str(exc.value)

    def test_session_repr_hides_values(self, tmp_path: Path) -> None:
        db = tmp_path / "cookies.sqlite"
        make_firefox_db(
            db, [("JSESSIONID", "secret-sid", HOST), ("jama-csrf-token", "secret-csrf", HOST)]
        )
        session = read_firefox(BASE, db)
        assert "secret-sid" not in repr(session)
        assert "secret-csrf" not in repr(session)


# ---------------------------------------------------------------------------
# Login path: validate with the fake Jama and store like a normal login
# ---------------------------------------------------------------------------


class TestBrowserLoginPath:
    @pytest.fixture
    def settings(self, tmp_path: Path) -> SessionSettings:
        return SessionSettings(
            base_url=BASE,
            session_source="firefox",
            browser_cookies_path=tmp_path / "ff" / "cookies.sqlite",
            session_file=tmp_path / "sessions" / "s.json",
        )

    def _write_ff(self, settings: SessionSettings, sid: str, csrf: str) -> None:
        db = settings.browser_cookies_path
        assert db is not None
        db.parent.mkdir(parents=True, exist_ok=True)
        make_firefox_db(db, [("JSESSIONID", sid, HOST), ("jama-csrf-token", csrf, HOST)])

    async def test_valid_browser_cookies_become_a_stored_session(
        self, settings: SessionSettings
    ) -> None:
        fake = FakeJama()
        sid, csrf = fake.plant_session("alice")
        self._write_ff(settings, sid, csrf)

        session = await browser_cookie_login(settings, "firefox", fake.transport())
        assert session.username == "alice"
        assert session.cookie_value("JSESSIONID") == sid

    async def test_invalid_browser_cookies_raise_not_relogin(
        self, settings: SessionSettings
    ) -> None:
        fake = FakeJama()
        self._write_ff(settings, "stale-sid", "stale-csrf")  # never a live session
        with pytest.raises(Exception) as exc:
            await browser_cookie_login(settings, "firefox", fake.transport())
        assert "not valid" in str(exc.value).lower()

    async def test_manager_login_uses_the_browser_source(self, settings: SessionSettings) -> None:
        fake = FakeJama()
        sid, csrf = fake.plant_session("alice")
        self._write_ff(settings, sid, csrf)

        manager = SessionManager(settings, transport=fake.transport())
        session = await manager.login()
        assert session.username == "alice"
        stored = SessionStore(settings.store_path).load()
        assert stored is not None
        assert stored.cookie_value("JSESSIONID") == sid
        # Reading cookies is not a server login.
        assert fake.login_count == 0

    async def test_dead_session_rereads_the_browser_instead_of_interactive_login(
        self, settings: SessionSettings
    ) -> None:
        fake = FakeJama()
        sid, csrf = fake.plant_session("alice")
        self._write_ff(settings, sid, csrf)
        manager = SessionManager(settings, transport=fake.transport())
        await manager.login()

        # The server drops the session; the user signs in again in the browser,
        # which lands as new cookies in the store the CLI reads.
        fake.kill_sessions()
        sid2, csrf2 = fake.plant_session("alice")
        self._write_ff(settings, sid2, csrf2)

        recovered = await manager.recover(manager.current(), interactive="never")
        assert recovered.cookie_value("JSESSIONID") == sid2
        assert fake.login_count == 0

    def test_only_firefox_is_supported(self) -> None:
        assert set(BROWSERS) == {"firefox"}
