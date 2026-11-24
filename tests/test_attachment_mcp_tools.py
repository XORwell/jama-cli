"""Tests for the attachment and test-run-result tools of the stdio MCP server."""

from __future__ import annotations

import base64
import copy
from pathlib import Path
from typing import Any

import pytest

from jama_cli.core.api import JamaApi
from jama_cli.core.attachments import UploadCache
from jama_mcp_server.core import attachment_tools
from jama_mcp_server.core.attachment_tools import AttachmentTools
from jama_mcp_server.core.stdio_server import JamaStdioMCPServer
from jama_mcp_server.models import JamaConfig
from tests.fake_jama_attachments import FakeJamaAttachments
from tests.test_attachments import PNG, make_http

RUN = 77
WRITE_TOOLS = ("upload_attachment", "attach_screenshot_to_test_run", "update_test_run")


@pytest.fixture
def fake() -> FakeJamaAttachments:
    return FakeJamaAttachments()


@pytest.fixture
def server(fake: FakeJamaAttachments, tmp_path: Path) -> JamaStdioMCPServer:
    """A stdio server wired to the fake Jama, with its upload map in tmp_path."""
    config = JamaConfig(url=fake.base, username="user", password="pw")  # noqa: S106
    server = JamaStdioMCPServer(config)
    api = JamaApi(make_http(fake, tmp_path))
    server._api = api
    server._attachment_tools = AttachmentTools(api, UploadCache(tmp_path / "uploads.json"))
    return server


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "shot.png"
    path.write_bytes(PNG)
    return path


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class TestToolDefinitions:
    def test_write_tools_say_that_they_modify_jama(self, server: JamaStdioMCPServer) -> None:
        tools = {tool.name: tool for tool in attachment_tools.tool_definitions()}
        for name in ("upload_attachment", "attach_screenshot_to_test_run"):
            assert "MODIFIES JAMA" in (tools[name].description or "")
        assert "Does not modify Jama" in (tools["download_attachment"].description or "")

    async def test_tools_are_listed_once(self, server: JamaStdioMCPServer) -> None:
        from mcp.types import ListToolsRequest

        handler = server.mcp.request_handlers[ListToolsRequest]
        listed = (await handler(ListToolsRequest(method="tools/list"))).root.tools
        names = [tool.name for tool in listed]

        assert len(names) == len(set(names))
        for name in (*WRITE_TOOLS, "download_attachment", "get_test_run", "get_attachment"):
            assert name in names
        update = next(tool for tool in listed if tool.name == "update_test_run")
        assert "MODIFIES JAMA" in (update.description or "")


