"""Shared registry of the attachment and test-run-result tools.

Both MCP servers use this one module: the stdio server (``stdio_server.py``)
lists and dispatches these tools, and the HTTP server (``server.py``) serves
the same definitions under ``/v1/tools`` and dispatches the same handlers. The
definitions and handlers exist only here, so the two servers cannot drift.

File input differs by transport. A stdio server runs on the user's machine, so
a path is fine. An HTTP server may be reached from elsewhere, so by default it
only takes base64 content; paths are accepted only when the server was started
with local paths allowed, and then only inside one configured directory
(:class:`FileAccessPolicy`).
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.types import Tool

from jama_cli.core.api import JamaApi
from jama_cli.core.attachments import (
    AttachmentError,
    AttachmentService,
    UploadCache,
    default_upload_cache_path,
)
from jama_cli.core.http_client import JamaHttpClient
from jama_cli.core.testruns import TestRunService

# Largest file returned inline (base64) by ``download_attachment``.
MAX_INLINE_BYTES = 1024 * 1024

_PATH_NOTE = (
    "Only if the server allows local paths (always under stdio; over HTTP only when "
    "started with local paths enabled, and then inside its configured directory)"
)


class LocalPathError(ValueError):
    """A file path was given to a server that does not accept it."""


@dataclass(frozen=True)
class FileAccessPolicy:
    """Whether, and where, a tool may read or write files on the server's machine.

    ``allow_local_paths=False`` refuses every path. With a ``base_dir`` a path
    must resolve (symlinks and ``..`` followed) to a location inside it.
    """

    allow_local_paths: bool = True
    base_dir: Path | None = None

    @classmethod
    def stdio(cls) -> FileAccessPolicy:
        """The stdio server runs as the user on the user's machine: paths are fine."""
        return cls(allow_local_paths=True, base_dir=None)

    @classmethod
    def http(
        cls, allow_local_paths: bool = False, base_dir: Path | str | None = None
    ) -> FileAccessPolicy:
        """The HTTP server: no paths unless enabled, and then only below ``base_dir``."""
        if allow_local_paths and not base_dir:
            raise ValueError(
                "Local file paths over HTTP need a directory to confine them to "
                "(--local-path-dir / JAMA_MCP_LOCAL_PATH_DIR)."
            )
        directory = Path(base_dir).expanduser().resolve() if base_dir else None
        return cls(allow_local_paths=allow_local_paths, base_dir=directory)

    def resolve(self, raw: str, argument: str = "file_path") -> Path:
        """The path to use for ``raw``, or :class:`LocalPathError` if it is not allowed."""
        if not self.allow_local_paths:
            raise LocalPathError(
                f"{argument} is not accepted by this server: local file paths are disabled. "
                "Send the file as content_base64 + file_name instead."
            )
        path = Path(raw).expanduser()
        if self.base_dir is None:
            return path
        candidate = path if path.is_absolute() else self.base_dir / path
        resolved = candidate.resolve()
        if resolved != self.base_dir and self.base_dir not in resolved.parents:
            # The directory is not named: it is server configuration.
            raise LocalPathError(
                f"{argument} is outside the directory this server allows file access in."
            )
        return resolved


_FILE_PROPERTIES: dict[str, Any] = {
    "file_path": {
        "type": "string",
        "description": f"Path of the file ON THE MACHINE RUNNING THIS SERVER. {_PATH_NOTE}",
    },
    "content_base64": {
        "type": "string",
        "description": (
            "Base64-encoded file content (use this when the file is not on the "
            "server's machine, and always over HTTP unless paths are enabled); "
            "requires file_name"
        ),
    },
    "file_name": {
        "type": "string",
        "description": "File name with extension, e.g. screenshot.png (required with content_base64)",
    },
}


