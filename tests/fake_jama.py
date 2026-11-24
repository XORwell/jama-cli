"""A fake Jama Connect server for session-auth tests.

Reproduces the behaviour that makes web-session auth tricky:

- ``/login`` hands out an *unauthenticated* ``JSESSIONID``;
- ``j_acegi_security_check`` redirects to ``...login_error...`` on bad credentials;
- a dead session shows up as a 401 with an empty message or as a 302 to the login page;
- a missing permission is also a 401, but with a "permission" message;
- every REST call, reads included, compares the ``jama-csrf-token`` header with
  the session's token; a wrong or missing header is a 401 "CSRF Exception" on a
  session that stays alive;
- a successful DELETE answers 204 with an empty body;
- ``logout.req`` only ends the session when the CSRF header is present;
- one live session per account: a new login invalidates the previous one.

Usable in-process through ``httpx.MockTransport(fake.handle)`` and, for the
browser test, over real HTTP through ``fake.serve()``. It also plays a tiny SAML
identity provider under ``/idp``.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

PERMISSION_MESSAGE = "You don't have permission to delete this item"
CSRF_MESSAGE = "CSRF Exception"


class FakeJama:
    def __init__(
        self,
        context_path: str = "/contour",
        dead_as: str = "401",
        login_delay: float = 0.0,
        sso: bool = False,
        idp_interactive: bool = False,
        csrf_cookie_on_reject: bool = True,
    ) -> None:
        self.ctx = context_path.rstrip("/")
        self.dead_as = dead_as  # "401" or "302"
        self.login_delay = login_delay
        self.sso = sso
        self.idp_interactive = idp_interactive
        # Whether a CSRF rejection tells the client the current token through
        # Set-Cookie. Real Jama's behaviour here is not known; both are covered.
        self.csrf_cookie_on_reject = csrf_cookie_on_reject
        # Extra Set-Cookie pairs added to the next successful REST answer.
        self.rotate_on_next: list[tuple[str, str]] = []
        self.users = {"alice": "s3cret-pw-alice"}
        self.sso_user = "alice"
        # JSESSIONID -> {"user": str | None, "csrf": str}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.login_count = 0
        self.reject_everything = False
        self.requests: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._retiring: str | None = None

    # ----- test controls -------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def kill_sessions(self) -> None:
        """Server-side timeout: every session is gone."""
        with self._lock:
            self.sessions.clear()

    def plant_session(self, user: str = "alice") -> tuple[str, str]:
        """Create one authenticated session and return its ``(JSESSIONID, csrf)``.

        Used to simulate a session the user established elsewhere (e.g. in a real
        browser) without going through the login form.
        """
        with self._lock:
            before = self.login_count
            sid, csrf = self._authenticate(user)
            # A session the user already has is not a login by this CLI.
            self.login_count = before
            return sid, csrf

    def rotate_csrf(self) -> None:
        """Make every client-held CSRF token stale."""
        with self._lock:
            for session in self.sessions.values():
                session["csrf"] = "csrf-" + secrets.token_hex(8)

    def rotate_session_id(self) -> str:
        """Give the one authenticated session a new id, announced on its next answer."""
        with self._lock:
            old = next(sid for sid, data in self.sessions.items() if data["user"])
            new = "auth-" + secrets.token_hex(12)
            self.sessions[new] = self.sessions[old]
            self.rotate_on_next.append(("JSESSIONID", new))
            self._retiring = old
        return new

    def live_secrets(self) -> list[str]:
        """Every secret value the server currently knows (for leak checks)."""
        with self._lock:
            values = list(self.sessions.keys())
            values += [s["csrf"] for s in self.sessions.values()]
        return [v for v in values + list(self.users.values()) if v]

    def is_authenticated(self, jsessionid: str) -> bool:
        with self._lock:
            session = self.sessions.get(jsessionid)
            return bool(session and session["user"])

    # ----- helpers -------------------------------------------------------

    def _cookie(self, name: str, value: str) -> tuple[str, str]:
        return ("set-cookie", f"{name}={value}; Path={self.ctx or '/'}; HttpOnly")

    @staticmethod
    def _cookies(request: httpx.Request) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for part in request.headers.get("cookie", "").split(";"):
            if "=" in part:
                name, value = part.strip().split("=", 1)
                cookies[name] = value
        return cookies

    def _authenticate(self, user: str) -> tuple[str, str]:
        """Create the one live session for a user, dropping any previous one."""
        for sid in [s for s, data in self.sessions.items() if data["user"] == user]:
            del self.sessions[sid]
        sid = "auth-" + secrets.token_hex(12)
        csrf = "csrf-" + secrets.token_hex(8)
        self.sessions[sid] = {"user": user, "csrf": csrf}
        self.login_count += 1
        return sid, csrf

    def _dead(self) -> httpx.Response:
        if self.dead_as == "302":
            return httpx.Response(302, headers={"Location": f"{self.ctx}/login.req"})
        return httpx.Response(401, json={"meta": {"status": "Unauthorized", "message": ""}})

    # ----- request handling ----------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))

        if path.startswith("/idp/"):
            return self._idp(request)
        if not path.startswith(self.ctx + "/"):
            return httpx.Response(404, text="not found")
        route = path[len(self.ctx) :]

        if route.startswith("/rest/v1/"):
            return self._rest(request, route[len("/rest/v1/") :])
        if route == "/login":
            with self._lock:
                sid = "anon-" + secrets.token_hex(12)
                self.sessions[sid] = {"user": None, "csrf": ""}
            return httpx.Response(200, headers=[self._cookie("JSESSIONID", sid)], text="login")
        if route == "/login.req":
            return self._login_page(request)
        if route == "/j_acegi_security_check":
            return self._form_login(request)
        if route == "/saml/login":
            return httpx.Response(302, headers={"Location": "/idp/auth"})
        if route == "/saml/acs":
            with self._lock:
                sid, csrf = self._authenticate(self.sso_user)
            return httpx.Response(
                302,
                headers=[
                    ("Location", f"{self.ctx}/perspective.req"),
                    self._cookie("JSESSIONID", sid),
                    self._cookie("jama-csrf-token", csrf),
                ],
            )
        if route == "/perspective.req":
            return httpx.Response(200, text="<html><body>Jama</body></html>")
        if route == "/logout.req":
            return self._logout(request)
        return httpx.Response(404, text="not found")

    def _login_page(self, request: httpx.Request) -> httpx.Response:
        cookies = self._cookies(request)
        if self.is_authenticated(cookies.get("JSESSIONID", "")):
            return httpx.Response(302, headers={"Location": f"{self.ctx}/perspective.req"})
        with self._lock:
            sid = "anon-" + secrets.token_hex(12)
            self.sessions[sid] = {"user": None, "csrf": ""}
        if self.sso:
            body = (
                "<html><body><form>"
                f'<a id="loginWithSSOButton" href="{self.ctx}/saml/login">Log in with SSO</a>'
                "</form></body></html>"
            )
        else:
            body = (
                f'<html><body><form method="post" action="{self.ctx}/j_acegi_security_check">'
                '<input name="j_username"><input name="j_password" type="password">'
                "</form></body></html>"
            )
        return httpx.Response(
            200,
            headers=[("content-type", "text/html"), self._cookie("JSESSIONID", sid)],
            content=body.encode(),
        )

    def _idp(self, request: httpx.Request) -> httpx.Response:
        if self.idp_interactive:
            body = '<html><body><input type="password" name="passwd"></body></html>'
            return httpx.Response(200, headers={"content-type": "text/html"}, content=body.encode())
        # The IdP remembers the user: straight back to Jama, no interaction.
        return httpx.Response(302, headers={"Location": f"{self.ctx}/saml/acs"})

    def _form_login(self, request: httpx.Request) -> httpx.Response:
        if self.login_delay:
            time.sleep(self.login_delay)
        form = parse_qs(request.content.decode())
        user = form.get("j_username", [""])[0]
        password = form.get("j_password", [""])[0]
        if self.users.get(user) != password or not password:
            return httpx.Response(302, headers={"Location": f"{self.ctx}/login.req?login_error=1"})
        with self._lock:
            sid, csrf = self._authenticate(user)
        return httpx.Response(
            302,
            headers=[
                ("Location", f"{self.ctx}/perspective.req"),
                self._cookie("JSESSIONID", sid),
                self._cookie("jama-csrf-token", csrf),
            ],
        )

    def _logout(self, request: httpx.Request) -> httpx.Response:
        cookies = self._cookies(request)
        sid = cookies.get("JSESSIONID", "")
        with self._lock:
            session = self.sessions.get(sid)
            # Without the CSRF header Jama answers 200 and keeps the session.
            if session and request.headers.get("jama-csrf-token") == session["csrf"]:
                del self.sessions[sid]
        return httpx.Response(200, text="bye")

    def _rest(self, request: httpx.Request, resource: str) -> httpx.Response:
        cookies = self._cookies(request)
        with self._lock:
            session = self.sessions.get(cookies.get("JSESSIONID", ""))
            session = dict(session) if session else None
        if self.reject_everything or not session or not session["user"]:
            return self._dead()

        headers: list[tuple[str, str]] = []
        if cookies.get("jama-csrf-token") != session["csrf"]:
            headers.append(self._cookie("jama-csrf-token", session["csrf"]))
        # The header is checked on every call, reads included.
        if request.headers.get("jama-csrf-token") != session["csrf"]:
            return httpx.Response(
                401,
                headers=headers if self.csrf_cookie_on_reject else [],
                json={"meta": {"status": "Unauthorized", "message": CSRF_MESSAGE}},
            )
        with self._lock:
            for name, value in self.rotate_on_next:
                headers.append(self._cookie(name, value))
            self.rotate_on_next.clear()
            if self._retiring:
                self.sessions.pop(self._retiring, None)
                self._retiring = None

        def ok(data: Any, status: int = 200, **meta: Any) -> httpx.Response:
            body = {"meta": {"status": "OK", **meta}, "data": data}
            return httpx.Response(status, headers=headers, content=json.dumps(body).encode())

        if request.method == "GET" and resource == "users/current":
            return ok({"id": 7, "username": session["user"]})
        if request.method == "GET" and resource == "projects":
            return ok(
                [{"id": 1, "name": "Demo"}],
                pageInfo={"startIndex": 0, "resultCount": 1, "totalResults": 1},
            )
        if request.method == "GET" and resource == "items/1":
            return ok({"id": 1, "fields": {"name": "Item"}})
        if request.method == "POST" and resource == "items":
            return ok(None, status=201, id=101)
        if request.method == "PUT" and resource == "items/1":
            return ok(None)
        if request.method == "DELETE" and resource == "items/1":
            # Real Jama answers a successful delete without a body.
            return httpx.Response(204, headers=headers)
        if request.method == "DELETE" and resource == "items/999":
            return httpx.Response(
                401, json={"meta": {"status": "Unauthorized", "message": PERMISSION_MESSAGE}}
            )
        return httpx.Response(404, json={"meta": {"status": "Not Found", "message": "nope"}})

    # ----- real HTTP (browser test) --------------------------------------

    def serve(self) -> tuple[ThreadingHTTPServer, str]:
        """Serve this fake over real HTTP on a free local port."""
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length) if length else b""
                host = self.headers.get("host", "127.0.0.1")
                request = httpx.Request(
                    self.command,
                    f"http://{host}{self.path}",
                    headers=list(self.headers.items()),
                    content=body,
                )
                response = fake.handle(request)
                payload = response.content
                self.send_response(response.status_code)
                for name, value in response.headers.multi_items():
                    if name.lower() not in ("content-length", "transfer-encoding"):
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _handle  # noqa: N815
            do_POST = _handle  # noqa: N815
            do_PUT = _handle  # noqa: N815
            do_DELETE = _handle  # noqa: N815

            def log_message(self, *args: Any) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        return server, f"http://127.0.0.1:{port}{self.ctx}"


def path_of(url: str) -> str:
    return urlsplit(url).path