class TestUploadAttachmentTool:
    async def test_upload_from_base64(
        self, server: JamaStdioMCPServer, fake: FakeJamaAttachments
    ) -> None:
        result = await server._execute_tool(
            "upload_attachment",
            {"item_id": 10, "content_base64": b64(PNG), "file_name": "remote.png"},
        )

        assert result["attachment_id"] == 500
        assert result["file_id"] == 9000
        assert result["embed_url"] == f"{fake.base}/attachment/9000/remote.png"
        assert fake.files[9000] == ("remote.png", PNG)
        assert fake.links == {10: [500]}

    async def test_upload_from_path_with_explicit_project(
        self, server: JamaStdioMCPServer, fake: FakeJamaAttachments, png: Path
    ) -> None:
        result = await server._execute_tool(
            "upload_attachment",
            {"item_id": 10, "project_id": 5, "file_path": str(png), "name": "N", "link": False},
        )

        assert fake.attachments[result["attachment_id"]]["project"] == 5
        assert fake.attachments[result["attachment_id"]]["fields"]["name"] == "N"
        assert result["linked"] is False

    @pytest.mark.parametrize(
        "arguments",
        [
            {"item_id": 10},
            {"item_id": 10, "content_base64": "aGk="},
            {"item_id": 10, "content_base64": "not base64!", "file_name": "a.png"},
        ],
    )
    async def test_bad_input(self, server: JamaStdioMCPServer, arguments: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            await server._execute_tool("upload_attachment", arguments)


class TestAttachScreenshotTool:
    async def test_base64_screenshot_in_step(
        self, server: JamaStdioMCPServer, fake: FakeJamaAttachments
    ) -> None:
        before = copy.deepcopy(fake.test_runs[RUN]["fields"])

        result = await server._execute_tool(
            "attach_screenshot_to_test_run",
            {
                "test_run_id": RUN,
                "step": 2,
                "caption": "After login",
                "content_base64": b64(PNG),
                "file_name": "remote.png",
            },
        )

        steps = fake.test_runs[RUN]["fields"]["testRunSteps"]
        url = f"{fake.base}/attachment/9000/remote.png"
        assert result["embedded"] == [url]
        assert steps[1]["actualResults"].startswith("<p>Error 500</p><p>After login</p>")
        assert url in steps[1]["actualResults"]
        assert steps[0] == before["testRunSteps"][0]
        assert steps[2] == before["testRunSteps"][2]

    async def test_several_sources_in_one_call(
        self, server: JamaStdioMCPServer, fake: FakeJamaAttachments, png: Path
    ) -> None:
        result = await server._execute_tool(
            "attach_screenshot_to_test_run",
            {
                "test_run_id": RUN,
                "file_paths": [str(png)],
                "files": [{"file_name": "b.png", "content_base64": b64(b"other-bytes")}],
            },
        )

        assert len(result["embedded"]) == 2
        assert len(fake.run_puts) == 1
        assert fake.test_runs[RUN]["fields"]["actualResults"].count("<img ") == 2

    async def test_no_file_given(self, server: JamaStdioMCPServer) -> None:
        with pytest.raises(ValueError, match="file_path"):
            await server._execute_tool("attach_screenshot_to_test_run", {"test_run_id": RUN})


class TestDownloadAttachmentTool:
    async def test_small_file_is_returned_as_base64(
        self, server: JamaStdioMCPServer, png: Path
    ) -> None:
        uploaded = await server._execute_tool(
            "upload_attachment", {"item_id": 10, "file_path": str(png)}
        )

        result = await server._execute_tool(
            "download_attachment", {"attachment_id": uploaded["attachment_id"]}
        )

        assert base64.b64decode(result["content_base64"]) == PNG
        assert result["bytes"] == len(PNG)

    async def test_saved_path_is_returned(
        self, server: JamaStdioMCPServer, png: Path, tmp_path: Path
    ) -> None:
        uploaded = await server._execute_tool(
            "upload_attachment", {"item_id": 10, "file_path": str(png)}
        )
        target = tmp_path / "dl" / "copy.png"

        by_id = await server._execute_tool(
            "download_attachment",
            {"attachment_id": uploaded["attachment_id"], "output_path": str(target)},
        )
        by_url = await server._execute_tool("download_attachment", {"url": uploaded["embed_url"]})

        assert by_id == {
            "bytes": len(PNG),
            "attachment_id": uploaded["attachment_id"],
            "path": str(target),
        }
        assert target.read_bytes() == PNG
        assert base64.b64decode(by_url["content_base64"]) == PNG

    async def test_large_file_needs_an_output_path(
        self,
        server: JamaStdioMCPServer,
        png: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        uploaded = await server._execute_tool(
            "upload_attachment", {"item_id": 10, "file_path": str(png)}
        )
        monkeypatch.setattr(attachment_tools, "MAX_INLINE_BYTES", 8)

        with pytest.raises(Exception, match="output_path"):
            await server._execute_tool(
                "download_attachment", {"attachment_id": uploaded["attachment_id"]}
            )

    async def test_needs_exactly_one_source(self, server: JamaStdioMCPServer) -> None:
        with pytest.raises(ValueError):
            await server._execute_tool("download_attachment", {})


class TestUpdateTestRunTool:
    async def test_partial_update_cannot_wipe_other_steps(
        self, server: JamaStdioMCPServer, fake: FakeJamaAttachments
    ) -> None:
        """The old tool sent ``data`` as the whole PUT body: a one-step list
        replaced all steps."""
        before = copy.deepcopy(fake.test_runs[RUN]["fields"])

        await server._execute_tool(
            "update_test_run",
            {"test_run_id": RUN, "data": {"fields": {"testRunSteps": [{"status": "BLOCKED"}]}}},
        )

        fields = fake.test_runs[RUN]["fields"]
        assert len(fields["testRunSteps"]) == 3
        assert fields["testRunSteps"][0] == {**before["testRunSteps"][0], "status": "BLOCKED"}
        assert fields["testRunSteps"][1:] == before["testRunSteps"][1:]
        assert fields["actualResults"] == before["actualResults"]
        assert fields["assignedTo"] == before["assignedTo"]

    async def test_step_fields(self, server: JamaStdioMCPServer, fake: FakeJamaAttachments) -> None:
        result = await server._execute_tool(
            "update_test_run", {"test_run_id": RUN, "step": 3, "step_fields": {"status": "PASSED"}}
        )

        assert result["updated_steps"] == [3]
        assert fake.test_runs[RUN]["fields"]["testRunSteps"][2]["status"] == "PASSED"

    async def test_get_test_run(self, server: JamaStdioMCPServer) -> None:
        run = await server._execute_tool("get_test_run", {"test_run_id": RUN})

        assert len(run["fields"]["testRunSteps"]) == 3