def tool_definitions() -> list[Tool]:
    """The attachment and test-run-result tools."""
    return [
        Tool(
            name="get_test_run",
            description=(
                "Get a test run with its steps, statuses and actual results. Jama leaves "
                "empty fields out: a run without 'actualResults', or a step without "
                "'result' (the step's actual results), has none yet."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "test_run_id": {"type": "integer", "description": "Test run ID"},
                },
                "required": ["test_run_id"],
            },
        ),
        Tool(
            name="update_test_run",
            description=(
                "Modifies Jama: partial update of a test run (e.g. set a step's "
                "status or result). The given values are merged into the current "
                "run, so steps and fields that are not named are kept. In "
                "data.fields.testRunSteps entry N updates step N ({} or null leaves "
                "a step alone); or use step + step_fields to update one step. The "
                "actual results of a step are its key 'result' (a step key "
                "'actualResults' is written as 'result'); the update fails if Jama "
                "did not store a step value."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "test_run_id": {"type": "integer", "description": "Test run ID"},
                    "data": {
                        "type": "object",
                        "description": 'Fields to update: {"fields": {...}}',
                    },
                    "step": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Step number, from 1 (with step_fields)",
                    },
                    "step_fields": {
                        "type": "object",
                        "description": (
                            'Keys to set on that step, e.g. {"status": "PASSED"} or '
                            '{"result": "<p>...</p>"}'
                        ),
                    },
                },
                "required": ["test_run_id"],
            },
        ),
        Tool(
            name="upload_attachment",
            description=(
                "Modifies Jama: uploads a file as a new attachment and links it to an item "
                "(it shows on the item's Attachments tab). Returns the attachment id, the "
                "stored file's id and the embed URL to use for an inline image. Give either "
                "file_path or content_base64 + file_name. item_id may be a test run id: "
                "test runs are not items in the REST API, so the attachment is created in "
                "the run's project but not linked (linked: false with an info entry); the "
                "embed URL works without the link."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "integer",
                        "description": "Item (or test run) to attach the file to",
                    },
                    "project_id": {
                        "type": "integer",
                        "description": (
                            "Project for the attachment (default: the project of the item "
                            "or test run)"
                        ),
                    },
                    **_FILE_PROPERTIES,
                    "name": {
                        "type": "string",
                        "description": "Attachment name (default: the file name)",
                    },
                    "description": {"type": "string", "description": "Attachment description"},
                    "link": {
                        "type": "boolean",
                        "description": "Link the attachment to the item (default true)",
                    },
                },
                "required": ["item_id"],
            },
        ),
        Tool(
            name="attach_screenshot_to_test_run",
            description=(
                "Modifies Jama: uploads one or more images as attachments and embeds them in "
                "the 'Actual results' of a test run, or in the 'result' of one step when "
                "step is given. The "
                "images are APPENDED; existing content, other steps and step statuses are kept. "
                "Give file_path, file_paths, content_base64 + file_name, or files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "test_run_id": {"type": "integer", "description": "Test run ID"},
                    "step": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Step number, from 1. Omit for the run-level actual results.",
                    },
                    "caption": {
                        "type": "string",
                        "description": "Plain text shown above each image (optional)",
                    },
                    **_FILE_PROPERTIES,
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": f"Several file paths on the server's machine. {_PATH_NOTE}",
                    },
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_name": {"type": "string"},
                                "content_base64": {"type": "string"},
                            },
                            "required": ["file_name", "content_base64"],
                        },
                        "description": "Several files as base64 content",
                    },
                    "project_id": {
                        "type": "integer",
                        "description": "Project for the attachments (default: the run's project)",
                    },
                },
                "required": ["test_run_id"],
            },
        ),
        Tool(
            name="download_attachment",
            description=(
                "Download a file from Jama: an attachment by attachment_id, or an embedded "
                "file (inline image) by url. With output_path the file is saved on the machine "
                "running this server and the path is returned; without it, files up to 1 MB "
                "are returned as base64. Does not modify Jama."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "attachment_id": {"type": "integer", "description": "Attachment ID"},
                    "url": {
                        "type": "string",
                        "description": "Embed URL of an inline file (instead of attachment_id)",
                    },
                    "output_path": {
                        "type": "string",
                        "description": (
                            f"Where to save the file on the server's machine (optional). {_PATH_NOTE}"
                        ),
                    },
                },
            },
        ),
    ]


TOOL_NAMES: frozenset[str] = frozenset(tool.name for tool in tool_definitions())


def tool_listing() -> list[dict[str, Any]]:
    """The shared tools as plain data (name, description, input schema)."""
    return [
        {"name": tool.name, "description": tool.description, "inputSchema": tool.inputSchema}
        for tool in tool_definitions()
    ]


def http_client_for(config: Any) -> JamaHttpClient:
    """An async Jama client for a server ``JamaConfig`` (OAuth, API key or basic)."""
    if config.client_id and config.client_secret:
        return JamaHttpClient(
            base_url=config.url, credentials=(config.client_id, config.client_secret), oauth=True
        )
    if config.api_key:
        return JamaHttpClient(base_url=config.url, credentials=(config.api_key, ""))
    return JamaHttpClient(
        base_url=config.url, credentials=(config.username, config.password), oauth=config.oauth
    )


