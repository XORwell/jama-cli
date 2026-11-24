"""Attachment upload/download and inline images for rich-text fields.

Jama facts this module is built on:

- An attachment is a project-scoped item of its own. Uploading is three REST
  calls: create the attachment in the project, PUT its file, link it to an item.
- An inline image does NOT use the attachment id but the id of the stored
  *file*, which is ``fields.attachment`` of the attachment. The embed URL is
  ``<base>/attachment/<fileId>/<url-encoded file name>``.
- ``GET /rest/v1/files?url=<embed url>`` serves an embedded file, which is also
  how an embed URL is verified.
- With a browser-session login Jama may refuse the REST create for SSO users.
  Only then, and only under session auth, the web UI's own (undocumented)
  ``<base>/ui/internal/attachments`` endpoint is used instead.

Nothing in here logs or raises cookies, tokens or passwords.
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from loguru import logger

from jama_cli.core.api import JamaApi
from jama_cli.core.exceptions import (
    AlreadyExistsException,
    APIClientException,
    JamaException,
    ResourceNotFoundException,
    TooManyRequestsException,
    UnauthorizedException,
)
from jama_cli.core.session import LOGIN_HINT

# Largest file accepted for upload unless configured otherwise.
DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_FILE_SIZE_ENV = "JAMA_MAX_ATTACHMENT_BYTES"

DEFAULT_CONTENT_TYPE = "application/octet-stream"
CONTENT_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
}

# Field of an attachment (``GET attachments/{id}`` -> ``data.fields``) that holds
# the id of the stored FILE. This id, not the attachment id, goes into embed URLs.
FILE_ID_FIELD = "attachment"
# Field of an attachment that holds the stored file's name, if Jama reports it.
FILE_NAME_FIELD = "fileName"

# HTTP statuses that count as "Jama refused the REST create" under session auth
# and therefore trigger the fallback to the internal endpoint.
REST_CREATE_REFUSED_STATUSES: frozenset[int] = frozenset({401, 403})

FileSource = Path | str | bytes


class AttachmentError(JamaException):
    """An attachment operation failed."""


class AttachmentTooLargeError(AttachmentError):
    """The file exceeds the configured maximum upload size."""


class EmbedVerificationError(AttachmentError):
    """An embed URL does not serve a file."""


def default_max_file_size() -> int:
    """Maximum upload size in bytes: ``JAMA_MAX_ATTACHMENT_BYTES`` or 50 MB."""
    raw = os.environ.get(MAX_FILE_SIZE_ENV)
    if not raw:
        return DEFAULT_MAX_FILE_SIZE
    try:
        value = int(raw)
    except ValueError:
        raise AttachmentError(f"{MAX_FILE_SIZE_ENV} must be a number of bytes") from None
    if value <= 0:
        raise AttachmentError(f"{MAX_FILE_SIZE_ENV} must be greater than zero")
    return value


def content_type_for(file_name: str) -> str:
    """Content type from the file extension; ``application/octet-stream`` if unknown."""
    return CONTENT_TYPES.get(Path(file_name).suffix.lower(), DEFAULT_CONTENT_TYPE)


def build_embed_url(base_url: str, file_id: int, file_name: str) -> str:
    """Embed URL of a stored file: ``<base>/attachment/<fileId>/<url-encoded name>``.

    ``file_id`` is the id of the stored file (``fields.attachment``), never the
    attachment id.
    """
    return f"{base_url.rstrip('/')}/attachment/{int(file_id)}/{quote(file_name, safe='')}"


def embed_image_html(embed_url: str, alt: str = "") -> str:
    """``<img>`` element for an embed URL, with ``src`` and ``alt`` HTML-escaped."""
    if urlsplit(embed_url).scheme not in ("http", "https"):
        raise ValueError("An embed URL must be an http(s) URL")
    return (
        f'<img src="{html.escape(embed_url, quote=True)}" alt="{html.escape(alt, quote=True)}" />'
    )


def screenshot_block_html(embed_url: str, alt: str = "", caption: str | None = None) -> str:
    """``<p>caption</p><p><img .../></p>``; the caption is plain text and gets escaped."""
    block = f"<p>{embed_image_html(embed_url, alt)}</p>"
    if caption:
        block = f"<p>{html.escape(caption)}</p>{block}"
    return block


def html_contains_url(markup: str, url: str) -> bool:
    """True if a rich-text value already references this URL (raw or HTML-escaped)."""
    return bool(markup) and (url in markup or html.escape(url, quote=True) in markup)


def file_id_of(attachment: dict[str, Any]) -> int:
    """The stored file's id of an attachment (``fields.attachment``)."""
    fields = attachment.get("fields")
    value = fields.get(FILE_ID_FIELD) if isinstance(fields, dict) else None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise AttachmentError(
            f"Attachment {attachment.get('id', '?')} has no file id (fields.{FILE_ID_FIELD}); "
            "was its file uploaded?"
        ) from None


