"""Tests for attachment upload/download and inline-image helpers against a fake Jama."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from loguru import logger

from jama_cli.core.api import JamaApi
from jama_cli.core.attachments import (
    AttachmentError,
    AttachmentService,
    AttachmentTooLargeError,
    EmbedVerificationError,
    UploadCache,
    build_embed_url,
    content_type_for,
    embed_image_html,
    file_id_of,
    is_rest_create_refused,
    screenshot_block_html,
)
from jama_cli.core.client import JamaClient
from jama_cli.core.exceptions import (
    APIClientException,
    ResourceNotFoundException,
    UnauthorizedException,
)
from jama_cli.core.http_client import JamaHttpClient
from jama_cli.core.session import LOGIN_HINT, SessionManager, SessionSettings
from jama_cli.core.session_store import SessionStore, StoredSession
from jama_cli.core.sync_wrapper import SyncJamaApi
from jama_cli.models import JamaProfile
from tests.fake_jama_attachments import CSRF_TOKEN, SESSION_ID, FakeJamaAttachments

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) + b"\r\n--tail"


def make_http(fake: FakeJamaAttachments, tmp_path: Path) -> JamaHttpClient:
    """An HTTP client for the fake's auth mode."""
    transport = fake.transport()
    if fake.auth == "session":
        session_file = tmp_path / "sessions" / "tester.json"
        SessionStore(session_file).save(
            StoredSession(
                base_url=fake.base,
                username="tester",
                cookies=[
                    {"name": "JSESSIONID", "value": SESSION_ID, "domain": "", "path": "/"},
                    {"name": "jama-csrf-token", "value": CSRF_TOKEN, "domain": "", "path": "/"},
                ],
                csrf_token=CSRF_TOKEN,
                created_at=1.0,
                last_validated_at=1.0,
            )
        )
        settings = SessionSettings(
            base_url=fake.base,
            username="tester",
            password="unused-in-this-test",
            login_mode="form",
            login_interactive="never",
            session_file=session_file,
        )
        manager = SessionManager(settings, transport=transport)
        return JamaHttpClient(base_url=fake.base, session=manager, transport=transport)
    if fake.auth == "oauth":
        return JamaHttpClient(
            base_url=fake.base, credentials=("client", "secret"), oauth=True, transport=transport
        )
    return JamaHttpClient(base_url=fake.base, credentials=("user", "pw"), transport=transport)


def make_service(
    fake: FakeJamaAttachments, tmp_path: Path, cache: bool = False, **kwargs: Any
) -> AttachmentService:
    api = JamaApi(make_http(fake, tmp_path))
    upload_cache = UploadCache(tmp_path / "uploads.json") if cache else None
    return AttachmentService(api, cache=upload_cache, **kwargs)