def _decode(content_base64: str, file_name: str | None) -> tuple[str, bytes]:
    if not file_name:
        raise ValueError("file_name is required with content_base64")
    try:
        return file_name, base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(f"content_base64 of {file_name} is not valid base64") from None


class AttachmentTools:
    """Handlers of the attachment and test-run-result tools."""

    def __init__(
        self,
        api: JamaApi,
        cache: UploadCache | None = None,
        files: FileAccessPolicy | None = None,
    ) -> None:
        self.attachments = AttachmentService(api, cache=cache)
        self.test_runs = TestRunService(api, self.attachments)
        self.files = files or FileAccessPolicy.stdio()

    @classmethod
    def for_api(cls, api: JamaApi, files: FileAccessPolicy | None = None) -> AttachmentTools:
        """Handlers with the default local upload map for this Jama instance."""
        base_url = api.base_url
        if not isinstance(base_url, str):
            return cls(api, files=files)
        return cls(api, UploadCache(default_upload_cache_path(base_url)), files=files)

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "get_test_run":
            return await self.test_runs.get_test_run(arguments["test_run_id"])
        if name == "upload_attachment":
            return await self._upload_attachment(arguments)
        if name == "attach_screenshot_to_test_run":
            return await self._attach_screenshot(arguments)
        if name == "download_attachment":
            return await self._download(arguments)
        if name == "update_test_run":
            if not arguments.get("data") and not arguments.get("step_fields"):
                raise ValueError("Give data, or step + step_fields")
            return await self.test_runs.update_test_run(
                arguments["test_run_id"],
                arguments.get("data"),
                step=arguments.get("step"),
                step_fields=arguments.get("step_fields"),
            )
        raise ValueError(f"Unknown tool: {name}")

    async def _upload_attachment(self, arguments: dict[str, Any]) -> dict[str, Any]:
        file_name = arguments.get("file_name")
        source: Path | bytes
        if arguments.get("content_base64"):
            file_name, source = _decode(arguments["content_base64"], file_name)
        elif arguments.get("file_path"):
            source = self.files.resolve(arguments["file_path"])
        else:
            raise ValueError("Give file_path or content_base64 + file_name")
        uploaded = await self.attachments.upload_attachment(
            arguments["item_id"],
            source,
            name=arguments.get("name"),
            description=arguments.get("description") or "",
            file_name=file_name,
            project_id=arguments.get("project_id"),
            link=arguments.get("link", True),
        )
        return uploaded.to_dict()

    async def _attach_screenshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        sources: list[Path | str | bytes | tuple[str, bytes]] = []
        if arguments.get("file_path"):
            sources.append(self.files.resolve(arguments["file_path"]))
        sources += [self.files.resolve(p, "file_paths") for p in arguments.get("file_paths") or []]
        if arguments.get("content_base64"):
            sources.append(_decode(arguments["content_base64"], arguments.get("file_name")))
        for entry in arguments.get("files") or []:
            sources.append(_decode(entry["content_base64"], entry.get("file_name")))
        if not sources:
            raise ValueError("Give file_path, file_paths, content_base64 + file_name, or files")
        result = await self.test_runs.attach_screenshots_to_test_run(
            arguments["test_run_id"],
            sources,
            step=arguments.get("step"),
            caption=arguments.get("caption"),
            project_id=arguments.get("project_id"),
        )
        return result.to_dict()

    async def _download(self, arguments: dict[str, Any]) -> dict[str, Any]:
        attachment_id = arguments.get("attachment_id")
        url = arguments.get("url")
        if (attachment_id is None) == (not url):
            raise ValueError("Give exactly one of attachment_id or url")
        # Decided before anything is fetched.
        output = (
            self.files.resolve(arguments["output_path"], "output_path")
            if arguments.get("output_path")
            else None
        )
        if url:
            content = await self.attachments.fetch_embedded(url)
        else:
            content = await self.attachments.fetch_attachment(int(attachment_id))  # type: ignore[arg-type]

        result: dict[str, Any] = {"bytes": len(content)}
        if attachment_id is not None:
            result["attachment_id"] = attachment_id
        else:
            result["url"] = url
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            result["path"] = str(output)
            return result
        if len(content) > MAX_INLINE_BYTES:
            raise AttachmentError(
                f"The file is {len(content)} bytes, too large to return inline "
                f"(limit {MAX_INLINE_BYTES}); pass output_path to save it instead"
            )
        result["content_base64"] = base64.b64encode(content).decode("ascii")
        return result
