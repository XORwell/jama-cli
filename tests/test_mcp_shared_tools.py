"""The attachment / test run tools come from one registry used by both MCP servers."""

from __future__ import annotations

import base64
import importlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from mcp import types

from jama_cli.core.api import JamaApi
from jama_cli.core.attachments import UploadCache
from jama_mcp_server.core import attachment_tools
from jama_mcp_server.core.attachment_tools import AttachmentTools, FileAccessPolicy, LocalPathError
from jama_mcp_server.core.server import JamaMCPServer
from jama_mcp_server.core.stdio_server import JamaStdioMCPServer
from jama_mcp_server.models import JamaConfig, MCPRequest
from tests.fake_jama_attachments import FRESH_RUN, FakeJamaAttachments
from tests.test_attachments import PNG, make_http

SHARED = {
    "get_test_run",
    "update_test_run",
    "upload_attachment",
    "attach_screenshot_to_test_run",
    "download_attachment",
}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.fixture
def fake() -> FakeJamaAttachments:
    return FakeJamaAttachments()


def make_http_server(fake: FakeJamaAttachments, tmp_path: Path, **kwargs: Any) -> JamaMCPServer:
    """An HTTP-mode server whose shared tools talk to the fake Jama."""
    config = JamaConfig(url=fake.base, username="user", password="pw")  # noqa: S106
    server = JamaMCPServer(config=config, **kwargs)
    server.jama_client = object()  # the legacy client is not used by the shared tools
    api = JamaApi(make_http(fake, tmp_path))
    server._shared_tools = AttachmentTools(
        api, UploadCache(tmp_path / "uploads.json"), files=server.file_policy
    )
    return server


async def invoke(
    server: JamaMCPServer, intent: str, **parameters: Any
) -> tuple[Any, dict[str, Any]]:
    """Call a tool the way POST /v1/invoke does; returns (decoded response, metadata)."""
    request = MCPRequest(prompt=intent, parameters={"intent": intent, **parameters})
    response = await server.handle_request(request)
    return json.loads(response.response), response.metadata or {}


# ---------------------------------------------------------------------------
# One registry, the same tool set in both servers
# ---------------------------------------------------------------------------