def read_source(source: FileSource, file_name: str | None = None) -> tuple[str, bytes]:
    """Turn a path or raw bytes into ``(file name, content)``.

    The content is always returned as ``bytes`` so that a request carrying it
    can be sent again.
    """
    if isinstance(source, bytes | bytearray):
        if not file_name:
            raise AttachmentError("A file name is required when uploading raw bytes")
        return Path(file_name).name, bytes(source)
    path = Path(source)
    if not path.is_file():
        raise AttachmentError(f"File not found: {path}")
    return Path(file_name).name if file_name else path.name, path.read_bytes()


def is_rest_create_refused(exc: BaseException) -> bool:
    """True if this error means "Jama refused the REST attachment create".

    Decided from what the HTTP client finally raised, i.e. after it repaired a
    dead session or a stale CSRF token on its own. A session that could not be
    repaired (``LOGIN_HINT``) is not a refusal: there the user has to log in.
    """
    if not isinstance(exc, APIClientException):
        return False
    if isinstance(exc, UnauthorizedException) and str(exc) == LOGIN_HINT:
        return False
    return exc.status_code in REST_CREATE_REFUSED_STATUSES


def _is_dead_session(exc: BaseException) -> bool:
    return isinstance(exc, UnauthorizedException) and str(exc) == LOGIN_HINT


def _describe(exc: JamaException) -> str:
    status = f"HTTP {exc.status_code}" if exc.status_code else type(exc).__name__
    message = str(exc).strip()
    return f"{status}: {message}" if message else status


# Why an attachment for a test run is not linked. Not a problem: the embed URL
# works without the link.
TEST_RUN_NOT_LINKED = (
    "Test runs have no Attachments tab via REST, so the attachment was not linked; "
    "embedding it by URL works without the link."
)


@dataclass
class UploadedAttachment:
    """Result of an upload: everything needed to reference the file."""

    attachment_id: int
    file_id: int
    embed_url: str
    name: str
    project_id: int
    linked: bool = False
    reused: bool = False
    via_internal_endpoint: bool = False
    warnings: list[str] = field(default_factory=list)
    # Things worth knowing that are not problems (e.g. why nothing was linked).
    info: list[str] = field(default_factory=list)
    # The target id is a test run, which is not an item in the REST API.
    target_is_test_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "file_id": self.file_id,
            "embed_url": self.embed_url,
            "name": self.name,
            "project_id": self.project_id,
            "linked": self.linked,
            "reused": self.reused,
            "via_internal_endpoint": self.via_internal_endpoint,
            "target_is_test_run": self.target_is_test_run,
            "warnings": list(self.warnings),
            "info": list(self.info),
        }


def default_upload_cache_path(base_url: str) -> Path:
    """Default location of the upload map for one Jama instance."""
    key = hashlib.sha256(base_url.rstrip("/").lower().encode()).hexdigest()[:16]
    return Path.home() / ".cache" / "jama-cli" / "uploads" / f"{key}.json"