@pytest.fixture
def fake() -> FakeJamaAttachments:
    return FakeJamaAttachments()


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "shot 1.png"
    path.write_bytes(PNG)
    return path


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("a.png", "image/png"),
            ("a.JPG", "image/jpeg"),
            ("a.jpeg", "image/jpeg"),
            ("a.gif", "image/gif"),
            ("a.webp", "image/webp"),
            ("a.svg", "image/svg+xml"),
            ("a.pdf", "application/pdf"),
            ("a.bin", "application/octet-stream"),
            ("noextension", "application/octet-stream"),
        ],
    )
    def test_content_type_from_extension(self, name: str, expected: str) -> None:
        assert content_type_for(name) == expected

    def test_embed_url_keeps_context_path_and_encodes_name(self) -> None:
        url = build_embed_url("https://jama.example.com/contour/", 9000, "shot 1 &<x>.png")
        assert url == "https://jama.example.com/contour/attachment/9000/shot%201%20%26%3Cx%3E.png"

    def test_embed_image_html_escapes_alt_and_src(self) -> None:
        markup = embed_image_html(
            'https://jama.example.com/attachment/1/a.png?x="1"&y=2', 'a "quote" <script>'
        )
        assert markup == (
            '<img src="https://jama.example.com/attachment/1/a.png?x=&quot;1&quot;&amp;y=2" '
            'alt="a &quot;quote&quot; &lt;script&gt;" />'
        )

    def test_embed_image_html_rejects_script_urls(self) -> None:
        with pytest.raises(ValueError):
            embed_image_html("javascript:alert(1)", "x")

    def test_caption_is_escaped(self) -> None:
        markup = screenshot_block_html(
            "https://jama.example.com/attachment/1/a.png", "alt", "<b>bold</b> & more"
        )
        assert markup.startswith("<p>&lt;b&gt;bold&lt;/b&gt; &amp; more</p><p><img ")
        assert "<b>" not in markup

    def test_file_id_missing_is_a_clear_error(self) -> None:
        with pytest.raises(AttachmentError, match="no file id"):
            file_id_of({"id": 5, "fields": {"name": "x"}})

    def test_refusal_classification(self) -> None:
        assert is_rest_create_refused(UnauthorizedException("", status_code=401))
        assert is_rest_create_refused(APIClientException("Forbidden", status_code=403))
        assert not is_rest_create_refused(APIClientException("Bad request", status_code=400))
        # A session that could not be repaired is not a refusal.
        assert not is_rest_create_refused(UnauthorizedException(LOGIN_HINT, status_code=401))
        assert not is_rest_create_refused(RuntimeError("boom"))


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class TestUpload:
    async def test_upload_creates_puts_file_and_links(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path)

        result = await service.upload_attachment(10, png, name="Login", description="desc")

        writes = [r for r in fake.routes() if not r.startswith("GET")]
        assert writes == [
            "POST rest/v1/projects/3/attachments",
            "PUT rest/v1/attachments/500/file",
            "POST rest/v1/items/10/attachments",
        ]
        assert fake.attachments[500]["fields"]["name"] == "Login"
        assert fake.attachments[500]["fields"]["description"] == "desc"
        upload = fake.file_uploads[0]
        assert upload["filename"] == "shot 1.png"
        assert upload["content_type"] == "image/png"
        assert upload["content"] == PNG
        assert fake.links == {10: [500]}
        assert result.linked is True
        assert result.via_internal_endpoint is False
        assert fake.internal_uploads == []

    async def test_embed_url_uses_file_id_not_attachment_id(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        """The stored file's id (fields.attachment) goes into the URL, never meta.id."""
        service = make_service(fake, tmp_path)

        result = await service.upload_attachment(10, png)

        assert result.attachment_id == 500
        assert result.file_id == 9000
        assert result.attachment_id != result.file_id
        assert result.embed_url == f"{fake.base}/attachment/9000/shot%201.png"
        assert "/attachment/500/" not in result.embed_url
        # The fake serves only the file-id URL: the attachment-id URL is a broken image.
        with pytest.raises(EmbedVerificationError):
            await service.verify_embed_url(build_embed_url(fake.base, 500, "shot 1.png"))

    async def test_upload_from_bytes_needs_a_file_name(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        service = make_service(fake, tmp_path)

        with pytest.raises(AttachmentError, match="file name is required"):
            await service.upload_attachment(10, PNG)

        result = await service.upload_attachment(10, PNG, file_name="from-bytes.png")
        assert fake.files[result.file_id] == ("from-bytes.png", PNG)

    async def test_no_link(self, fake: FakeJamaAttachments, tmp_path: Path, png: Path) -> None:
        service = make_service(fake, tmp_path)

        result = await service.upload_attachment(10, png, link=False)

        assert result.linked is False
        assert fake.links == {}

    async def test_embed_verification_failure_is_a_clear_error(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        fake.broken_files = "404"
        service = make_service(fake, tmp_path)

        with pytest.raises(EmbedVerificationError, match="does not load"):
            await service.upload_attachment(10, png)

    async def test_empty_embedded_file_fails_verification(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        fake.broken_files = "empty"
        service = make_service(fake, tmp_path)

        with pytest.raises(EmbedVerificationError, match="empty file"):
            await service.upload_attachment(10, png)

    async def test_max_file_size(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path, max_file_size=16)

        with pytest.raises(AttachmentTooLargeError, match="maximum upload size of 16 bytes"):
            await service.upload_attachment(10, png)
        assert fake.attachments == {}

    def test_max_file_size_from_environment(
        self, fake: FakeJamaAttachments, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JAMA_MAX_ATTACHMENT_BYTES", "1234")
        assert make_service(fake, tmp_path).max_file_size == 1234

    async def test_link_refused_for_a_normal_item_is_an_error(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        fake.refuse_link_for = {10}
        service = make_service(fake, tmp_path)

        with pytest.raises(APIClientException, match="not allowed"):
            await service.upload_attachment(10, png)

    async def test_create_and_link_separately(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path)

        attachment_id = await service.create_attachment(3, png, description="d")
        assert fake.links == {}
        await service.link_attachment(10, attachment_id)

        assert fake.links == {10: [attachment_id]}
        assert await service.resolve_embed_url(attachment_id) == (
            f"{fake.base}/attachment/9000/shot%201.png"
        )

    async def test_works_without_a_context_path(self, tmp_path: Path, png: Path) -> None:
        fake = FakeJamaAttachments(context_path="")
        service = make_service(fake, tmp_path)

        result = await service.upload_attachment(10, png)

        assert result.embed_url == "https://jama.example.com/attachment/9000/shot%201.png"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestUploadCache:
    async def test_same_bytes_are_uploaded_once(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        first = await make_service(fake, tmp_path, cache=True).upload_attachment(10, png)
        # A new service (a new CLI run) with the same cache file.
        second = await make_service(fake, tmp_path, cache=True).upload_attachment(10, png)

        assert len(fake.attachments) == 1
        assert second.reused is True and first.reused is False
        assert (second.attachment_id, second.file_id, second.embed_url) == (
            first.attachment_id,
            first.file_id,
            first.embed_url,
        )
        assert fake.links == {10: [500]}  # not linked twice
        assert second.linked is True

    async def test_cached_upload_is_linked_to_another_item(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        fake.items[11] = {"id": 11, "project": 3, "fields": {"name": "Other requirement"}}
        service = make_service(fake, tmp_path, cache=True)
        await service.upload_attachment(10, png)
        await service.upload_attachment(11, png)

        assert len(fake.attachments) == 1
        assert fake.links == {10: [500], 11: [500]}

    async def test_stale_cache_entry_is_replaced(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path, cache=True)
        first = await service.upload_attachment(10, png)
        fake.files.clear()  # deleted on the server

        second = await service.upload_attachment(10, png)

        assert second.reused is False
        assert second.attachment_id != first.attachment_id

    async def test_cache_can_be_bypassed_and_holds_no_secrets(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path, cache=True)
        await service.upload_attachment(10, png)
        await service.upload_attachment(10, png, use_cache=False)

        assert len(fake.attachments) == 2
        stored = json.loads((tmp_path / "uploads.json").read_text())
        assert all(
            set(entry) == {"attachment_id", "file_id", "embed_url", "name"}
            for entry in stored.values()
        )


# ---------------------------------------------------------------------------
# Session auth: fallback to the internal endpoint
# ---------------------------------------------------------------------------


class TestSessionFallback:
    @pytest.mark.parametrize(
        "refusal",
        [(401, ""), (401, "You don't have permission to create attachments"), (403, "Forbidden")],
    )
    async def test_refused_rest_create_falls_back_to_internal_endpoint(
        self, tmp_path: Path, png: Path, refusal: tuple[int, str]
    ) -> None:
        fake = FakeJamaAttachments(auth="session")
        fake.refuse_rest_create = refusal
        service = make_service(fake, tmp_path)

        result = await service.upload_attachment(10, png, name="Login", description="desc")

        assert len(fake.internal_uploads) == 1
        upload = fake.internal_uploads[0]
        parts = upload["parts"]
        assert set(parts) == {"file", "itemId", "attachmentDocument", "originalFileName"}
        assert parts["file"]["content"] == PNG
        assert parts["file"]["filename"] == "shot 1.png"
        assert parts["file"]["content_type"] == "image/png"
        assert parts["itemId"]["content"] == b"10"
        assert json.loads(parts["attachmentDocument"]["content"]) == {
            "project": 3,
            "fields": {"name": "Login", "description": "desc"},
        }
        assert parts["originalFileName"]["content"] == b"shot 1.png"
        assert upload["csrf_header"] == CSRF_TOKEN

        assert result.via_internal_endpoint is True
        assert result.linked is True
        # The internal endpoint links by itself: no REST file PUT, no REST link.
        assert fake.count("PUT", "rest/v1/attachments/500/file") == 0
        assert fake.count("POST", "rest/v1/items/10/attachments") == 0
        assert fake.links == {10: [500]}
        assert result.embed_url == f"{fake.base}/attachment/{result.file_id}/shot%201.png"
        assert result.file_id != result.attachment_id

    async def test_session_auth_uses_rest_when_it_is_allowed(
        self, tmp_path: Path, png: Path
    ) -> None:
        fake = FakeJamaAttachments(auth="session")
        service = make_service(fake, tmp_path)

        result = await service.upload_attachment(10, png)

        assert fake.internal_uploads == []
        assert result.via_internal_endpoint is False
        assert fake.count("POST", "rest/v1/projects/3/attachments") == 1

    async def test_other_client_errors_do_not_fall_back(self, tmp_path: Path, png: Path) -> None:
        fake = FakeJamaAttachments(auth="session")
        fake.refuse_rest_create = (400, "Name is required")
        service = make_service(fake, tmp_path)

        with pytest.raises(APIClientException, match="Name is required"):
            await service.upload_attachment(10, png)
        assert fake.internal_uploads == []

    async def test_both_endpoints_refusing_reports_both(self, tmp_path: Path, png: Path) -> None:
        fake = FakeJamaAttachments(auth="session")
        fake.refuse_rest_create = (403, "REST not allowed for SSO users")
        fake.refuse_internal = (403, "No write access")
        service = make_service(fake, tmp_path)

        with pytest.raises(AttachmentError) as excinfo:
            await service.upload_attachment(10, png)

        message = str(excinfo.value)
        assert "REST not allowed for SSO users" in message
        assert "No write access" in message
        assert SESSION_ID not in message and CSRF_TOKEN not in message

    async def test_create_without_item_cannot_fall_back(self, tmp_path: Path, png: Path) -> None:
        fake = FakeJamaAttachments(auth="session")
        fake.refuse_rest_create = (403, "Forbidden")
        service = make_service(fake, tmp_path)

        with pytest.raises(AttachmentError, match="needs an item"):
            await service.create_attachment(3, png)
        assert fake.internal_uploads == []

    @pytest.mark.parametrize("auth", ["basic", "oauth"])
    @pytest.mark.parametrize("refusal", [(401, ""), (403, "Forbidden")])
    async def test_other_auth_modes_never_call_the_internal_endpoint(
        self, tmp_path: Path, png: Path, auth: str, refusal: tuple[int, str]
    ) -> None:
        fake = FakeJamaAttachments(auth=auth)
        fake.refuse_rest_create = refusal
        service = make_service(fake, tmp_path)

        with pytest.raises(APIClientException):
            await service.upload_attachment(10, png)

        assert fake.internal_uploads == []
        assert fake.count("POST", "ui/internal/attachments") == 0

    async def test_no_secrets_in_logs(self, tmp_path: Path, png: Path) -> None:
        fake = FakeJamaAttachments(auth="session")
        fake.refuse_rest_create = (403, "Forbidden")
        lines: list[str] = []
        sink_id = logger.add(lines.append, level="DEBUG", format="{message}")
        try:
            await make_service(fake, tmp_path).upload_attachment(10, png)
        finally:
            logger.remove(sink_id)

        text = "".join(lines)
        assert "internal web UI endpoint" in text
        assert SESSION_ID not in text and CSRF_TOKEN not in text


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


class TestDownload:
    async def test_download_attachment_writes_the_exact_bytes(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path)
        uploaded = await service.upload_attachment(10, png)
        target = tmp_path / "out" / "copy.png"

        written = await service.download_attachment(uploaded.attachment_id, target)

        assert written == target
        assert target.read_bytes() == PNG

    async def test_download_embedded_writes_the_exact_bytes(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path)
        uploaded = await service.upload_attachment(10, png)
        target = tmp_path / "embedded.png"

        await service.download_embedded(uploaded.embed_url, target)

        assert target.read_bytes() == PNG


# ---------------------------------------------------------------------------
# JamaClient (sync facade used by the CLI)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(fake: FakeJamaAttachments, tmp_path: Path) -> Any:
    http = make_http(fake, tmp_path)
    profile = JamaProfile(
        url=fake.base, auth_type="basic", username="user", password="pw"  # noqa: S106
    )
    jama = JamaClient(profile, use_disk_cache=False)
    jama._api = SyncJamaApi(JamaApi(http), http)
    yield jama
    jama._api.close()


class TestJamaClient:
    def test_upload_attachment_regression(
        self, client: JamaClient, fake: FakeJamaAttachments, png: Path
    ) -> None:
        """upload_attachment(item_id, path) used to send the PATH as the attachment id
        to the link endpoint and never created an attachment or uploaded bytes."""
        result = client.upload_attachment(10, png)

        assert fake.count("POST", "rest/v1/projects/3/attachments") == 1
        assert fake.file_uploads[0]["content"] == PNG
        assert fake.links == {10: [result["attachment_id"]]}
        assert isinstance(result["attachment_id"], int)
        assert result["file_id"] == 9000
        assert result["embed_url"] == f"{fake.base}/attachment/9000/shot%201.png"

    def test_download_attachment_writes_the_file_not_metadata(
        self, client: JamaClient, png: Path, tmp_path: Path
    ) -> None:
        """download_attachment used to write the attachment METADATA as JSON."""
        result = client.upload_attachment(10, png)
        target = tmp_path / "download.png"

        client.download_attachment(result["attachment_id"], target)

        assert target.read_bytes() == PNG

    def test_download_embedded_and_html(
        self, client: JamaClient, png: Path, tmp_path: Path
    ) -> None:
        result = client.upload_attachment(10, png)
        target = tmp_path / "embedded.png"

        client.download_embedded(result["embed_url"], target)

        assert target.read_bytes() == PNG
        assert client.embed_image_html(result["embed_url"], "a<b") == (
            f'<img src="{result["embed_url"]}" alt="a&lt;b" />'
        )

    def test_create_and_link(
        self, client: JamaClient, fake: FakeJamaAttachments, png: Path
    ) -> None:
        attachment_id = client.create_attachment(3, png, name="N")
        client.link_attachment(10, attachment_id)

        assert fake.attachments[attachment_id]["fields"]["name"] == "N"
        assert fake.links == {10: [attachment_id]}


# ---------------------------------------------------------------------------
# Test runs are not items
# ---------------------------------------------------------------------------

RUN = 77
ITEM_ROUTE = f"rest/v1/items/{RUN}"


class TestUploadForATestRun:
    def test_fake_answers_404_for_a_test_run_id_on_items(self, fake: FakeJamaAttachments) -> None:
        assert RUN in fake.test_runs and RUN not in fake.items

    async def test_project_comes_from_the_test_run_when_the_item_lookup_is_404(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path)

        result = await service.upload_attachment(RUN, png)

        assert fake.attachments[result.attachment_id]["project"] == 3
        assert result.project_id == 3 and result.target_is_test_run is True
        assert fake.count("GET", ITEM_ROUTE) == 1
        assert fake.count("GET", f"rest/v1/testruns/{RUN}") == 1
        assert await service.fetch_embedded(result.embed_url) == PNG

    async def test_no_link_is_attempted_and_that_is_info_not_a_warning(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path)

        result = await service.upload_attachment(RUN, png)

        assert result.linked is False
        assert result.warnings == []
        assert len(result.info) == 1 and "no Attachments tab via REST" in result.info[0]
        assert fake.count("POST", f"{ITEM_ROUTE}/attachments") == 0
        assert fake.count("GET", f"{ITEM_ROUTE}/attachments") == 0
        assert fake.links == {}
        assert result.to_dict()["info"] == result.info

    async def test_explicit_project_is_used_for_a_test_run(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path)

        result = await service.upload_attachment(RUN, png, project_id=5)

        assert fake.attachments[result.attachment_id]["project"] == 5
        assert result.linked is False and result.target_is_test_run is True
        assert fake.count("POST", f"{ITEM_ROUTE}/attachments") == 0

    async def test_known_test_run_needs_no_item_lookup(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path)

        await service.upload_attachment(RUN, png, project_id=3, target_is_test_run=True)

        assert fake.count("GET", ITEM_ROUTE) == 0
        assert fake.count("GET", f"rest/v1/testruns/{RUN}") == 0

    async def test_reused_upload_for_a_test_run_is_not_linked_either(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path, cache=True)
        await service.upload_attachment(10, png)

        again = await service.upload_attachment(RUN, png)

        assert again.reused is True and again.linked is False
        assert fake.links == {10: [500]}

    async def test_unknown_id_keeps_the_item_error(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path)

        with pytest.raises(ResourceNotFoundException, match="Item not found"):
            await service.upload_attachment(4242, png)
        assert fake.attachments == {}

    async def test_ordinary_item_is_still_linked(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        service = make_service(fake, tmp_path)

        result = await service.upload_attachment(10, png)

        assert result.linked is True and result.target_is_test_run is False
        assert result.info == [] and fake.links == {10: [500]}
