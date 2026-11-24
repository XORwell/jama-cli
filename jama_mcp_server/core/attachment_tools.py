"""MCP tools for attachments and test run results (stdio server).

Kept apart from ``stdio_server.py``: the tool definitions and their handlers
live here, the server only registers and dispatches them.
"""

from __future__ import annotations

import base64
import binascii
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
from jama_cli.core.testruns import TestRunService

# Largest file returned inline (base64) by ``download_attachment``.
MAX_INLINE_BYTES = 1024 * 1024

_FILE_PROPERTIES: dict[str, Any] = {
    "file_path": {
        "type": "string",
        "description": "Path of the file ON THE MACHINE RUNNING THIS SERVER",
    },
    "content_base64": {
        "type": "string",
        "description": (
            "Base64-encoded file content (use this when the file is not on the "
            "server's machine); requires file_name"
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
            description="Get a test run with its steps, statuses and actual results",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_run_id": {"type": "integer", "description": "Test run ID"},
                },
                "required": ["test_run_id"],
            },
        ),
        Tool(
            name="upload_attachment",
            description=(
                "MODIFIES JAMA: uploads a file as a new attachment and links it to an item "
                "(it shows on the item's Attachments tab). Returns the attachment id, the "
                "stored file's id and the embed URL to use for an inline image. Give either "
                "file_path or content_base64 + file_name."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "Item to attach the file to"},
                    "project_id": {
                        "type": "integer",
                        "description": "Project for the attachment (default: the item's project)",
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
                "MODIFIES JAMA: uploads one or more images as attachments and embeds them in "
                "the 'Actual results' of a test run, or of one step when step is given. The "
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
                        "description": "Several file paths on the machine running this server",
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
                        "description": "Where to save the file on the server's machine (optional)",
                    },
                },
            },
        ),
    ]


TOOL_NAMES: frozenset[str] = frozenset(tool.name for tool in tool_definitions()) | {
    "update_test_run"
}


def _decode(content_base64: str, file_name: str | None) -> tuple[str, bytes]:
    if not file_name:
        raise ValueError("file_name is required with content_base64")
    try:
        return file_name, base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(f"content_base64 of {file_name} is not valid base64") from None


class AttachmentTools:
    """Handlers of the attachment and test-run-result tools."""

    def __init__(self, api: JamaApi, cache: UploadCache | None = None) -> None:
        self.attachments = AttachmentService(api, cache=cache)
        self.test_runs = TestRunService(api, self.attachments)

    @classmethod
    def for_api(cls, api: JamaApi) -> AttachmentTools:
        """Handlers with the default local upload map for this Jama instance."""
        return cls(api, UploadCache(default_upload_cache_path(api.base_url)))

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
            source = Path(arguments["file_path"])
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
            sources.append(Path(arguments["file_path"]))
        sources += [Path(p) for p in arguments.get("file_paths") or []]
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
        if url:
            content = await self.attachments.fetch_embedded(url)
        else:
            content = await self.attachments.fetch_attachment(int(attachment_id))  # type: ignore[arg-type]

        result: dict[str, Any] = {"bytes": len(content)}
        if attachment_id is not None:
            result["attachment_id"] = attachment_id
        else:
            result["url"] = url
        if arguments.get("output_path"):
            path = Path(arguments["output_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            result["path"] = str(path)
            return result
        if len(content) > MAX_INLINE_BYTES:
            raise AttachmentError(
                f"The file is {len(content)} bytes, too large to return inline "
                f"(limit {MAX_INLINE_BYTES}); pass output_path to save it instead"
            )
        result["content_base64"] = base64.b64encode(content).decode("ascii")
        return result
