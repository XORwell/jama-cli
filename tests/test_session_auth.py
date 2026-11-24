"""Tests for the browser-session ("SSO cookie") auth mode against a fake Jama."""

from __future__ import annotations

import builtins
import json
import os
import stat
import sys
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from loguru import logger

from jama_cli.config import get_profile_or_env
from jama_cli.core.api import JamaApi
from jama_cli.core.exceptions import CoreException, UnauthorizedException
from jama_cli.core.http_client import JamaHttpClient
from jama_cli.core.session import (
    SessionManager,
    SessionSettings,
    form_login,
    is_auth_rejected,
    is_csrf_rejected,
    is_session_rejected,
    probe,
)
from jama_cli.core.session_store import SessionStore, StoredSession, default_session_file
from jama_cli.core.sync_wrapper import SyncJamaApi
from jama_cli.models import JamaProfile
from tests.fake_jama import CSRF_MESSAGE, PERMISSION_MESSAGE, FakeJama

BASE = "https://jama.example.com/contour"


@pytest.fixture
def fake() -> FakeJama:
    return FakeJama()


@pytest.fixture
def settings(tmp_path: Path) -> SessionSettings:
    return SessionSettings(
        base_url=BASE,
        username="alice",
        password="s3cret-pw-alice",
        login_mode="form",
        session_file=tmp_path / "sessions" / "alice.json",
    )


def make_client(fake: FakeJama, settings: SessionSettings) -> JamaHttpClient:
    transport = fake.transport()
    manager = SessionManager(settings, transport=transport)
    return JamaHttpClient(base_url=BASE, session=manager, transport=transport)


@pytest.fixture
def log_lines() -> Any:
    """Capture everything loguru emits, down to DEBUG."""
    lines: list[str] = []
    sink_id = logger.add(lines.append, level="DEBUG", format="{message}")
    yield lines
    logger.remove(sink_id)


async def logged_in_store(fake: FakeJama, settings: SessionSettings) -> SessionStore:
    """Log in once, save the session, and make any further login impossible."""
    store = SessionStore(settings.store_path)
    store.save(await form_login(settings, fake.transport()))
    settings.password = None
    return store


def tamper(store: SessionStore, **changes: Any) -> None:
    """Edit top-level fields of the session file, as a user with an editor would."""
    data = json.loads(store.path.read_text())
    data.update(changes)
    store.path.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------


