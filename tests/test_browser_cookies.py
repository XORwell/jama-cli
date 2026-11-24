"""Tests for reusing the browser's Jama session (``jama login --from-browser``).

Firefox is exercised against a real (temporary) ``cookies.sqlite``, so no browser
is needed. Chrome and Edge are not supported and must be refused.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from jama_cli.core import browser_cookies
from jama_cli.core.browser_cookies import (
    BROWSERS,
    CHROMIUM_UNSUPPORTED,
    BrowserCookieError,
    host_matches,
    lz4_block_decompress,
    normalise_source,
    read_browser_session,
    read_firefox,
    read_mozlz4,
)
from jama_cli.core.session import SessionManager, SessionSettings, browser_cookie_login
from jama_cli.core.session_store import SessionStore
from tests.fake_jama import FakeJama

BASE = "https://jama.example.com/contour"
HOST = "jama.example.com"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def make_firefox_db(path: Path, cookies: list[tuple[str, ...]]) -> None:
    """Write a minimal Firefox cookies.sqlite.

    Rows are (name, value, host) or (name, value, host, originAttributes).
    """
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE moz_cookies "
        "(id INTEGER PRIMARY KEY, originAttributes TEXT NOT NULL DEFAULT '', name TEXT, "
        "value TEXT, host TEXT, path TEXT, expiry INTEGER, isSecure INTEGER, isHttpOnly INTEGER)"
    )
    conn.executemany(
        "INSERT INTO moz_cookies "
        "(name, value, host, originAttributes, path, expiry, isSecure, isHttpOnly) "
        "VALUES (?, ?, ?, ?, '/', 0, 1, 1)",
        [row if len(row) == 4 else (*row, "") for row in cookies],
    )
    conn.commit()
    conn.close()


def lz4_literals_block(data: bytes) -> bytes:
    """An LZ4 block that stores ``data`` as literals only (valid, uncompressed)."""
    length = len(data)
    if length < 15:
        return bytes([length << 4]) + data
    rest = length - 15
    extra = b"\xff" * (rest // 255) + bytes([rest % 255])
    return b"\xf0" + extra + data


def write_session_store(profile_dir: Path, cookies: list[dict[str, Any]], name: str = "") -> Path:
    """Write a Firefox session store (mozLz4) holding the given session cookies."""
    path = profile_dir / (name or "sessionstore-backups/recovery.jsonlz4")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"version": ["sessionrestore", 1], "cookies": cookies}).encode()
    path.write_bytes(
        b"mozLz40\0" + len(payload).to_bytes(4, "little") + lz4_literals_block(payload)
    )
    return path


def store_cookie(name: str, value: str, host: str = HOST, **attrs: Any) -> dict[str, Any]:
    origin = {
        "firstPartyDomain": "",
        "partitionKey": "",
        "privateBrowsingId": 0,
        "userContextId": 0,
    }
    origin.update(attrs)
    return {"host": host, "name": name, "value": value, "path": "/", "originAttributes": origin}


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


# ---------------------------------------------------------------------------
# Logout: a browser-sourced session is the browser's own session
# ---------------------------------------------------------------------------


LOGOUT = ("GET", "/contour/logout.req")


class TestLogoutSparesTheBrowser:
    @pytest.fixture
    def settings(self, tmp_path: Path) -> SessionSettings:
        return SessionSettings(
            base_url=BASE,
            session_source="firefox",
            browser_cookies_path=tmp_path / "ff" / "cookies.sqlite",
            session_file=tmp_path / "sessions" / "s.json",
        )

    async def _browser_login(self, fake: FakeJama, settings: SessionSettings) -> tuple[Any, str]:
        sid, csrf = fake.plant_session("alice")
        db = settings.browser_cookies_path
        assert db is not None
        db.parent.mkdir(parents=True, exist_ok=True)
        make_firefox_db(db, [("JSESSIONID", sid, HOST), ("jama-csrf-token", csrf, HOST)])
        manager = SessionManager(settings, transport=fake.transport())
        await manager.login()
        return manager, sid

    async def test_source_is_stored_in_the_session_file(self, settings: SessionSettings) -> None:
        fake = FakeJama()
        await self._browser_login(fake, settings)

        assert json.loads(settings.store_path.read_text())["source"] == "browser-firefox"
        stored = SessionStore(settings.store_path).load()
        assert stored is not None and stored.from_browser

    async def test_logout_removes_only_the_local_entry(self, settings: SessionSettings) -> None:
        fake = FakeJama()
        manager, sid = await self._browser_login(fake, settings)

        result = await manager.logout()

        assert result.had_session and result.source == "browser-firefox"
        assert result.server_session_ended is False
        assert LOGOUT not in fake.requests
        assert fake.is_authenticated(sid)  # the browser is still signed in
        assert not settings.store_path.exists()

    async def test_end_server_session_calls_logout_with_the_csrf_header(
        self, settings: SessionSettings
    ) -> None:
        fake = FakeJama()
        manager, sid = await self._browser_login(fake, settings)

        result = await manager.logout(end_server_session=True)

        assert result.server_session_ended is True
        assert fake.requests.count(LOGOUT) == 1
        # The fake only ends a session when logout.req carries the CSRF header.
        assert not fake.is_authenticated(sid)
        assert not settings.store_path.exists()

    async def test_source_survives_a_token_repair(self, settings: SessionSettings) -> None:
        fake = FakeJama()
        manager, _sid = await self._browser_login(fake, settings)
        data = json.loads(settings.store_path.read_text())
        data["csrf_token"] = "wrong-token"
        settings.store_path.write_text(json.dumps(data))

        from jama_cli.core.http_client import JamaHttpClient

        fresh = SessionManager(settings, transport=fake.transport())
        async with JamaHttpClient(BASE, session=fresh, transport=fake.transport()) as client:
            await client.get("items/1")

        stored = SessionStore(settings.store_path).load()
        assert stored is not None and stored.source == "browser-firefox"

    def test_cli_logout_messages(
        self, settings: SessionSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from typer.testing import CliRunner

        from jama_cli.commands import auth
        from jama_cli.main import app

        fake = FakeJama()
        for name in ("JAMA_API_KEY", "JAMA_CLIENT_ID", "JAMA_USERNAME", "JAMA_SESSION_SOURCE"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("JAMA_URL", BASE)
        monkeypatch.setenv("JAMA_AUTH_TYPE", "session")
        monkeypatch.setattr(
            auth,
            "SessionManager",
            lambda _settings: SessionManager(settings, transport=fake.transport()),
        )
        runner = CliRunner()

        _manager, sid = asyncio.run(self._browser_login(fake, settings))
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0
        assert "your browser session is still active" in " ".join(result.output.split())
        assert fake.is_authenticated(sid)
        assert LOGOUT not in fake.requests

        _manager, sid = asyncio.run(self._browser_login(fake, settings))
        result = runner.invoke(app, ["logout", "--end-server-session"])
        assert result.exit_code == 0
        assert "signed out there too" in " ".join(result.output.split())
        assert not fake.is_authenticated(sid)

    async def test_mcp_logout_tool_follows_the_same_rule(self, settings: SessionSettings) -> None:
        from jama_mcp_server.core.stdio_server import JamaStdioMCPServer
        from jama_mcp_server.models import JamaConfig

        fake = FakeJama()
        _manager, sid = await self._browser_login(fake, settings)
        server = JamaStdioMCPServer(JamaConfig(url=BASE, api_key="unused"), settings)
        manager = SessionManager(settings, transport=fake.transport())
        server._session = manager
        server._api = object()  # type: ignore[assignment]

        result = await server._execute_tool("logout_session", {})
        assert result["server_session_ended"] is False
        assert result["browser_session_still_active"] is True
        assert result["source"] == "browser-firefox"
        assert fake.is_authenticated(sid)
        assert LOGOUT not in fake.requests
        for secret in fake.live_secrets():
            assert secret not in json.dumps(result)

        _manager, sid = await self._browser_login(fake, settings)
        result = await server._execute_tool("logout_session", {"end_server_session": True})
        assert result["server_session_ended"] is True
        assert result["browser_session_still_active"] is False
        assert not fake.is_authenticated(sid)


class TestLoginSourcedLogoutIsUnchanged:
    async def test_form_session_is_ended_on_the_server(self, tmp_path: Path) -> None:
        fake = FakeJama()
        settings = SessionSettings(
            base_url=BASE,
            username="alice",
            password="s3cret-pw-alice",
            login_mode="form",
            session_file=tmp_path / "s.json",
        )
        manager = SessionManager(settings, transport=fake.transport())
        session = await manager.login()
        sid = session.cookie_value("JSESSIONID") or ""
        assert json.loads(settings.store_path.read_text())["source"] == "form"

        result = await manager.logout()

        assert result.server_session_ended is True
        assert fake.requests.count(LOGOUT) == 1
        assert not fake.is_authenticated(sid)

    async def test_old_session_file_without_source_is_a_login_session(self, tmp_path: Path) -> None:
        fake = FakeJama()
        sid, csrf = fake.plant_session("alice")
        path = tmp_path / "old.json"
        # The format written before the "source" key existed.
        path.write_text(
            json.dumps(
                {
                    "base_url": BASE,
                    "username": "alice",
                    "cookies": [
                        {"name": "JSESSIONID", "value": sid, "domain": HOST, "path": "/"},
                        {"name": "jama-csrf-token", "value": csrf, "domain": HOST, "path": "/"},
                    ],
                    "csrf_token": csrf,
                    "created_at": 1.0,
                    "last_validated_at": 2.0,
                }
            )
        )
        stored = SessionStore(path).load()
        assert stored is not None
        assert stored.source == "login" and not stored.from_browser

        settings = SessionSettings(base_url=BASE, session_file=path)
        result = await SessionManager(settings, transport=fake.transport()).logout()
        assert result.server_session_ended is True
        assert not fake.is_authenticated(sid)


# ---------------------------------------------------------------------------
# Recovery follows where the session came from, not the process's own settings
# ---------------------------------------------------------------------------


class TestRecoveryFollowsTheStoredSource:
    """`--from-browser` applies to one call; later processes must not log in on their own."""

    def _settings(self, tmp_path: Path, source: str | None) -> SessionSettings:
        return SessionSettings(
            base_url=BASE,
            username="alice",
            password="s3cret-pw-alice",
            login_mode="form",  # a login of its own would be possible
            session_source=source,
            browser_cookies_path=tmp_path / "ff" / "cookies.sqlite",
            session_file=tmp_path / "sessions" / "s.json",
        )

    def _browser_has(self, settings: SessionSettings, sid: str, csrf: str) -> None:
        db = settings.browser_cookies_path
        assert db is not None
        db.parent.mkdir(parents=True, exist_ok=True)
        make_firefox_db(db, [("JSESSIONID", sid, HOST), ("jama-csrf-token", csrf, HOST)])

    async def test_other_process_without_session_source_rereads_the_browser(
        self, tmp_path: Path
    ) -> None:
        fake = FakeJama()
        first = self._settings(tmp_path, "firefox")
        self._browser_has(first, *fake.plant_session("alice"))
        await SessionManager(first, transport=fake.transport()).login()

        # The session ends; the user signs in again in the browser.
        fake.kill_sessions()
        new_sid, new_csrf = fake.plant_session("alice")
        self._browser_has(first, new_sid, new_csrf)

        # E.g. the MCP server: same store, but no session_source configured.
        other = SessionManager(self._settings(tmp_path, None), transport=fake.transport())
        from jama_cli.core.http_client import JamaHttpClient

        async with JamaHttpClient(BASE, session=other, transport=fake.transport()) as client:
            item = await client.get("items/1")

        assert item["data"]["id"] == 1
        assert fake.login_count == 0  # no login of its own, no second session
        stored = SessionStore(first.store_path).load()
        assert stored is not None
        assert stored.cookie_value("JSESSIONID") == new_sid
        assert stored.source == "browser-firefox"

    async def test_no_fallback_to_an_own_login_when_the_browser_is_signed_out(
        self, tmp_path: Path
    ) -> None:
        fake = FakeJama()
        first = self._settings(tmp_path, "firefox")
        self._browser_has(first, *fake.plant_session("alice"))
        await SessionManager(first, transport=fake.transport()).login()
        fake.kill_sessions()  # signed out everywhere; the browser still holds dead cookies

        other = SessionManager(self._settings(tmp_path, None), transport=fake.transport())
        with pytest.raises(Exception) as exc:
            await other.recover(other.current())

        assert "Sign in to Jama in the browser" in str(exc.value)
        assert fake.login_count == 0

    async def test_own_login_session_is_recovered_by_login_as_before(self, tmp_path: Path) -> None:
        fake = FakeJama()
        settings = self._settings(tmp_path, None)
        manager = SessionManager(settings, transport=fake.transport())
        await manager.login()
        fake.kill_sessions()

        recovered = await manager.recover(manager.current())

        assert fake.login_count == 2 and recovered.source == "form"

    async def test_explicit_login_replaces_a_browser_session_on_purpose(
        self, tmp_path: Path
    ) -> None:
        fake = FakeJama()
        first = self._settings(tmp_path, "firefox")
        self._browser_has(first, *fake.plant_session("alice"))
        await SessionManager(first, transport=fake.transport()).login()

        own = SessionManager(self._settings(tmp_path, None), transport=fake.transport())
        session = await own.login(force=True)

        assert session.source == "form" and fake.login_count == 1

    async def test_from_browser_login_does_not_reuse_an_own_login_session(
        self, tmp_path: Path
    ) -> None:
        """`jama login --from-browser firefox` must read the browser, not keep a form session."""
        fake = FakeJama()
        own = SessionManager(self._settings(tmp_path, None), transport=fake.transport())
        own_session = await own.login()
        browser = self._settings(tmp_path, "firefox")
        # Another account, so the fake's one-session-per-user rule keeps both alive.
        self._browser_has(browser, *fake.plant_session("bob"))
        assert fake.is_authenticated(own_session.cookie_value("JSESSIONID") or "")

        session = await SessionManager(browser, transport=fake.transport()).login()

        assert session.source == "browser-firefox" and fake.login_count == 1


# ---------------------------------------------------------------------------
# Firefox session store (where session cookies such as JSESSIONID live)
# ---------------------------------------------------------------------------


class TestSessionStore:
    def test_lz4_block_with_overlapping_match(self) -> None:
        # literals "abc", then a match of 9 bytes at offset 3, then an empty last sequence
        block = bytes([0x35]) + b"abc" + bytes([3, 0]) + bytes([0x00])
        assert lz4_block_decompress(block) == b"abc" * 4

    def test_lz4_rejects_an_offset_before_the_start(self) -> None:
        with pytest.raises(ValueError):
            lz4_block_decompress(bytes([0x10]) + b"a" + bytes([5, 0]))

    def test_read_mozlz4_round_trip(self, tmp_path: Path) -> None:
        path = write_session_store(tmp_path, [store_cookie("JSESSIONID", "sid")])
        assert read_mozlz4(path)["cookies"][0]["name"] == "JSESSIONID"

    def test_session_cookies_come_from_the_store(self, tmp_path: Path) -> None:
        """Real Firefox: cookies.sqlite has only persistent cookies, never JSESSIONID."""
        db = tmp_path / "cookies.sqlite"
        make_firefox_db(db, [("_dd_s", "rum", HOST)])
        write_session_store(
            tmp_path,
            [
                store_cookie("JSESSIONID", "sid-live"),
                store_cookie("jama-csrf-token", "csrf-live", host="." + HOST),
            ],
        )

        session = read_firefox(BASE, db)

        assert session.cookie_value("JSESSIONID") == "sid-live"
        assert session.csrf_token == "csrf-live"

    def test_private_container_and_partitioned_cookies_are_ignored(self, tmp_path: Path) -> None:
        db = tmp_path / "cookies.sqlite"
        make_firefox_db(db, [("JSESSIONID", "sid-container", HOST, "^userContextId=2")])
        write_session_store(
            tmp_path,
            [
                store_cookie("JSESSIONID", "sid-private", privateBrowsingId=1),
                store_cookie("jama-csrf-token", "csrf-part", partitionKey="(https,example.org)"),
                store_cookie("jama-csrf-token", "csrf-ok"),
            ],
        )

        with pytest.raises(BrowserCookieError) as exc:
            read_firefox(BASE, db)

        assert "JSESSIONID" in str(exc.value)
        for secret in ("sid-container", "sid-private", "csrf-part", "csrf-ok"):
            assert secret not in str(exc.value)

    def test_the_newest_store_file_wins(self, tmp_path: Path) -> None:
        db = tmp_path / "cookies.sqlite"
        make_firefox_db(db, [])
        old = write_session_store(
            tmp_path,
            [store_cookie("JSESSIONID", "sid-old"), store_cookie("jama-csrf-token", "c-old")],
            name="sessionstore.jsonlz4",
        )
        os.utime(old, (1_000, 1_000))
        write_session_store(
            tmp_path,
            [store_cookie("JSESSIONID", "sid-new"), store_cookie("jama-csrf-token", "c-new")],
        )

        assert read_firefox(BASE, db).cookie_value("JSESSIONID") == "sid-new"

    def test_corrupt_store_is_skipped(self, tmp_path: Path) -> None:
        db = tmp_path / "cookies.sqlite"
        make_firefox_db(db, [])
        bad = tmp_path / "sessionstore-backups" / "recovery.jsonlz4"
        bad.parent.mkdir(parents=True)
        bad.write_bytes(b"mozLz40\0garbage")

        with pytest.raises(BrowserCookieError, match="missing cookie"):
            read_firefox(BASE, db)


# ---------------------------------------------------------------------------
# Where Firefox lives on each platform
# ---------------------------------------------------------------------------


def make_profile_root(root: Path, sid: str, csrf: str, mtime: float) -> Path:
    profile = root / "Profiles" / "abc.default-release"
    profile.mkdir(parents=True)
    (root / "profiles.ini").write_text(
        "[Install1]\nDefault=Profiles/abc.default-release\n\n"
        "[Profile0]\nName=default-release\nIsRelative=1\nPath=Profiles/abc.default-release\n"
    )
    make_firefox_db(profile / "cookies.sqlite", [])
    store = write_session_store(
        profile, [store_cookie("JSESSIONID", sid), store_cookie("jama-csrf-token", csrf)]
    )
    for path in (store, profile / "cookies.sqlite"):
        os.utime(path, (mtime, mtime))
    return profile


class TestProfileRoots:
    @pytest.fixture
    def home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(browser_cookies.Path, "home", lambda: tmp_path)
        monkeypatch.setattr(browser_cookies, "in_wsl", lambda: False)
        return tmp_path

    def test_windows_uses_appdata(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_cookies.sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(home / "Roaming"))
        assert browser_cookies.firefox_root_candidates() == [home / "Roaming" / "Mozilla/Firefox"]

    def test_macos(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_cookies.sys, "platform", "darwin")
        assert browser_cookies.firefox_root_candidates() == [
            home / "Library/Application Support/Firefox"
        ]

    def test_linux_knows_xdg_snap_and_flatpak(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_cookies.sys, "platform", "linux")
        roots = browser_cookies.firefox_root_candidates()
        assert home / ".mozilla/firefox" in roots
        assert home / ".config/mozilla/firefox" in roots
        assert home / "snap/firefox/common/.mozilla/firefox" in roots
        assert home / ".var/app/org.mozilla.firefox/.mozilla/firefox" in roots

    def test_wsl_puts_the_windows_firefox_first(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_cookies.sys, "platform", "linux")
        monkeypatch.setattr(browser_cookies, "in_wsl", lambda: True)
        monkeypatch.setattr(browser_cookies, "windows_user_home", lambda: home / "win")
        roots = browser_cookies.firefox_root_candidates()
        assert roots[0] == home / "win" / "AppData/Roaming/Mozilla/Firefox"
        assert home / ".mozilla/firefox" in roots

    def test_the_most_recently_used_firefox_wins(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_cookies.sys, "platform", "linux")
        monkeypatch.setattr(browser_cookies, "in_wsl", lambda: True)
        monkeypatch.setattr(browser_cookies, "windows_user_home", lambda: home / "win")
        make_profile_root(home / "win/AppData/Roaming/Mozilla/Firefox", "sid-win", "c-win", 1_000)
        make_profile_root(
            home / "snap/firefox/common/.mozilla/firefox", "sid-snap", "c-snap", 2_000
        )

        session = read_browser_session(BASE, "firefox")

        assert session.cookie_value("JSESSIONID") == "sid-snap"

    def test_no_firefox_names_the_places_searched(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_cookies.sys, "platform", "darwin")
        with pytest.raises(BrowserCookieError, match="Library/Application Support/Firefox"):
            read_browser_session(BASE, "firefox")


# ---------------------------------------------------------------------------
# WSL: finding the Windows user's home
# ---------------------------------------------------------------------------


class TestWindowsUserHome:
    @pytest.fixture
    def drive(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        c = tmp_path / "mnt" / "c"
        (c / "Users" / "winme").mkdir(parents=True)
        monkeypatch.setattr(browser_cookies, "WSL_WINDOWS_DRIVE", c)
        return c

    @staticmethod
    def _fake_cmd(monkeypatch: pytest.MonkeyPatch, works: set[str], profile: str) -> list[str]:
        calls: list[str] = []

        def run(args: list[str], **_: Any) -> Any:
            calls.append(args[0])
            if args[0] not in works:
                raise FileNotFoundError(args[0])
            return type("Done", (), {"stdout": profile + "\r\n"})()

        monkeypatch.setattr(browser_cookies.subprocess, "run", run)
        return calls

    def test_cmd_on_path(self, drive: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._fake_cmd(monkeypatch, {"cmd.exe"}, "C:\\Users\\winme")
        assert browser_cookies.windows_user_home() == drive / "Users" / "winme"

    def test_cmd_by_absolute_path_when_windows_is_not_on_path(
        self, drive: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        absolute = str(drive / "Windows/System32/cmd.exe")
        calls = self._fake_cmd(monkeypatch, {absolute}, "C:\\Users\\winme")

        assert browser_cookies.windows_user_home() == drive / "Users" / "winme"
        assert calls == ["cmd.exe", absolute]

    def test_profile_on_another_drive(self, drive: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (drive.parent / "d" / "Users" / "winme").mkdir(parents=True)
        self._fake_cmd(monkeypatch, {"cmd.exe"}, "D:\\Users\\winme")
        assert browser_cookies.windows_user_home() == drive.parent / "d" / "Users" / "winme"

    def test_without_interop_the_only_firefox_user_is_used(
        self, drive: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fake_cmd(monkeypatch, set(), "")
        (drive / "Users" / "Public").mkdir()
        firefox = drive / "Users" / "winme" / browser_cookies.WINDOWS_FIREFOX_DIR
        firefox.mkdir(parents=True)
        (firefox / "profiles.ini").write_text("[General]\n")

        assert browser_cookies.windows_user_home() == drive / "Users" / "winme"

    def test_without_interop_several_firefox_users_are_not_guessed(
        self, drive: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fake_cmd(monkeypatch, set(), "")
        for user in ("winme", "colleague"):
            firefox = drive / "Users" / user / browser_cookies.WINDOWS_FIREFOX_DIR
            firefox.mkdir(parents=True)
            (firefox / "profiles.ini").write_text("[General]\n")

        assert browser_cookies.windows_user_home() is None

    def test_unusable_answer_falls_through(
        self, drive: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fake_cmd(monkeypatch, {"cmd.exe"}, "%USERPROFILE%")
        assert browser_cookies.windows_user_home() is None
