"""Tests for reusing the browser's Jama session (``jama login --from-browser``).

Firefox is exercised against a real (temporary) ``cookies.sqlite``; Chrome/Edge
against a mocked Windows helper, so neither test needs a browser or Windows.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import pytest

from jama_cli.core.browser_cookies import (
    BROWSERS,
    BrowserCookieError,
    ChromiumPaths,
    host_matches,
    normalise_source,
    read_browser_session,
    read_chromium,
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


def make_chromium_db(path: Path, cookies: list[tuple[str, bytes, str]]) -> None:
    """Write a minimal Chromium Cookies db with (name, encrypted_value, host) rows."""
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE cookies "
        "(name TEXT, encrypted_value BLOB, host_key TEXT, path TEXT, is_secure INTEGER)"
    )
    conn.executemany(
        "INSERT INTO cookies (name, encrypted_value, host_key, path, is_secure) "
        "VALUES (?, ?, ?, '/', 1)",
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
        assert normalise_source("browser-chrome") == "chrome"
        assert normalise_source("EDGE") == "edge"
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
# Chrome / Edge (encrypted; helper mocked)
# ---------------------------------------------------------------------------


class TestChromium:
    def _paths(self, tmp_path: Path) -> ChromiumPaths:
        cookies_db = tmp_path / "Cookies"
        make_chromium_db(
            cookies_db,
            [
                ("JSESSIONID", b"v10enc-sid", HOST),
                ("jama-csrf-token", b"v10enc-csrf", HOST),
                ("other", b"v10enc-x", "other.com"),
            ],
        )
        local_state = tmp_path / "Local State"
        key = base64.b64encode(b"DPAPI" + b"\x01" * 32).decode()
        local_state.write_text(json.dumps({"os_crypt": {"encrypted_key": key}}))
        return ChromiumPaths(cookies_db=cookies_db, local_state=local_state)

    def test_helper_receives_only_the_two_blobs_and_the_key(self, tmp_path: Path) -> None:
        paths = self._paths(tmp_path)
        seen: dict[str, object] = {}

        def fake_helper(payload: dict[str, object]) -> str:
            seen.update(payload)
            cookies = payload["cookies"]
            assert set(cookies) == {"JSESSIONID", "jama-csrf-token"}  # not "other"
            # The helper would decrypt; here we just hand back fixed plaintext.
            return json.dumps({"JSESSIONID": "sid-abc", "jama-csrf-token": "csrf-xyz"})

        session = read_chromium(BASE, paths, helper_runner=fake_helper)
        assert session.cookie_value("JSESSIONID") == "sid-abc"
        assert session.csrf_token == "csrf-xyz"
        assert "encrypted_key" in seen
        # The blobs are passed as base64, decoding to the stored bytes.
        assert base64.b64decode(seen["cookies"]["JSESSIONID"]) == b"v10enc-sid"  # type: ignore[index]

    def test_helper_failure_is_a_clear_error(self, tmp_path: Path) -> None:
        paths = self._paths(tmp_path)

        def bad_helper(payload: dict[str, object]) -> str:
            return "not json"

        with pytest.raises(BrowserCookieError):
            read_chromium(BASE, paths, helper_runner=bad_helper)

    def test_missing_cookie_does_not_call_the_helper(self, tmp_path: Path) -> None:
        cookies_db = tmp_path / "Cookies"
        make_chromium_db(cookies_db, [("jama-csrf-token", b"v10enc", HOST)])
        (tmp_path / "Local State").write_text(
            json.dumps({"os_crypt": {"encrypted_key": base64.b64encode(b"DPAPIk").decode()}})
        )
        paths = ChromiumPaths(cookies_db=cookies_db, local_state=tmp_path / "Local State")

        called = False

        def helper(payload: dict[str, object]) -> str:
            nonlocal called
            called = True
            return "{}"

        with pytest.raises(BrowserCookieError):
            read_chromium(BASE, paths, helper_runner=helper)
        assert called is False


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

    def test_all_browsers_are_known(self) -> None:
        assert set(BROWSERS) == {"firefox", "chrome", "edge"}
