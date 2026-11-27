"""Async HTTP client for the Jama REST API.

Replaces py_jama_rest_client with a native async implementation using httpx.
Handles authentication (basic, API key, OAuth), pagination, retry on 429,
and maps HTTP status codes to typed exceptions.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from loguru import logger

from jama_cli.core.exceptions import (
    AlreadyExistsException,
    APIClientException,
    APIException,
    APIServerException,
    CoreException,
    ReadOnlyModeError,
    ResourceNotFoundException,
    TooManyRequestsException,
    UnauthorizedException,
)
from jama_cli.core.read_only import SAFE_METHODS, refusal_message
from jama_cli.core.session import LOGIN_HINT, SessionManager, is_auth_rejected, is_csrf_rejected
from jama_cli.core.session_store import StoredSession

# Jama API max page size
MAX_PAGE_SIZE = 50


class JamaHttpClient:
    """Async HTTP client for the Jama REST API.

    Supports four auth modes:
    - basic: username + password
    - api_key: API key as username, empty password
    - oauth: client_credentials grant with proactive token refresh
    - session: cookies of a Jama web session (pass ``session``), shared with
      other processes through the session store and repaired when it dies

    With ``read_only=True`` every request other than GET/HEAD/OPTIONS raises
    :class:`ReadOnlyModeError` before it is sent. Authentication (OAuth token,
    session login and logout) uses its own requests and is not affected.
    """

    def __init__(
        self,
        base_url: str,
        credentials: tuple[str, str] = ("", ""),
        oauth: bool = False,
        timeout: float = 30.0,
        page_size: int = MAX_PAGE_SIZE,
        session: SessionManager | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        read_only: bool = False,
    ) -> None:
        self._read_only = read_only
        self._base_url = base_url.rstrip("/")
        self._api_url = f"{self._base_url}/rest/v1/"
        self._credentials = credentials
        self._oauth = oauth
        self._page_size = min(page_size, MAX_PAGE_SIZE)

        # OAuth token state
        self._token: str | None = None
        self._token_expires_at: float = 0

        # httpx client (created lazily or via context manager)
        self._session = session
        auth = None if (oauth or session) else httpx.BasicAuth(*credentials)
        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            auth=auth,
            timeout=timeout,
            headers={"Accept": "application/json"},
            transport=transport,
            # Redirects stay manual: in session mode a redirect to the login
            # page is how a dead session shows up.
            follow_redirects=False,
        )

    # --- Lifecycle ---

    async def __aenter__(self) -> JamaHttpClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # --- OAuth ---

    async def _ensure_token(self) -> None:
        """Refresh OAuth token if expired or about to expire (within 60s)."""
        if not self._oauth:
            return
        if self._token and time.time() < self._token_expires_at - 60:
            return
        await self._refresh_token()

    async def _refresh_token(self) -> None:
        """Fetch a new OAuth bearer token via client_credentials grant."""
        token_url = f"{self._base_url}/rest/oauth/token"
        time_before = time.time()

        try:
            response = await self._client.post(
                token_url,
                data={"grant_type": "client_credentials"},
                auth=httpx.BasicAuth(*self._credentials),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise UnauthorizedException(
                f"OAuth token request failed: {e}",
                status_code=e.response.status_code,
            ) from e
        except httpx.HTTPError as e:
            raise CoreException(f"OAuth token request failed: {e}") from e

        data = response.json()
        self._token = data["access_token"]
        self._token_expires_at = math.floor(time_before) + data["expires_in"]
        logger.debug("OAuth token refreshed")

    # --- Core HTTP ---

    async def _request(
        self,
        method: str,
        path: str,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an HTTP request with auth, status mapping, and 429 retry.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            path: API resource path (e.g. "projects", "items/123")
            max_retries: Max retries on 429
            **kwargs: Passed to httpx (params, json, content, headers, etc.)

        Returns:
            httpx.Response

        Raises:
            Typed exceptions for non-2xx responses
            ReadOnlyModeError: a write in read-only mode (nothing is sent)
        """
        if self._read_only and method.upper() not in SAFE_METHODS:
            raise ReadOnlyModeError(refusal_message(f"{method.upper()} {path}"))

        if self._oauth:
            await self._ensure_token()

        for attempt in range(max_retries + 1):
            try:
                # Set OAuth bearer header per-request
                if self._oauth and self._token:
                    headers = kwargs.pop("headers", {})
                    headers["Authorization"] = f"Bearer {self._token}"
                    kwargs["headers"] = headers

                if self._session is not None:
                    response = await self._session_request(method, path, **kwargs)
                else:
                    response = await self._client.request(method, path, **kwargs)

                if response.status_code == 429:
                    if attempt < max_retries:
                        retry_after = float(response.headers.get("Retry-After", 2**attempt))
                        logger.warning(
                            f"Rate limited, retrying in {retry_after}s (attempt {attempt + 1})"
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    self._raise_for_status(response)

                self._raise_for_status(response)
                return response

            except httpx.HTTPError as e:
                if attempt < max_retries and "429" not in str(e):
                    raise
                raise CoreException(f"HTTP request failed: {e}") from e

        # Should not reach here, but satisfy type checker
        raise CoreException("Max retries exceeded")

    @property
    def read_only(self) -> bool:
        """Whether this client refuses every request that could change Jama."""
        return self._read_only

    # --- Session auth ---

    @property
    def session(self) -> SessionManager | None:
        """The session manager when running with ``auth_type=session``."""
        return self._session

    async def _send_with_session(
        self, session: StoredSession, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        """Send one request authenticated with the given web session.

        Cookies the server sets in its answer are taken over into the session
        (and saved), so a token or session id replaced by Jama is not lost.
        """
        manager = self._session
        assert manager is not None
        headers = dict(kwargs.pop("headers", None) or {})
        headers.update(session.auth_headers())
        try:
            response = await self._client.request(method, path, headers=headers, **kwargs)
        finally:
            # The session object is the single source of truth for cookies;
            # never let httpx replay cookies it collected on its own.
            self._client.cookies.clear()
        await manager.absorb(session, response)
        return response

    async def _session_request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send a request with the web session, repairing the session if needed.

        Jama checks the CSRF header on every call, reads included. A 401 that
        mentions "csrf" is a token problem on a live session; a 401 with an
        empty message or a redirect to the login page is a dead session. When a
        request is not accepted, the following steps run in order, each at most
        once per request:

        1. CSRF repair (any method):
           a. take the token from the ``jama-csrf-token`` cookie if it differs
              from the header that was sent, and retry;
           b. fetch the current token with one GET and retry. This also runs
              for a write that was rejected without a CSRF message. If that
              GET is accepted, the session is alive and the retry's answer is
              final; steps 2 and 3 only run when the GET is rejected as well.
        2. re-read the store; if another process wrote a newer session, retry;
        3. take the lock, re-read again, and only if the store still holds the
           same dead session, log in again, save and retry.

        If that still fails, an UnauthorizedException tells the user to run
        ``jama login``. A 401 that mentions "permission" is returned to the
        caller right away. There is no loop.
        """
        manager = self._session
        assert manager is not None

        session = manager.current()
        if session is not None:
            sent_token = session.csrf_token
            response = await self._send_with_session(session, method, path, **kwargs)
            if not is_auth_rejected(response):
                return response

            # 1a. The header is out of step with the cookie.
            if is_csrf_rejected(response) and await manager.adopt_cookie_csrf(session, sent_token):
                response = await self._send_with_session(session, method, path, **kwargs)
                if not is_auth_rejected(response):
                    return response

            # 1b. Ask Jama for the current token. Skipped for a read that looks
            # like a dead session: the GET could only confirm that.
            if (
                is_csrf_rejected(response) or method.upper() != "GET"
            ) and await manager.refresh_csrf(session):
                # The GET proved the session alive and gave us the current
                # token, so logging in again could not change anything:
                # whatever this retry returns is the answer.
                return await self._send_with_session(session, method, path, **kwargs)

            # 2. Another process may already have logged in again.
            newer = manager.adopt_newer(session)
            if newer is not None:
                session = newer
                response = await self._send_with_session(session, method, path, **kwargs)
                if not is_auth_rejected(response):
                    return response

        # 3. Double-checked re-login under the cross-process lock.
        session = await manager.recover(session)
        response = await self._send_with_session(session, method, path, **kwargs)
        if is_auth_rejected(response):
            raise UnauthorizedException(LOGIN_HINT, status_code=401)
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Map HTTP status to typed exceptions."""
        code = response.status_code
        if 200 <= code < 300:
            return

        try:
            body = response.json()
            message = body.get("meta", {}).get("message", response.text)
        except Exception:
            message = response.text

        if code == 401:
            raise UnauthorizedException(message, status_code=code)
        if code == 404:
            raise ResourceNotFoundException(message, status_code=code)
        if code == 409 or (code == 400 and "already exists" in message.lower()):
            raise AlreadyExistsException(message, status_code=code)
        if code == 429:
            retry_after = float(response.headers.get("Retry-After", 0)) or None
            raise TooManyRequestsException(message, status_code=code, retry_after=retry_after)
        if 400 <= code < 500:
            raise APIClientException(message, status_code=code)
        if 500 <= code < 600:
            raise APIServerException(message, status_code=code)
        raise APIException(message, status_code=code)

    # --- Convenience HTTP methods ---

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        """Decode a response body; an empty body (e.g. 204 No Content) is ``{}``."""
        if response.status_code == 204 or not response.content.strip():
            return {}
        data: dict[str, Any] = response.json()
        return data

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a single resource. Returns the response JSON."""
        response = await self._request("GET", path, params=params)
        return self._json(response)

    async def post(
        self, path: str, json: dict[str, Any] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """POST to a resource. Returns the response JSON ({} for an empty body)."""
        response = await self._request("POST", path, json=json, **kwargs)
        return self._json(response)

    async def put(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        """PUT a resource. Returns the response JSON ({} for an empty body)."""
        response = await self._request("PUT", path, json=json)
        return self._json(response)

    async def patch(self, path: str, json: Any = None) -> dict[str, Any]:
        """PATCH a resource. Returns the response JSON ({} for an empty body)."""
        response = await self._request("PATCH", path, json=json)
        return self._json(response)

    async def delete(self, path: str) -> dict[str, Any]:
        """DELETE a resource. Returns the response JSON ({} for an empty body)."""
        response = await self._request("DELETE", path)
        return self._json(response)

    # --- Raw access (file transfers, non-REST endpoints) ---

    @property
    def base_url(self) -> str:
        """The configured Jama base URL, including any context path, without ``/rest/v1``."""
        return self._base_url

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send a request and return the raw response (for bytes and multipart bodies).

        Same auth, session recovery and status mapping as the JSON helpers.
        ``path`` may be an absolute URL below the base URL. Bodies must be
        re-sendable (``bytes``, never an open file), because a request can be
        sent again after a session repair.
        """
        return await self._request(method, path, **kwargs)

    # --- Pagination ---

    async def get_all(
        self, path: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """GET all pages of a paginated resource.

        Uses page size 50 (API max) instead of py_jama_rest_client's hardcoded 20.
        """
        results: list[dict[str, Any]] = []
        async for page in self.get_pages(path, params):
            results.extend(page)
        return results

    async def get_pages(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> AsyncGenerator[list[dict[str, Any]], None]:
        """Yield pages from a paginated Jama API endpoint.

        Reads `meta.pageInfo` from the Jama response envelope:
        - startIndex: current offset
        - resultCount: items in this page
        - totalResults: total items available
        """
        params = dict(params or {})
        start_at = 0

        while True:
            params["startAt"] = start_at
            params["maxResults"] = self._page_size

            data = await self.get(path, params=params)
            page_info = data.get("meta", {}).get("pageInfo", {})
            items = data.get("data", [])

            if items:
                yield items

            result_count = page_info.get("resultCount", len(items))
            total_results = page_info.get("totalResults", result_count)

            start_at += result_count
            if start_at >= total_results or result_count == 0:
                break

    async def get_page(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        start_at: int = 0,
        max_results: int = MAX_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """GET a single page of results."""
        params = dict(params or {})
        params["startAt"] = start_at
        params["maxResults"] = min(max_results, MAX_PAGE_SIZE)
        data = await self.get(path, params=params)
        return data.get("data", [])