class TestOneRegistry:
    def test_registry_holds_the_shared_tools(self) -> None:
        assert set(attachment_tools.TOOL_NAMES) == SHARED
        names = [tool.name for tool in attachment_tools.tool_definitions()]
        assert len(names) == len(set(names))

    async def test_both_servers_expose_the_same_shared_tool_set(self) -> None:
        config = JamaConfig(url="https://jama.example.com", api_key="k")

        stdio = JamaStdioMCPServer(config)
        handler = stdio.mcp.request_handlers[types.ListToolsRequest]
        listed = (await handler(types.ListToolsRequest(method="tools/list"))).root.tools
        from_stdio = {
            tool.name: (tool.description, tool.inputSchema)
            for tool in listed
            if tool.name in attachment_tools.TOOL_NAMES
        }
        from_http = {
            tool["name"]: (tool["description"], tool["inputSchema"])
            for tool in JamaMCPServer(config=config).shared_tools()
        }

        assert set(from_stdio) == set(from_http) == SHARED
        # Not merely the same names: the very same definitions.
        assert from_stdio == from_http

    def test_definitions_exist_in_one_module_only(self) -> None:
        """Neither server defines these tools itself; both import the registry."""
        for module_name in ("stdio_server", "server"):
            module = importlib.import_module(f"jama_mcp_server.core.{module_name}")
            source = Path(str(module.__file__)).read_text()
            assert "attachment_tools" in source
            for name in SHARED:
                assert f'name="{name}"' not in source, f"{name} is defined in {module.__name__}"

    async def test_http_tools_endpoint_lists_them(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        server = make_http_server(fake, tmp_path)

        response = await server._handle_tools(None)  # type: ignore[arg-type]

        listed = json.loads(response.body)["tools"]  # type: ignore[arg-type]
        assert {tool["name"] for tool in listed} == SHARED
        assert all(tool["inputSchema"]["type"] == "object" for tool in listed)


# ---------------------------------------------------------------------------
# HTTP mode: the tools work, files travel as base64
# ---------------------------------------------------------------------------


class TestHttpMode:
    async def test_upload_attachment_from_base64(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        server = make_http_server(fake, tmp_path)

        result, metadata = await invoke(
            server,
            "upload_attachment",
            item_id=10,
            content_base64=b64(PNG),
            file_name="remote.png",
        )

        assert metadata["status"] == "success"
        assert result["attachment_id"] == 500 and result["file_id"] == 9000
        assert result["embed_url"] == f"{fake.base}/attachment/9000/remote.png"
        assert fake.files[9000] == ("remote.png", PNG)

    async def test_test_run_tools(self, fake: FakeJamaAttachments, tmp_path: Path) -> None:
        server = make_http_server(fake, tmp_path)

        run, _ = await invoke(server, "get_test_run", test_run_id=FRESH_RUN)
        assert "result" not in run["fields"]["testRunSteps"][0]

        updated, metadata = await invoke(
            server,
            "update_test_run",
            test_run_id=FRESH_RUN,
            step=1,
            step_fields={"status": "PASSED", "result": "<p>ok</p>"},
        )
        assert metadata["status"] == "success" and updated["updated_steps"] == [1]

        shot, _ = await invoke(
            server,
            "attach_screenshot_to_test_run",
            test_run_id=FRESH_RUN,
            step=1,
            content_base64=b64(PNG),
            file_name="shot.png",
        )
        step = fake.test_runs[FRESH_RUN]["fields"]["testRunSteps"][0]
        assert step["status"] == "PASSED"
        assert step["result"].startswith("<p>ok</p>") and shot["embedded"][0] in step["result"]

    async def test_download_returns_base64(self, fake: FakeJamaAttachments, tmp_path: Path) -> None:
        server = make_http_server(fake, tmp_path)
        uploaded, _ = await invoke(
            server, "upload_attachment", item_id=10, content_base64=b64(PNG), file_name="a.png"
        )

        result, _ = await invoke(
            server, "download_attachment", attachment_id=uploaded["attachment_id"]
        )

        assert base64.b64decode(result["content_base64"]) == PNG

    @pytest.mark.parametrize(
        ("intent", "parameters"),
        [
            ("upload_attachment", {"item_id": 10, "file_path": "/etc/hostname"}),
            ("attach_screenshot_to_test_run", {"test_run_id": 77, "file_path": "/etc/hostname"}),
            ("attach_screenshot_to_test_run", {"test_run_id": 77, "file_paths": ["/etc/hostname"]}),
            ("download_attachment", {"attachment_id": 1, "output_path": "/tmp/out.bin"}),
        ],
    )
    async def test_file_paths_are_refused_by_default(
        self,
        fake: FakeJamaAttachments,
        tmp_path: Path,
        intent: str,
        parameters: dict[str, Any],
    ) -> None:
        server = make_http_server(fake, tmp_path)

        result, metadata = await invoke(server, intent, **parameters)

        assert metadata["status"] == "error"
        assert "local file paths are disabled" in result["error"]
        assert "content_base64" in result["error"]
        # Refused before Jama was asked for anything.
        assert fake.requests == []

    async def test_paths_inside_the_configured_directory(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        allowed = tmp_path / "exchange"
        allowed.mkdir()
        (allowed / "in.png").write_bytes(PNG)
        server = make_http_server(fake, tmp_path, allow_local_paths=True, local_path_dir=allowed)

        uploaded, metadata = await invoke(
            server, "upload_attachment", item_id=10, file_path="in.png"
        )
        assert metadata["status"] == "success"
        assert fake.files[uploaded["file_id"]] == ("in.png", PNG)

        saved, _ = await invoke(
            server,
            "download_attachment",
            attachment_id=uploaded["attachment_id"],
            output_path=str(allowed / "sub" / "out.png"),
        )
        assert Path(saved["path"]).read_bytes() == PNG

    async def test_paths_outside_the_directory_are_refused(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        allowed = tmp_path / "exchange"
        allowed.mkdir()
        secret = tmp_path / "secret.png"
        secret.write_bytes(PNG)
        os.symlink(secret, allowed / "link.png")
        server = make_http_server(fake, tmp_path, allow_local_paths=True, local_path_dir=allowed)

        for path in (str(secret), "../secret.png", "link.png", str(allowed) + "-other/x.png"):
            result, metadata = await invoke(server, "upload_attachment", item_id=10, file_path=path)
            assert metadata["status"] == "error", path
            assert "outside the directory" in result["error"]
            # The configured directory is not disclosed to the caller.
            assert str(allowed) not in result["error"]
        assert fake.attachments == {}

    def test_enabling_paths_needs_a_directory(self) -> None:
        config = JamaConfig(url="https://jama.example.com", api_key="k")
        with pytest.raises(ValueError, match="need a directory"):
            JamaMCPServer(config=config, allow_local_paths=True)


class TestFileAccessPolicy:
    def test_stdio_default_allows_any_path(self, tmp_path: Path) -> None:
        policy = FileAccessPolicy.stdio()
        assert policy.resolve(str(tmp_path / "a.png")) == tmp_path / "a.png"
        config = JamaConfig(url="https://jama.example.com", api_key="k")
        assert AttachmentTools(JamaApi(object())).files == policy  # type: ignore[arg-type]
        assert JamaMCPServer(config=config).file_policy.allow_local_paths is False

    def test_http_default_refuses(self) -> None:
        with pytest.raises(LocalPathError):
            FileAccessPolicy.http().resolve("anything.png")

    def test_cli_requires_the_directory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner

        from jama_cli.main import app

        for name in ("JAMA_MCP_ALLOW_LOCAL_PATHS", "JAMA_MCP_LOCAL_PATH_DIR", "JAMA_AUTH_TYPE"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("JAMA_URL", "https://jama.example.com")
        monkeypatch.setenv("JAMA_API_KEY", "k")

        result = CliRunner().invoke(app, ["serve", "--allow-local-paths"])

        assert result.exit_code == 1
        assert "--local-path-dir" in " ".join(result.output.split())
