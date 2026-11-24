"""A fake Jama Connect server for attachment and test run tests.

Models what the attachment code depends on:

- attachments are created in a project, get their file with a multipart PUT and
  are linked to items; the stored FILE has its own id (``fields.attachment``),
  different from the attachment id;
- ``files?url=`` only serves ``<base>/attachment/<fileId>/<name>``, so an embed
  URL built from the attachment id is a broken image;
- ``<base>/ui/internal/attachments`` creates and links in one call and needs a
  web session (cookie + ``jama-csrf-token`` header);
- ``PUT testruns/{id}`` REPLACES the result fields: a step list or a field that
  is not sent is gone afterwards (the worst case a client has to survive).

Usable in-process through ``httpx.MockTransport(fake.handle)``.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

HOST = "https://jama.example.com"
SESSION_ID = "fake-session-id"
CSRF_TOKEN = "fake-csrf-token"

# Run-level result fields a PUT replaces wholesale (worst case: not sent = gone).
RESULT_FIELDS = ("actualResults", "assignedTo")
# Step keys a PUT stores. Anything else in a step (``actualResults``,
# ``actualResult``, ``actual``, ...) is accepted with OK and silently dropped.
STORED_STEP_KEYS = ("action", "expectedResult", "notes", "status", "result")

TEST_RUN_TYPE_ID = 89
FRESH_RUN = 78


def test_run_item_type() -> dict[str, Any]:
    """The test run item type as a real instance reports it."""
    return {
        "id": TEST_RUN_TYPE_ID,
        "typeKey": "TSTRN",
        "display": "Test Run",
        "fields": [
            {"id": 1, "name": "name", "fieldType": "STRING", "readOnly": False},
            {"id": 2, "name": "testRunStatus", "fieldType": "LOOKUP", "readOnly": True},
            {"id": 3, "name": "assignedTo", "fieldType": "USER", "readOnly": False},
            {"id": 4, "name": "actualResults", "fieldType": "TEXT", "readOnly": False},
            # Marked read-only, although a PUT of this field does store step
            # results and statuses.
            {"id": 5, "name": "testRunSteps", "fieldType": "STEPS", "readOnly": True},
            {
                "id": 6,
                "name": f"defects_found${TEST_RUN_TYPE_ID}",
                "fieldType": "STRING",
                "readOnly": False,
            },
        ],
    }


test_run_item_type.__test__ = False  # type: ignore[attr-defined]


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def without_empty_fields(run: dict[str, Any]) -> dict[str, Any]:
    """A run as GET returns it: empty fields are left out, also inside steps."""
    shown = copy.deepcopy(run)
    fields = {k: v for k, v in shown.get("fields", {}).items() if not _is_empty(v)}
    if isinstance(fields.get("testRunSteps"), list):
        fields["testRunSteps"] = [
            {k: v for k, v in step.items() if not _is_empty(v)} for step in fields["testRunSteps"]
        ]
    shown["fields"] = fields
    return shown


def run_status(steps: list[dict[str, Any]]) -> str:
    """Jama recomputes the run status from the step statuses."""
    statuses = {step.get("status", "NOT_RUN") for step in steps}
    if statuses <= {"NOT_RUN"}:
        return "NOT_RUN"
    if len(statuses) == 1:
        return statuses.pop()
    return "INPROGRESS"


def fresh_test_run() -> dict[str, Any]:
    """A run just generated from a test plan: nothing executed, no result keys anywhere."""
    return {
        "id": FRESH_RUN,
        "project": 3,
        "itemType": TEST_RUN_TYPE_ID,
        "fields": {
            "name": "Fresh run",
            "testCycle": 40,
            "testRunStatus": "NOT_RUN",
            "testRunSteps": [
                {
                    "action": "<p>Open the page</p>",
                    "expectedResult": "<p>Page loads</p>",
                    "status": "NOT_RUN",
                },
                {
                    "action": "<p>Log in</p>",
                    "expectedResult": "<p>Dashboard</p>",
                    "notes": "<p>note</p>",
                    "status": "NOT_RUN",
                },
            ],
        },
    }


def parse_multipart(request: httpx.Request) -> dict[str, dict[str, Any]]:
    """Parts of a multipart/form-data request by part name."""
    content_type = request.headers.get("content-type", "")
    match = re.search(r"boundary=([^;]+)", content_type)
    assert match, "not a multipart request"
    boundary = b"--" + match.group(1).strip('"').encode()
    parts: dict[str, dict[str, Any]] = {}
    for chunk in request.content.split(boundary)[1:-1]:
        head, _, body = chunk[2:-2].partition(b"\r\n\r\n")
        headers = head.decode()
        name = re.search(r'name="([^"]*)"', headers)
        filename = re.search(r'filename="([^"]*)"', headers)
        ctype = re.search(r"Content-Type: (\S+)", headers, re.IGNORECASE)
        assert name
        parts[name.group(1)] = {
            "filename": filename.group(1) if filename else None,
            "content_type": ctype.group(1) if ctype else None,
            "content": body,
        }
    return parts


def default_test_run() -> dict[str, Any]:
    return {
        "id": 77,
        "project": 3,
        "itemType": 89,
        "fields": {
            "name": "Login works",
            "testCycle": 40,
            "assignedTo": 12,
            "testRunStatus": "INPROGRESS",
            "actualResults": "<p>Run started &amp; ok</p>",
            "testRunSteps": [
                {
                    "action": "<p>Open the page</p>",
                    "expectedResult": "<p>Page loads</p>",
                    "status": "PASSED",
                    "result": "<p>Loaded in <b>1s</b></p>",
                },
                {
                    "action": "<p>Log in</p>",
                    "expectedResult": "<p>Dashboard</p>",
                    "notes": "<p>note</p>",
                    "status": "FAILED",
                    "result": "<p>Error 500</p>",
                },
                {
                    "action": "<p>Log out</p>",
                    "expectedResult": "<p>Login page</p>",
                    "status": "NOT_RUN",
                },
            ],
        },
    }


class FakeJamaAttachments:
    def __init__(self, context_path: str = "/contour", auth: str = "basic") -> None:
        self.ctx = context_path.rstrip("/")
        self.base = HOST + self.ctx
        self.auth = auth  # "basic" | "oauth" | "session"

        self.items: dict[int, dict[str, Any]] = {
            10: {"id": 10, "project": 3, "fields": {"name": "Requirement"}},
            77: {"id": 77, "project": 3, "fields": {"name": "Login works"}},
        }
        self.test_runs: dict[int, dict[str, Any]] = {
            77: default_test_run(),
            FRESH_RUN: fresh_test_run(),
        }
        # Run-level fields a PUT replaces (names as on this instance).
        self.result_fields: tuple[str, ...] = RESULT_FIELDS
        self.item_types: list[dict[str, Any]] = [
            {"id": 33, "typeKey": "TXT", "display": "Text", "fields": []},
            test_run_item_type(),
        ]
        self.test_cycles: dict[int, dict[str, Any]] = {
            40: {"id": 40, "project": 3, "fields": {"name": "Cycle"}}
        }
        self.attachments: dict[int, dict[str, Any]] = {}
        self.files: dict[int, tuple[str, bytes]] = {}
        self.links: dict[int, list[int]] = {}
        self._next_attachment_id = 500
        self._next_file_id = 9000

        # ----- test controls -----
        # (status, message): refuse POST projects/{id}/attachments
        self.refuse_rest_create: tuple[int, str] | None = None
        # (status, message): refuse POST <base>/ui/internal/attachments
        self.refuse_internal: tuple[int, str] | None = None
        # item ids for which POST items/{id}/attachments is refused
        self.refuse_link_for: set[int] = set()
        # files?url= serves nothing ("404") or an empty body ("empty")
        self.broken_files: str | None = None
        # (status, message): refuse PUT testruns/{id}
        self.refuse_run_update: tuple[int, str] | None = None

        # ----- request log -----
        self.requests: list[tuple[str, str]] = []
        self.internal_uploads: list[dict[str, Any]] = []
        self.file_uploads: list[dict[str, Any]] = []
        self.run_puts: list[dict[str, Any]] = []

    # ----- helpers -------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def count(self, method: str, route: str) -> int:
        return sum(1 for m, r in self.requests if m == method and r == route)

    def routes(self) -> list[str]:
        return [f"{m} {r}" for m, r in self.requests]

    @staticmethod
    def _error(status: int, message: str) -> httpx.Response:
        return httpx.Response(status, json={"meta": {"status": "Error", "message": message}})

    @staticmethod
    def _ok(data: Any = None, status: int = 200, **meta: Any) -> httpx.Response:
        body: dict[str, Any] = {"meta": {"status": "OK", **meta}}
        if data is not None:
            body["data"] = data
        return httpx.Response(status, json=body)

    @staticmethod
    def _cookies(request: httpx.Request) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for part in request.headers.get("cookie", "").split(";"):
            if "=" in part:
                name, value = part.strip().split("=", 1)
                cookies[name] = value
        return cookies

    def _authorized(self, request: httpx.Request) -> bool:
        if self.auth == "session":
            if self._cookies(request).get("JSESSIONID") != SESSION_ID:
                return False
            if request.method == "GET":
                return True
            return request.headers.get("jama-csrf-token") == CSRF_TOKEN
        authorization = request.headers.get("authorization", "")
        if self.auth == "oauth":
            return authorization == "Bearer fake-access-token"
        return authorization.startswith("Basic ")

    def _store(
        self, project: int, name: str, description: str, file_name: str | None, content: bytes
    ) -> int:
        attachment_id = self._next_attachment_id
        self._next_attachment_id += 1
        self.attachments[attachment_id] = {
            "id": attachment_id,
            "project": project,
            "fields": {"name": name, "description": description},
        }
        if file_name is not None:
            self._store_file(attachment_id, file_name, content)
        return attachment_id

    def _store_file(self, attachment_id: int, file_name: str, content: bytes) -> None:
        file_id = self._next_file_id
        self._next_file_id += 1
        self.files[file_id] = (file_name, content)
        attachment = self.attachments[attachment_id]
        attachment["fileName"] = file_name
        attachment["fields"]["attachment"] = file_id

    # ----- request handling ----------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if not path.startswith(self.ctx + "/"):
            return httpx.Response(404, text="not found")
        route = path[len(self.ctx) + 1 :]
        self.requests.append((request.method, route))

        if route == "rest/oauth/token":
            return httpx.Response(
                200, json={"access_token": "fake-access-token", "expires_in": 3600}
            )
        if not self._authorized(request):
            return httpx.Response(401, json={"meta": {"status": "Unauthorized", "message": ""}})
        if route == "ui/internal/attachments" and request.method == "POST":
            return self._internal_upload(request)
        if route.startswith("rest/v1/"):
            return self._rest(request, route[len("rest/v1/") :])
        return httpx.Response(404, text="not found")

    def _internal_upload(self, request: httpx.Request) -> httpx.Response:
        if self.auth != "session":
            return self._error(401, "")
        parts = parse_multipart(request)
        self.internal_uploads.append(
            {"parts": parts, "csrf_header": request.headers.get("jama-csrf-token")}
        )
        if self.refuse_internal:
            return self._error(*self.refuse_internal)
        document = json.loads(parts["attachmentDocument"]["content"])
        attachment_id = self._store(
            document["project"],
            document["fields"]["name"],
            document["fields"].get("description", ""),
            parts["originalFileName"]["content"].decode(),
            parts["file"]["content"],
        )
        self.links.setdefault(int(parts["itemId"]["content"]), []).append(attachment_id)
        return self._ok(status=201, id=attachment_id)

    def _rest(self, request: httpx.Request, resource: str) -> httpx.Response:
        method = request.method
        segments = resource.split("/")

        if method == "GET" and resource == "users/current":
            return self._ok({"id": 7, "username": "tester"})

        if method == "GET" and resource == "files":
            return self._serve_file(request.url.params.get("url", ""))

        if segments[0] == "projects" and segments[2:] == ["attachments"] and method == "POST":
            if self.refuse_rest_create:
                return self._error(*self.refuse_rest_create)
            fields = json.loads(request.content)["fields"]
            attachment_id = self._store(
                int(segments[1]), fields["name"], fields.get("description", ""), None, b""
            )
            return self._ok(status=201, id=attachment_id)

        if segments[0] == "attachments":
            attachment = self.attachments.get(int(segments[1]))
            if attachment is None:
                return self._error(404, "Attachment not found")
            if len(segments) == 2 and method == "GET":
                return self._ok(copy.deepcopy(attachment))
            if segments[2:] == ["file"] and method == "PUT":
                part = parse_multipart(request)["file"]
                self.file_uploads.append({"attachment_id": attachment["id"], **part})
                self._store_file(attachment["id"], part["filename"], part["content"])
                return httpx.Response(200)
            if segments[2:] == ["file"] and method == "GET":
                file_id = attachment["fields"].get("attachment")
                if file_id is None:
                    return self._error(404, "No file")
                return httpx.Response(200, content=self.files[file_id][1])

        if segments[0] == "items" and len(segments) >= 2:
            item_id = int(segments[1])
            if len(segments) == 2 and method == "GET":
                if item_id not in self.items:
                    return self._error(404, "Item not found")
                return self._ok(copy.deepcopy(self.items[item_id]))
            if segments[2:] == ["attachments"] and method == "GET":
                linked = [copy.deepcopy(self.attachments[a]) for a in self.links.get(item_id, [])]
                return self._ok(
                    linked,
                    pageInfo={
                        "startIndex": 0,
                        "resultCount": len(linked),
                        "totalResults": len(linked),
                    },
                )
            if segments[2:] == ["attachments"] and method == "POST":
                if item_id in self.refuse_link_for:
                    return self._error(403, "Attachments are not allowed for this item type")
                attachment_id = json.loads(request.content)["attachment"]
                if attachment_id not in self.attachments:
                    return self._error(404, "Attachment not found")
                self.links.setdefault(item_id, []).append(attachment_id)
                return self._ok(status=201)

        if segments[0] == "testcycles" and len(segments) == 2 and method == "GET":
            cycle = self.test_cycles.get(int(segments[1]))
            return self._ok(copy.deepcopy(cycle)) if cycle else self._error(404, "Not found")

        if segments[0] == "itemtypes" and method == "GET":
            if len(segments) == 1:
                listed = copy.deepcopy(self.item_types)
                return self._ok(
                    listed,
                    pageInfo={
                        "startIndex": 0,
                        "resultCount": len(listed),
                        "totalResults": len(listed),
                    },
                )
            found = next((t for t in self.item_types if t["id"] == int(segments[1])), None)
            return self._ok(copy.deepcopy(found)) if found else self._error(404, "Not found")

        if segments[0] == "testruns" and len(segments) == 2:
            run = self.test_runs.get(int(segments[1]))
            if run is None:
                return self._error(404, "Test run not found")
            if method == "GET":
                return self._ok(without_empty_fields(run))
            if method == "PUT":
                body = json.loads(request.content)
                self.run_puts.append(body)
                if self.refuse_run_update:
                    return self._error(*self.refuse_run_update)
                sent = body.get("fields", {})
                # Worst case: the run-level result fields are replaced, not merged.
                for name in self.result_fields:
                    if name in sent:
                        run["fields"][name] = copy.deepcopy(sent[name])
                    else:
                        run["fields"].pop(name, None)
                # The steps field is "readOnly" in the item type, but a PUT stores
                # the known keys of each step and silently drops every other key.
                if "testRunSteps" in sent:
                    run["fields"]["testRunSteps"] = [
                        {k: copy.deepcopy(v) for k, v in step.items() if k in STORED_STEP_KEYS}
                        for step in sent["testRunSteps"]
                    ]
                    run["fields"]["testRunStatus"] = run_status(run["fields"]["testRunSteps"])
                return self._ok()

        return self._error(404, "Not found")

    def _serve_file(self, url: str) -> httpx.Response:
        prefix = f"{self.base}/attachment/"
        if self.broken_files == "404" or not url.startswith(prefix):
            return self._error(404, "File not found")
        if self.broken_files == "empty":
            return httpx.Response(200, content=b"")
        file_id, _, name = urlsplit(url).path[len(self.ctx) + len("/attachment/") :].partition("/")
        stored = self.files.get(int(file_id)) if file_id.isdigit() else None
        if stored is None or stored[0] != unquote(name):
            return self._error(404, "File not found")
        return httpx.Response(200, content=stored[1])