class TestSessionStore:
    def _session(self) -> StoredSession:
        return StoredSession(
            base_url=BASE,
            username="alice",
            cookies=[{"name": "JSESSIONID", "value": "sid-secret", "domain": "h", "path": "/"}],
            csrf_token="csrf-secret",
            created_at=1.0,
            last_validated_at=2.0,
        )

    def test_roundtrip_and_contents(self, tmp_path: Path) -> None:
        store = SessionStore(tmp_path / "s" / "a.json")
        store.save(self._session())

        loaded = store.load()
        assert loaded is not None
        assert loaded.same_as(self._session())
        assert loaded.username == "alice"

        on_disk = json.loads(store.path.read_text())
        assert set(on_disk) == {
            "base_url",
            "username",
            "cookies",
            "csrf_token",
            "created_at",
            "last_validated_at",
            "source",
        }
        assert set(on_disk["cookies"][0]) == {"name", "value", "domain", "path"}

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
    def test_file_is_private(self, tmp_path: Path) -> None:
        store = SessionStore(tmp_path / "s" / "a.json")
        store.save(self._session())
        assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600

    def test_atomic_write_leaves_no_temp_files(self, tmp_path: Path) -> None:
        store = SessionStore(tmp_path / "a.json")
        store.save(self._session())
        store.save(self._session())
        assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []

    def test_corrupt_file_is_no_session(self, tmp_path: Path) -> None:
        path = tmp_path / "a.json"
        path.write_text("{not json")
        assert SessionStore(path).load() is None

    def test_repr_has_no_secrets(self) -> None:
        text = repr(self._session())
        assert "sid-secret" not in text
        assert "csrf-secret" not in text

    def test_one_store_per_base_url_and_account(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JAMA_SESSION_DIR", "/tmp/jama-sessions")
        a = default_session_file(BASE, "alice")
        assert a == default_session_file(BASE + "/", "Alice")
        assert a != default_session_file(BASE, "bob")
        assert a != default_session_file("https://other.example.com", "alice")
        assert "alice" not in a.name


# ---------------------------------------------------------------------------
# Fake-server behaviour the client relies on
# ---------------------------------------------------------------------------


class TestLoginAndProbe:
    async def test_login_page_cookie_is_not_a_session(self, fake: FakeJama) -> None:
        async with httpx.AsyncClient(transport=fake.transport()) as client:
            response = await client.get(f"{BASE}/login")
            sid = client.cookies.get("JSESSIONID")
        assert response.status_code == 200 and sid

        anonymous = StoredSession(
            base_url=BASE, cookies=[{"name": "JSESSIONID", "value": sid, "domain": "", "path": "/"}]
        )
        result = await probe(BASE, anonymous, fake.transport())
        assert result.ok is False

    async def test_form_login(self, fake: FakeJama, settings: SessionSettings) -> None:
        session = await form_login(settings, fake.transport())
        assert session.username == "alice"
        assert session.csrf_token
        assert fake.is_authenticated(session.cookie_value("JSESSIONID") or "")
        assert session.last_validated_at >= session.created_at > 0

    async def test_form_login_wrong_password(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        settings.password = "wrong-password-value"
        with pytest.raises(UnauthorizedException) as exc:
            await form_login(settings, fake.transport())
        assert "rejected" in str(exc.value)
        assert "wrong-password-value" not in str(exc.value)

    async def test_new_login_invalidates_previous_session(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        first = await form_login(settings, fake.transport())
        second = await form_login(settings, fake.transport())
        assert (await probe(BASE, first, fake.transport())).ok is False
        assert (await probe(BASE, second, fake.transport())).ok is True

    def test_rejection_rules(self) -> None:
        def resp(code: int, **kwargs: Any) -> httpx.Response:
            return httpx.Response(code, **kwargs)

        assert is_session_rejected(resp(401, json={"meta": {"message": ""}}))
        assert is_session_rejected(resp(401, text=""))
        assert is_session_rejected(resp(302, headers={"Location": "/contour/login.req"}))
        assert is_session_rejected(resp(302, headers={"Location": "https://idp/saml/sso"}))
        assert is_session_rejected(resp(302, headers={"Location": "/j_acegi_security_check"}))
        assert not is_session_rejected(resp(401, json={"meta": {"message": PERMISSION_MESSAGE}}))
        assert not is_session_rejected(resp(302, headers={"Location": "/contour/other"}))
        assert not is_session_rejected(resp(404, json={"meta": {"message": "x"}}))

    def test_csrf_rejection_is_not_a_dead_session(self) -> None:
        def resp(message: str, code: int = 401) -> httpx.Response:
            return httpx.Response(code, json={"meta": {"message": message}})

        for message in (CSRF_MESSAGE, "csrf exception", "Invalid CSRF token"):
            assert is_csrf_rejected(resp(message))
            assert not is_session_rejected(resp(message))
            assert is_auth_rejected(resp(message))
        assert not is_csrf_rejected(resp(""))
        assert not is_csrf_rejected(resp(PERMISSION_MESSAGE))
        assert not is_auth_rejected(resp(PERMISSION_MESSAGE))
        assert not is_csrf_rejected(resp(CSRF_MESSAGE, code=403))
        assert is_auth_rejected(resp(""))


# ---------------------------------------------------------------------------
# HTTP client behaviour
# ---------------------------------------------------------------------------


class TestSessionClient:
    async def test_first_request_logs_in_and_stores(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        async with make_client(fake, settings) as client:
            user = await client.get("users/current")
        assert user["data"]["username"] == "alice"
        assert fake.login_count == 1
        assert SessionStore(settings.store_path).load() is not None

    async def test_session_from_store_is_reused_without_login(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        session = await form_login(settings, fake.transport())
        SessionStore(settings.store_path).save(session)
        assert fake.login_count == 1

        # A different process: it only knows the store, and may not log in.
        settings.password = None
        async with make_client(fake, settings) as client:
            projects = await client.get_all("projects")
        assert projects == [{"id": 1, "name": "Demo"}]
        assert fake.login_count == 1

    @pytest.mark.parametrize("dead_as", ["401", "302"])
    async def test_dead_session_triggers_one_relogin(
        self, settings: SessionSettings, dead_as: str
    ) -> None:
        fake = FakeJama(dead_as=dead_as)
        async with make_client(fake, settings) as client:
            await client.get("users/current")
            fake.kill_sessions()
            user = await client.get("users/current")
        assert user["data"]["username"] == "alice"
        assert fake.login_count == 2

    async def test_permission_401_is_surfaced_not_retried(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        async with make_client(fake, settings) as client:
            await client.get("users/current")
            before = len(fake.requests)
            with pytest.raises(UnauthorizedException) as exc:
                await client.delete("items/999")
        assert "permission" in str(exc.value)
        assert fake.login_count == 1
        # Exactly the one DELETE: no CSRF refresh, no re-login, no retry.
        assert fake.requests[before:] == [("DELETE", "/contour/rest/v1/items/999")]

    async def test_stale_csrf_self_heals(self, fake: FakeJama, settings: SessionSettings) -> None:
        async with make_client(fake, settings) as client:
            await client.get("users/current")
            fake.rotate_csrf()
            created = await client.post("items", json={"fields": {"name": "x"}})
        assert created["meta"]["id"] == 101
        assert fake.login_count == 1

        # The refreshed token is shared with other processes through the store.
        stored = SessionStore(settings.store_path).load()
        assert stored is not None
        assert stored.csrf_token in fake.live_secrets()
        assert stored.cookie_value("jama-csrf-token") == stored.csrf_token

    async def test_write_on_dead_session_relogs_in(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        async with make_client(fake, settings) as client:
            await client.get("users/current")
            fake.kill_sessions()
            created = await client.post("items", json={"fields": {"name": "x"}})
        assert created["meta"]["id"] == 101
        assert fake.login_count == 2

    async def test_picks_up_session_written_by_another_process(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        async with make_client(fake, settings) as client:
            await client.get("users/current")
            assert fake.login_count == 1

            # Another process logs in: Jama invalidates our session ("one live
            # session per account") and the new one lands in the shared store.
            other = SessionManager(settings, transport=fake.transport())
            await other.login(force=True)
            assert fake.login_count == 2

            user = await client.get("users/current")
        assert user["data"]["username"] == "alice"
        assert fake.login_count == 2  # adopted, not logged in again

    async def test_never_loops_when_login_does_not_help(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        async with make_client(fake, settings) as client:
            await client.get("users/current")
            fake.reject_everything = True
            logins: list[int] = []

            async def login_once(_settings: SessionSettings, _mode: str) -> StoredSession:
                logins.append(1)
                fake.reject_everything = False
                session = await form_login(settings, fake.transport())
                fake.reject_everything = True
                return session

            assert client.session is not None
            client.session._login_func = login_once
            with pytest.raises(UnauthorizedException) as exc:
                await client.get("users/current")
        assert "jama login" in str(exc.value)
        assert logins == [1]

    async def test_interactive_never_fails_with_hint(
        self, fake: FakeJama, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_browser(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("a browser must not be started with login_interactive=never")

        monkeypatch.setattr("jama_cli.core.browser_login.browser_login", no_browser)
        settings = SessionSettings(
            base_url=BASE,
            login_mode="browser",
            login_interactive="never",
            session_file=tmp_path / "s.json",
        )
        async with make_client(fake, settings) as client:
            with pytest.raises(UnauthorizedException) as exc:
                await client.get("users/current")
        assert "jama login" in str(exc.value)
        assert fake.login_count == 0

    def test_two_concurrent_clients_log_in_exactly_once(self, settings: SessionSettings) -> None:
        fake = FakeJama(login_delay=0.3)
        barrier = threading.Barrier(2)
        results: list[Any] = []

        def worker() -> None:
            transport = fake.transport()
            http = JamaHttpClient(
                base_url=BASE,
                session=SessionManager(settings, transport=transport),
                transport=transport,
            )
            api = SyncJamaApi(JamaApi(http), http)
            try:
                barrier.wait(timeout=5)
                results.append(api.get_current_user())
            except Exception as e:  # pragma: no cover - failure path
                results.append(e)
            finally:
                api.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert [r["username"] for r in results] == ["alice", "alice"]
        assert fake.login_count == 1

    async def test_concurrent_requests_in_one_process_log_in_once(
        self, settings: SessionSettings
    ) -> None:
        import asyncio

        fake = FakeJama()
        async with make_client(fake, settings) as client:
            users = await asyncio.gather(*(client.get("users/current") for _ in range(5)))
        assert all(u["data"]["username"] == "alice" for u in users)
        assert fake.login_count == 1


# ---------------------------------------------------------------------------
# logout / status
# ---------------------------------------------------------------------------


class TestCsrfRepair:
    """Jama checks the CSRF header on every call; a wrong one is not a dead session."""

    @pytest.mark.parametrize("bad_token", ["wrong-token", ""])
    async def test_read_with_bad_header_is_repaired_without_login(
        self, fake: FakeJama, settings: SessionSettings, bad_token: str
    ) -> None:
        store = await logged_in_store(fake, settings)
        tamper(store, csrf_token=bad_token)

        async with make_client(fake, settings) as client:
            item = await client.get("items/1")

        assert item["data"]["id"] == 1
        assert fake.login_count == 1
        # The file is correct again, so the next process does not hit the problem.
        repaired = store.load()
        assert repaired is not None
        assert repaired.csrf_token == repaired.cookie_value("jama-csrf-token")
        assert repaired.csrf_token in fake.live_secrets()

    async def test_write_with_bad_header_is_repaired_without_login(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        store = await logged_in_store(fake, settings)
        tamper(store, csrf_token="wrong-token")

        async with make_client(fake, settings) as client:
            created = await client.post("items", json={"fields": {"name": "x"}})
            await client.put("items/1", json={"fields": {"name": "y"}})

        assert created["meta"]["id"] == 101
        assert fake.login_count == 1
        assert fake.requests.count(("POST", "/contour/rest/v1/items")) == 2

    async def test_repair_takes_one_retry_and_no_probe(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        store = await logged_in_store(fake, settings)
        tamper(store, csrf_token="wrong-token")

        async with make_client(fake, settings) as client:
            before = len(fake.requests)
            await client.get("items/1")

        assert fake.requests[before:] == [("GET", "/contour/rest/v1/items/1")] * 2

    @pytest.mark.parametrize("method", ["GET", "POST"])
    async def test_token_replaced_by_server_is_repaired_without_login(
        self, fake: FakeJama, settings: SessionSettings, method: str
    ) -> None:
        store = await logged_in_store(fake, settings)
        async with make_client(fake, settings) as client:
            await client.get("users/current")
            # Header and cookie are both stale now.
            fake.rotate_csrf()
            if method == "GET":
                await client.get("items/1")
            else:
                await client.post("items", json={"fields": {"name": "x"}})

        assert fake.login_count == 1
        stored = store.load()
        assert stored is not None
        assert stored.csrf_token in fake.live_secrets()

    async def test_unrepairable_token_ends_with_login_hint_not_a_loop(
        self, settings: SessionSettings
    ) -> None:
        # This server never tells the client the new token.
        fake = FakeJama(csrf_cookie_on_reject=False)
        await logged_in_store(fake, settings)
        logins: list[str] = []

        async def no_login(_settings: SessionSettings, mode: str) -> StoredSession:
            logins.append(mode)
            raise UnauthorizedException("No valid Jama session. Run `jama login` to sign in.")

        async with make_client(fake, settings) as client:
            await client.get("users/current")
            fake.rotate_csrf()
            assert client.session is not None
            client.session._login_func = no_login
            before = len(fake.requests)
            with pytest.raises(UnauthorizedException) as exc:
                await client.get("items/1")

        assert "jama login" in str(exc.value)
        assert logins == ["auto"]
        # The request, one probe (users/current, then the projects fallback is
        # skipped because the answer was a rejection), nothing else.
        assert fake.requests[before:] == [
            ("GET", "/contour/rest/v1/items/1"),
            ("GET", "/contour/rest/v1/users/current"),
        ]

    async def test_dead_session_still_needs_a_login(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        settings.login_interactive = "never"
        settings.login_mode = "browser"
        store = SessionStore(settings.store_path)
        login_settings = SessionSettings(
            base_url=BASE, username="alice", password="s3cret-pw-alice", login_mode="form"
        )
        store.save(await form_login(login_settings, fake.transport()))
        fake.kill_sessions()

        async with make_client(fake, settings) as client:
            with pytest.raises(UnauthorizedException) as exc:
                await client.get("items/1")
        assert "Run `jama login`" in str(exc.value)

    async def test_permission_401_with_bad_header_free_session_never_logs_in(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        await logged_in_store(fake, settings)
        async with make_client(fake, settings) as client:
            before = len(fake.requests)
            with pytest.raises(UnauthorizedException) as exc:
                await client.delete("items/999")
        assert "permission" in str(exc.value)
        assert fake.login_count == 1
        assert fake.requests[before:] == [("DELETE", "/contour/rest/v1/items/999")]

    async def test_probe_repairs_bad_header(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        store = await logged_in_store(fake, settings)
        tamper(store, csrf_token="wrong-token")
        manager = SessionManager(settings, transport=fake.transport())

        status = await manager.status()

        assert status["valid"] is True
        stored = store.load()
        assert stored is not None
        assert stored.csrf_token in fake.live_secrets()

    async def test_no_secrets_in_logs_or_errors_during_repair(
        self, settings: SessionSettings, log_lines: list[str]
    ) -> None:
        fake = FakeJama(csrf_cookie_on_reject=False)
        store = await logged_in_store(fake, settings)
        secrets_before = fake.live_secrets()
        tamper(store, csrf_token="wrong-token-value")

        errors: list[str] = []
        async with make_client(fake, settings) as client:
            await client.get("items/1")  # repaired from the cookie
            fake.rotate_csrf()  # not repairable on this server
            try:
                await client.post("items", json={"fields": {"name": "x"}})
            except (UnauthorizedException, CoreException) as e:
                errors.append(f"{e} {e!r}")

        assert errors, "the unrepairable write should have failed"
        text = "\n".join(log_lines + errors)
        for secret in secrets_before + fake.live_secrets() + ["wrong-token-value"]:
            assert secret not in text


class TestResponseCookies:
    """Set-Cookie of ordinary answers is taken over, not only that of the probe."""

    async def test_replaced_session_id_is_adopted_and_saved(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        store = await logged_in_store(fake, settings)
        async with make_client(fake, settings) as client:
            await client.get("items/1")
            new_id = fake.rotate_session_id()
            await client.get("items/1")  # answer carries the new JSESSIONID
            await client.get("items/1")  # old id is gone on the server now

        assert fake.login_count == 1
        stored = store.load()
        assert stored is not None
        assert stored.cookie_value("JSESSIONID") == new_id
        if sys.platform != "win32":
            assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600

    async def test_cookies_of_a_dead_session_answer_are_ignored(
        self, settings: SessionSettings
    ) -> None:
        fake = FakeJama()
        store = await logged_in_store(fake, settings)
        manager = SessionManager(settings, transport=fake.transport())
        session = manager.current()
        assert session is not None
        good_id = session.cookie_value("JSESSIONID")

        dead = httpx.Response(
            401,
            headers={"set-cookie": "JSESSIONID=anonymous-id; Path=/contour"},
            json={"meta": {"message": ""}},
            request=httpx.Request("GET", BASE + "/rest/v1/items/1"),
        )
        await manager.absorb(session, dead)

        assert session.cookie_value("JSESSIONID") == good_id
        stored = store.load()
        assert stored is not None and stored.cookie_value("JSESSIONID") == good_id

    async def test_update_does_not_overwrite_a_newer_login_or_undo_a_logout(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        store = SessionStore(settings.store_path)
        ours = await form_login(settings, fake.transport())
        store.save(ours)
        manager = SessionManager(settings, transport=fake.transport())

        newer = await form_login(settings, fake.transport())
        store.save(newer)
        ours.set_csrf("some-other-token")
        assert await manager.persist(ours) is False
        stored = store.load()
        assert stored is not None and stored.same_as(newer)

        store.delete()
        assert await manager.persist(ours) is False
        assert store.load() is None


class TestEmptyBodies:
    async def test_delete_with_empty_answer_returns_empty_dict(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        async with make_client(fake, settings) as client:
            assert await client.delete("items/1") == {}

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    async def test_write_helpers_accept_204_with_any_auth(self, method: str) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(204))
        async with JamaHttpClient(BASE, ("user", "pw"), transport=transport) as client:
            assert await getattr(client, method)("items/1") == {}

    async def test_api_delete_item_reports_success(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(204))
        async with JamaHttpClient(BASE, ("user", "pw"), transport=transport) as client:
            assert await JamaApi(client).delete_item(1) in (200, 204)


class TestLogoutAndStatus:
    async def test_logout_needs_csrf_header(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        session = await form_login(settings, fake.transport())
        sid = session.cookie_value("JSESSIONID") or ""

        async with httpx.AsyncClient(transport=fake.transport()) as client:
            response = await client.get(
                f"{BASE}/logout.req", headers={"Cookie": session.cookie_header()}
            )
        assert response.status_code == 200
        assert fake.is_authenticated(sid)  # 200, but the seat is still held

    async def test_logout_ends_session_and_deletes_store(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        manager = SessionManager(settings, transport=fake.transport())
        session = await manager.login()
        sid = session.cookie_value("JSESSIONID") or ""
        assert settings.store_path.exists()

        result = await manager.logout()
        assert result.had_session is True
        assert result.server_session_ended is True
        assert result.source == "form"
        assert not fake.is_authenticated(sid)
        assert not settings.store_path.exists()
        assert (await manager.logout()).had_session is False

    async def test_status_has_no_secrets(self, fake: FakeJama, settings: SessionSettings) -> None:
        manager = SessionManager(settings, transport=fake.transport())
        assert (await manager.status())["logged_in"] is False

        await manager.login()
        info = await manager.status()
        assert info["valid"] is True
        assert info["username"] == "alice"
        assert info["base_url"] == BASE
        assert info["age_seconds"] is not None
        dumped = json.dumps(info)
        for secret in fake.live_secrets():
            assert secret not in dumped

        fake.kill_sessions()
        info = await manager.status()
        assert info["logged_in"] is True and info["valid"] is False

    async def test_login_reuses_valid_session(
        self, fake: FakeJama, settings: SessionSettings
    ) -> None:
        manager = SessionManager(settings, transport=fake.transport())
        await manager.login()
        await manager.login()
        assert fake.login_count == 1


# ---------------------------------------------------------------------------
# Secrets never leak
# ---------------------------------------------------------------------------


async def test_no_secret_in_logs_or_exceptions(
    fake: FakeJama, settings: SessionSettings, log_lines: list[str]
) -> None:
    secrets_seen: set[str] = set()
    errors: list[str] = []

    async with make_client(fake, settings) as client:
        await client.get("users/current")
        secrets_seen.update(fake.live_secrets())

        fake.rotate_csrf()
        await client.post("items", json={"fields": {"name": "x"}})
        secrets_seen.update(fake.live_secrets())

        fake.kill_sessions()
        await client.get("users/current")
        secrets_seen.update(fake.live_secrets())

        try:
            await client.delete("items/999")
        except UnauthorizedException as e:
            errors.append(f"{e!s} {e!r}")

        assert client.session is not None
        errors.append(repr(client.session.current()))
        errors.append(repr(client.session.settings))

        fake.kill_sessions()
        settings.password = "another-wrong-password"
        try:
            await client.get("users/current")
        except UnauthorizedException as e:
            errors.append(f"{e!s} {e!r}")
    secrets_seen.add("another-wrong-password")

    assert len(errors) == 4
    haystack = "\n".join(log_lines + errors)
    assert log_lines, "expected some log output"
    for secret in secrets_seen:
        assert secret not in haystack


# ---------------------------------------------------------------------------
# Config and existing auth modes
# ---------------------------------------------------------------------------

_JAMA_ENV = [
    "JAMA_URL",
    "JAMA_API_KEY",
    "JAMA_CLIENT_ID",
    "JAMA_CLIENT_SECRET",
    "JAMA_USERNAME",
    "JAMA_PASSWORD",
    "JAMA_AUTH_TYPE",
    "JAMA_LOGIN_MODE",
    "JAMA_LOGIN_INTERACTIVE",
    "JAMA_LOGIN_TIMEOUT",
    "JAMA_SSO_SELECTORS",
    "JAMA_BROWSER_CHANNEL",
    "JAMA_SESSION_FILE",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    for name in _JAMA_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JAMA_CONFIG", str(tmp_path / "config.yml"))
    monkeypatch.setattr("jama_cli.config.CONFIG_FILE", tmp_path / "config.yml")
    monkeypatch.chdir(tmp_path)
    return monkeypatch


class TestConfig:
    def test_session_profile_from_env(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("JAMA_URL", "https://host.example.com/contour/")
        clean_env.setenv("JAMA_AUTH_TYPE", "session")
        clean_env.setenv("JAMA_LOGIN_INTERACTIVE", "never")
        clean_env.setenv("JAMA_LOGIN_TIMEOUT", "45")
        clean_env.setenv("JAMA_SSO_SELECTORS", "#a, .b")
        clean_env.setenv("JAMA_BROWSER_CHANNEL", "msedge")

        profile = get_profile_or_env()
        assert profile is not None
        assert profile.auth_type == "session"
        assert profile.has_valid_credentials()

        settings = profile.session_settings()
        assert settings.base_url == "https://host.example.com/contour"
        assert settings.login_interactive == "never"
        assert settings.login_timeout == 45
        assert settings.sso_selectors == ("#a", ".b")
        assert settings.browser_channel == "msedge"
        assert settings.login_mode == "browser"

    def test_env_overrides_profile_session_settings(self, clean_env: pytest.MonkeyPatch) -> None:
        Path("config.yml").write_text(
            "default_profile: sso\n"
            "profiles:\n"
            "  sso:\n"
            "    url: https://host.example.com\n"
            "    auth_type: session\n"
            "    login_interactive: always\n"
            "    browser_channel: chrome\n"
        )
        clean_env.setenv("JAMA_LOGIN_INTERACTIVE", "never")

        profile = get_profile_or_env()
        assert profile is not None and profile.auth_type == "session"
        assert profile.login_interactive == "never"  # env wins
        assert profile.browser_channel == "chrome"  # file value kept

    @pytest.mark.parametrize(
        ("env", "expected"),
        [
            ({"JAMA_API_KEY": "k"}, "api_key"),
            ({"JAMA_CLIENT_ID": "i", "JAMA_CLIENT_SECRET": "s"}, "oauth"),
            ({"JAMA_USERNAME": "u", "JAMA_PASSWORD": "p"}, "basic"),
        ],
    )
    def test_existing_env_detection_unchanged(
        self, clean_env: pytest.MonkeyPatch, env: dict[str, str], expected: str
    ) -> None:
        clean_env.setenv("JAMA_URL", "https://host.example.com")
        for name, value in env.items():
            clean_env.setenv(name, value)
        profile = get_profile_or_env()
        assert profile is not None and profile.auth_type == expected

    def test_default_profile_is_still_api_key(self) -> None:
        profile = JamaProfile(url="https://host.example.com", api_key="k")
        assert profile.auth_type == "api_key"
        assert profile.has_valid_credentials()


class TestExistingAuthModesUnchanged:
    async def test_basic_auth_sends_authorization_and_no_cookies(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"data": {"id": 1}})

        async with JamaHttpClient(
            base_url=BASE, credentials=("user", "pw"), transport=httpx.MockTransport(handler)
        ) as client:
            assert client.session is None
            await client.get("users/current")

        assert seen[0].headers["authorization"].startswith("Basic ")
        assert "cookie" not in seen[0].headers
        assert "jama-csrf-token" not in seen[0].headers

    async def test_basic_auth_401_is_not_retried(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(401, json={"meta": {"message": ""}})

        async with JamaHttpClient(
            base_url=BASE, credentials=("user", "pw"), transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(UnauthorizedException):
                await client.get("users/current")
        assert len(calls) == 1

    async def test_oauth_uses_bearer_token(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path.endswith("/rest/oauth/token"):
                return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
            return httpx.Response(200, json={"data": {}})

        async with JamaHttpClient(
            base_url=BASE,
            credentials=("id", "secret"),
            oauth=True,
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.get("users/current")

        assert seen[-1].headers["authorization"] == "Bearer tok"
        assert "cookie" not in seen[-1].headers


# ---------------------------------------------------------------------------
# MCP tools and optional Playwright
# ---------------------------------------------------------------------------


class TestMcpSessionTools:
    async def _server(self, fake: FakeJama, settings: SessionSettings) -> Any:
        from jama_mcp_server.core.stdio_server import JamaStdioMCPServer
        from jama_mcp_server.models import JamaConfig

        server = JamaStdioMCPServer(JamaConfig(url=BASE), session_settings=settings)
        transport = fake.transport()
        server._session = SessionManager(settings, transport=transport)
        server._http = JamaHttpClient(base_url=BASE, session=server._session, transport=transport)
        server._api = JamaApi(server._http)
        return server

    async def test_status_and_logout_tools(self, fake: FakeJama, settings: SessionSettings) -> None:
        server = await self._server(fake, settings)
        try:
            assert (await server._execute_tool("get_current_user", {}))["username"] == "alice"

            status = await server._execute_tool("get_session_status", {})
            assert status["auth_type"] == "session"
            assert status["session"]["valid"] is True
            assert status["session"]["username"] == "alice"
            for secret in fake.live_secrets():
                assert secret not in json.dumps(status)

            result = await server._execute_tool("logout_session", {})
            assert result == {
                "logged_out": True,
                "had_session": True,
                "source": "form",
                "server_session_ended": True,
                "browser_session_still_active": False,
            }
            assert not settings.store_path.exists()
            assert not any(s["user"] for s in fake.sessions.values())
        finally:
            await server._http.close()

    async def test_tools_without_session_auth(self) -> None:
        from jama_mcp_server.core.stdio_server import JamaStdioMCPServer
        from jama_mcp_server.models import JamaConfig

        server = JamaStdioMCPServer(JamaConfig(url=BASE, api_key="k"))
        await server.initialize_client()
        try:
            status = await server._execute_tool("get_session_status", {})
            assert status == {"auth_type": "credentials", "session": None}
            with pytest.raises(ValueError):
                await server._execute_tool("logout_session", {})
        finally:
            await server._http.close()


async def test_missing_playwright_gives_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jama_cli.core.browser_login import browser_login

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("playwright"):
            raise ImportError("No module named 'playwright'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    settings = SessionSettings(base_url=BASE, browser_profile_dir=tmp_path / "profile")
    with pytest.raises(CoreException) as exc:
        await browser_login(settings)
    assert "jama-cli[browser]" in str(exc.value)
    assert "playwright install chromium" in str(exc.value)