class UploadCache:
    """Local map ``(project, sha256 of the bytes) -> attachment`` to avoid duplicate uploads.

    Holds ids, names and embed URLs only; no credentials.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _key(project_id: int, digest: str) -> str:
        return f"{project_id}:{digest}"

    def _load(self) -> dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".uploads-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp_name, self.path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
                raise
        except OSError as e:
            logger.debug(f"Could not write the upload cache: {type(e).__name__}")

    def get(self, project_id: int, digest: str) -> dict[str, Any] | None:
        entry = self._load().get(self._key(project_id, digest))
        if not isinstance(entry, dict):
            return None
        try:
            int(entry["attachment_id"])
            int(entry["file_id"])
            str(entry["embed_url"])
            str(entry["name"])
        except (KeyError, TypeError, ValueError):
            return None
        return entry

    def put(self, project_id: int, digest: str, uploaded: UploadedAttachment) -> None:
        data = self._load()
        data[self._key(project_id, digest)] = {
            "attachment_id": uploaded.attachment_id,
            "file_id": uploaded.file_id,
            "embed_url": uploaded.embed_url,
            "name": uploaded.name,
        }
        self._save(data)

    def forget(self, project_id: int, digest: str) -> None:
        data = self._load()
        if data.pop(self._key(project_id, digest), None) is not None:
            self._save(data)


class AttachmentService:
    """Upload, link, download and embed attachments on top of :class:`JamaApi`."""

    def __init__(
        self,
        api: JamaApi,
        cache: UploadCache | None = None,
        max_file_size: int | None = None,
    ) -> None:
        self._api = api
        self._cache = cache
        self.max_file_size = max_file_size if max_file_size is not None else default_max_file_size()

    # ----- helpers --------------------------------------------------------

    def _check_size(self, file_name: str, content: bytes) -> None:
        if not content:
            raise AttachmentError(f"{file_name} is empty; nothing to upload")
        if len(content) > self.max_file_size:
            raise AttachmentTooLargeError(
                f"{file_name} is {len(content)} bytes, larger than the maximum upload size of "
                f"{self.max_file_size} bytes (set {MAX_FILE_SIZE_ENV} to change the limit)"
            )

    async def _create(
        self,
        project_id: int,
        file_name: str,
        content: bytes,
        name: str,
        description: str,
        item_id: int | None,
    ) -> tuple[int, bool]:
        """Create the attachment and upload its file.

        Returns ``(attachment id, created through the internal endpoint)``. The
        internal endpoint also links the attachment to ``item_id``.
        """
        content_type = content_type_for(file_name)
        try:
            attachment_id = await self._api.post_project_attachment(project_id, name, description)
        except APIClientException as refusal:
            # Only a web session can use the internal endpoint; every other auth
            # mode reports the refusal as it is.
            if not (self._api.uses_session_auth and is_rest_create_refused(refusal)):
                raise
            if item_id is None:
                raise AttachmentError(
                    f"Jama refused to create the attachment through the REST API "
                    f"({_describe(refusal)}). The web UI endpoint used as a fallback needs an "
                    "item to link the attachment to.",
                    status_code=refusal.status_code,
                ) from refusal
            logger.info(
                "Jama refused the REST attachment create; using the internal web UI endpoint"
            )
            try:
                attachment_id = await self._api.post_internal_attachment(
                    item_id, project_id, name, description, file_name, content, content_type
                )
            except (JamaException, KeyError, ValueError, TypeError) as e:
                if _is_dead_session(e):
                    raise
                detail = _describe(e) if isinstance(e, JamaException) else "unexpected response"
                raise AttachmentError(
                    f"Jama refused to create the attachment through the REST API "
                    f"({_describe(refusal)}) and the internal web UI endpoint failed as well "
                    f"({detail}).",
                    status_code=getattr(e, "status_code", None),
                ) from e
            return attachment_id, True

        await self._api.put_attachment_file(attachment_id, file_name, content, content_type)
        return attachment_id, False

    async def _is_linked(self, item_id: int, attachment_id: int) -> bool:
        """Best effort: whether the attachment already shows on the item."""
        try:
            linked = await self._api.get_item_attachments(item_id)
        except JamaException as e:
            if _is_dead_session(e):
                raise
            return False
        return any(entry.get("id") == attachment_id for entry in linked)

    async def _embed_loads(self, embed_url: str) -> bool:
        try:
            return bool(await self._api.get_file_by_url(embed_url))
        except JamaException as e:
            if _is_dead_session(e) or isinstance(e, TooManyRequestsException):
                raise
            return False

    # ----- public API -----------------------------------------------------

    async def create_attachment(
        self,
        project_id: int,
        file: FileSource,
        name: str | None = None,
        description: str = "",
        file_name: str | None = None,
        item_id: int | None = None,
    ) -> int:
        """Create an attachment in a project and upload its file. Returns the attachment id.

        ``item_id`` is only used under session auth when Jama refuses the REST
        create: the internal endpoint used then links the attachment to that item.
        """
        actual_name, content = read_source(file, file_name)
        self._check_size(actual_name, content)
        attachment_id, _ = await self._create(
            project_id, actual_name, content, name or actual_name, description, item_id
        )
        return attachment_id

    async def link_attachment(self, item_id: int, attachment_id: int) -> None:
        """Link an attachment to an item (shows it on the item's Attachments tab)."""
        with contextlib.suppress(AlreadyExistsException):
            await self._api.post_item_attachment(item_id, attachment_id)

    async def resolve_embed_url(self, attachment_id: int, file_name: str | None = None) -> str:
        """Embed URL of an attachment's stored file."""
        attachment = await self._api.get_attachment(attachment_id)
        return self._embed_url_of(attachment, file_name)[1]

    def _embed_url_of(self, attachment: dict[str, Any], file_name: str | None) -> tuple[int, str]:
        file_id = file_id_of(attachment)
        name = file_name
        if not name:
            # Not uploaded by this call: use the name Jama reports for the file.
            fields = attachment.get("fields") or {}
            reported = attachment.get(FILE_NAME_FIELD) or fields.get(FILE_NAME_FIELD)
            name = reported if isinstance(reported, str) else None
        if not name:
            raise AttachmentError(f"Attachment {attachment.get('id', '?')} has no file name")
        return file_id, build_embed_url(self._api.base_url, file_id, name)

    async def verify_embed_url(self, embed_url: str) -> None:
        """Raise unless Jama serves a non-empty file for this embed URL."""
        try:
            content = await self._api.get_file_by_url(embed_url)
        except JamaException as e:
            if _is_dead_session(e) or isinstance(e, TooManyRequestsException):
                raise
            raise EmbedVerificationError(
                f"The embed URL {embed_url} does not load ({_describe(e)}). "
                "The image would show as broken.",
                status_code=e.status_code,
            ) from e
        if not content:
            raise EmbedVerificationError(
                f"The embed URL {embed_url} returned an empty file. "
                "The image would show as broken."
            )

    async def upload_attachment(
        self,
        item_id: int,
        file: FileSource,
        name: str | None = None,
        description: str = "",
        file_name: str | None = None,
        project_id: int | None = None,
        link: bool = True,
        link_optional: bool = False,
        verify: bool = True,
        use_cache: bool = True,
        target_is_test_run: bool | None = None,
    ) -> UploadedAttachment:
        """Upload a file, link it to an item and resolve its embed URL.

        A test run is not an item in the REST API: ``items/{id}`` and
        ``items/{id}/attachments`` answer 404 for a test run id. For a test run
        the project is taken from ``testruns/{id}`` and no link is attempted;
        the file can still be embedded by its URL.

        Args:
            item_id: Item (or test run) the attachment belongs to
            file: Path to the file, or its bytes (then ``file_name`` is required)
            name: Attachment name (default: the file name)
            description: Attachment description
            file_name: File name to store (default: the name of ``file``)
            project_id: Project to create the attachment in (default: the item's project)
            link: Link the attachment to the item's Attachments tab
            link_optional: A refused link becomes a warning instead of an error
            verify: Check that the embed URL serves the file
            use_cache: Reuse an earlier upload of the same bytes to the same project
            target_is_test_run: ``True`` if ``item_id`` is known to be a test run,
                ``None`` to find out (only asked when a link or the project needs it)
        """
        actual_name, content = read_source(file, file_name)
        self._check_size(actual_name, content)
        project_id, is_test_run = await self._resolve_target(
            item_id, project_id, link, target_is_test_run
        )
        info: list[str] = []
        if is_test_run and link:
            link = False
            info.append(TEST_RUN_NOT_LINKED)

        cache = self._cache if use_cache else None
        digest = hashlib.sha256(content).hexdigest()
        result: UploadedAttachment | None = None
        linked = False

        entry = cache.get(project_id, digest) if cache else None
        if entry is not None and cache is not None:
            if await self._embed_loads(str(entry["embed_url"])):
                result = UploadedAttachment(
                    attachment_id=int(entry["attachment_id"]),
                    file_id=int(entry["file_id"]),
                    embed_url=str(entry["embed_url"]),
                    name=str(entry["name"]),
                    project_id=project_id,
                    reused=True,
                )
                if link:
                    linked = await self._is_linked(item_id, result.attachment_id)
            else:
                # The attachment is gone on the server: upload it again.
                cache.forget(project_id, digest)

        via_internal = False
        attachment_id = result.attachment_id if result else None
        if attachment_id is None:
            attachment_id, via_internal = await self._create(
                project_id, actual_name, content, name or actual_name, description, item_id
            )
            linked = via_internal

        warnings: list[str] = []
        if link and not linked:
            try:
                await self.link_attachment(item_id, attachment_id)
                linked = True
            except APIClientException as e:
                if (
                    not link_optional
                    or _is_dead_session(e)
                    or isinstance(e, TooManyRequestsException)
                ):
                    raise
                warnings.append(
                    f"Attachment {attachment_id} could not be linked to item {item_id} "
                    f"({_describe(e)}); it will not show on the item's Attachments tab."
                )
        elif via_internal and not link:
            warnings.append(
                "The internal web UI endpoint always links the attachment to the item; "
                "the request not to link it could not be honoured."
            )

        if result is None:
            attachment = await self._api.get_attachment(attachment_id)
            file_id, embed_url = self._embed_url_of(attachment, actual_name)
            if verify:
                await self.verify_embed_url(embed_url)
            result = UploadedAttachment(
                attachment_id=attachment_id,
                file_id=file_id,
                embed_url=embed_url,
                name=actual_name,
                project_id=project_id,
            )
            if cache is not None:
                cache.put(project_id, digest, result)

        result.linked = linked
        result.via_internal_endpoint = via_internal
        result.warnings = warnings
        result.info = info
        result.target_is_test_run = is_test_run
        return result

    async def _resolve_target(
        self,
        item_id: int,
        project_id: int | None,
        link: bool,
        is_test_run: bool | None,
    ) -> tuple[int, bool]:
        """The project to upload to, and whether the target is a test run.

        ``items/{id}`` is only asked when the answer is needed: for the project,
        or to know whether a link can be attempted. A 404 there followed by a hit
        on ``testruns/{id}`` means the id is a test run.
        """
        if is_test_run is None and project_id is not None and not link:
            return project_id, False

        if not is_test_run:
            try:
                item = await self._api.get_item(item_id)
            except ResourceNotFoundException as not_an_item:
                try:
                    run = await self._api.get_test_run(item_id)
                except ResourceNotFoundException:
                    raise not_an_item from None
                return project_id or self._project_of(run, "test run", item_id), True
            return project_id or self._project_of(item, "item", item_id), False

        if project_id is not None:
            return project_id, True
        run = await self._api.get_test_run(item_id)
        return self._project_of(run, "test run", item_id), True

    @staticmethod
    def _project_of(record: dict[str, Any], kind: str, record_id: int) -> int:
        fields = record.get("fields")
        candidates = [record.get("project")]
        if isinstance(fields, dict):
            candidates.append(fields.get("project"))
        for candidate in candidates:
            if isinstance(candidate, int):
                return candidate
        raise AttachmentError(
            f"Could not determine the project of {kind} {record_id}; pass the project id "
            "(--project / project_id)"
        )

    async def fetch_attachment(self, attachment_id: int) -> bytes:
        """The file content of an attachment."""
        return await self._api.get_attachment_file(attachment_id)

    async def fetch_embedded(self, url: str) -> bytes:
        """The content of an embedded file, by its embed URL."""
        return await self._api.get_file_by_url(url)

    async def download_attachment(self, attachment_id: int, output_path: Path) -> Path:
        """Write an attachment's file to ``output_path``."""
        return _write_bytes(output_path, await self.fetch_attachment(attachment_id))

    async def download_embedded(self, url: str, output_path: Path) -> Path:
        """Write an embedded file (by embed URL) to ``output_path``."""
        return _write_bytes(output_path, await self.fetch_embedded(url))


def _write_bytes(output_path: Path, content: bytes) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    return output_path
