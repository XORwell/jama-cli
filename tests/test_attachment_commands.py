"""Tests for the attachments and testruns CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from jama_cli.commands.attachments import app as attachments_app
from jama_cli.commands.testruns import app as testruns_app
from jama_cli.core.exceptions import APIClientException
from jama_cli.main import app as main_app

runner = CliRunner()

UPLOAD_RESULT = {
    "attachment_id": 500,
    "file_id": 9000,
    "embed_url": "https://jama.example.com/contour/attachment/9000/shot.png",
    "name": "shot.png",
    "project_id": 3,
    "linked": True,
    "reused": False,
    "via_internal_endpoint": False,
    "warnings": [],
}


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "shot.png"
    path.write_bytes(b"png-bytes")
    return path


@pytest.fixture
def attachments_client():
    with (
        patch("jama_cli.commands.attachments.get_profile_or_env") as profile,
        patch("jama_cli.commands.attachments.JamaClient") as client_class,
    ):
        profile.return_value = MagicMock()
        client = MagicMock()
        client_class.return_value = client
        yield client


@pytest.fixture
def testruns_client():
    with (
        patch("jama_cli.commands.testruns.get_profile_or_env") as profile,
        patch("jama_cli.commands.testruns.JamaClient") as client_class,
    ):
        profile.return_value = MagicMock()
        client = MagicMock()
        client_class.return_value = client
        yield client


class TestAttachmentsUpload:
    def test_upload_prints_ids_and_embed_url(self, attachments_client, png):
        attachments_client.upload_attachment.return_value = dict(UPLOAD_RESULT)

        result = runner.invoke(attachments_app, ["upload", "10", str(png)])

        assert result.exit_code == 0
        assert "Uploaded attachment with ID: 500" in result.stdout
        assert "File ID: 9000" in result.stdout
        assert "https://jama.example.com/contour/attachment/9000/shot.png" in result.stdout
        attachments_client.upload_attachment.assert_called_once_with(
            10, png, name=None, description="", project_id=None, link=True, use_cache=True
        )

    def test_upload_options(self, attachments_client, png):
        attachments_client.upload_attachment.return_value = dict(UPLOAD_RESULT, linked=False)

        result = runner.invoke(
            attachments_app,
            ["upload", "10", str(png), "--name", "N", "--description", "D", "--no-link"],
        )

        assert result.exit_code == 0
        attachments_client.upload_attachment.assert_called_once_with(
            10, png, name="N", description="D", project_id=None, link=False, use_cache=True
        )

    def test_upload_with_project_for_a_test_run(self, attachments_client, png):
        attachments_client.upload_attachment.return_value = dict(
            UPLOAD_RESULT,
            linked=False,
            target_is_test_run=True,
            info=["Test runs have no Attachments tab via REST, so the attachment was not linked"],
        )

        result = runner.invoke(attachments_app, ["upload", "77", str(png), "--project", "3"])

        assert result.exit_code == 0
        attachments_client.upload_attachment.assert_called_once_with(
            77, png, name=None, description="", project_id=3, link=True, use_cache=True
        )
        assert "Linked to test run 77: no" in result.stdout
        assert "no Attachments tab via REST" in " ".join(result.output.split())
        assert "Warning" not in result.output

    def test_upload_json(self, attachments_client, png):
        attachments_client.upload_attachment.return_value = dict(UPLOAD_RESULT)

        result = runner.invoke(attachments_app, ["upload", "10", str(png), "--json"])

        assert result.exit_code == 0
        assert json.loads(result.stdout) == UPLOAD_RESULT

    def test_upload_failure_exits_non_zero(self, attachments_client, png):
        attachments_client.upload_attachment.side_effect = APIClientException(
            "Forbidden", status_code=403
        )

        result = runner.invoke(attachments_app, ["upload", "10", str(png)])

        assert result.exit_code == 1

    def test_upload_missing_file(self, attachments_client, tmp_path):
        result = runner.invoke(attachments_app, ["upload", "10", str(tmp_path / "nope.png")])

        assert result.exit_code == 1
        attachments_client.upload_attachment.assert_not_called()


class TestAttachmentsDownload:
    def test_download(self, attachments_client, tmp_path):
        target = tmp_path / "out.png"
        target.write_bytes(b"12345")
        attachments_client.download_attachment.return_value = target

        result = runner.invoke(attachments_app, ["download", "500", "-o", str(target), "--json"])

        assert result.exit_code == 0
        assert json.loads(result.stdout) == {
            "attachment_id": 500,
            "path": str(target),
            "bytes": 5,
        }
        attachments_client.download_attachment.assert_called_once_with(500, target)

    def test_download_requires_output(self, attachments_client):
        result = runner.invoke(attachments_app, ["download", "500"])

        assert result.exit_code != 0
        attachments_client.download_attachment.assert_not_called()

    def test_download_url(self, attachments_client, tmp_path):
        target = tmp_path / "out.png"
        target.write_bytes(b"123")
        attachments_client.download_embedded.return_value = target
        url = "https://jama.example.com/contour/attachment/9000/shot.png"

        result = runner.invoke(attachments_app, ["download-url", url, "-o", str(target)])

        assert result.exit_code == 0
        attachments_client.download_embedded.assert_called_once_with(url, target)

    def test_download_failure_exits_non_zero(self, attachments_client, tmp_path):
        attachments_client.download_attachment.side_effect = RuntimeError("boom")

        result = runner.invoke(attachments_app, ["download", "500", "-o", str(tmp_path / "x")])

        assert result.exit_code == 1

    def test_existing_get_command_still_works(self, attachments_client):
        attachments_client.get_attachment.return_value = {"id": 1, "fileName": "test.txt"}

        result = runner.invoke(attachments_app, ["get", "1"])

        assert result.exit_code == 0


class TestTestrunsCommands:
    def test_group_is_registered(self):
        result = runner.invoke(main_app, ["testruns", "--help"])

        assert result.exit_code == 0
        for command in ("add-screenshot", "set-actual", "get"):
            assert command in result.stdout

    def test_existing_tests_group_is_unchanged(self):
        result = runner.invoke(main_app, ["tests", "--help"])

        assert result.exit_code == 0
        assert "cycle" in result.stdout and "runs" in result.stdout

    def test_add_screenshot(self, testruns_client, png, tmp_path):
        second = tmp_path / "second.png"
        second.write_bytes(b"x")
        testruns_client.attach_screenshots_to_test_run.return_value = {
            "test_run_id": 77,
            "step": 2,
            "updated": True,
            "attachments": [dict(UPLOAD_RESULT)],
            "embedded": [UPLOAD_RESULT["embed_url"]],
            "skipped": [],
            "warnings": [],
        }

        result = runner.invoke(
            testruns_app,
            ["add-screenshot", "77", str(png), str(second), "--step", "2", "--caption", "After"],
        )

        assert result.exit_code == 0
        testruns_client.attach_screenshots_to_test_run.assert_called_once_with(
            77, [png, second], step=2, caption="After", project_id=None, use_cache=True
        )
        assert "step 2 of test run 77" in result.stdout
        assert UPLOAD_RESULT["embed_url"] in result.stdout

    def test_add_screenshot_json_and_warning(self, testruns_client, png):
        payload = {
            "test_run_id": 77,
            "step": None,
            "updated": True,
            "attachments": [dict(UPLOAD_RESULT, linked=False)],
            "embedded": [UPLOAD_RESULT["embed_url"]],
            "skipped": [],
            "warnings": ["Attachment 500 could not be linked to item 77"],
        }
        testruns_client.attach_screenshots_to_test_run.return_value = payload

        result = runner.invoke(testruns_app, ["add-screenshot", "77", str(png), "--json"])

        assert result.exit_code == 0
        assert json.loads(result.stdout) == payload

    def test_add_screenshot_missing_file(self, testruns_client, tmp_path):
        result = runner.invoke(testruns_app, ["add-screenshot", "77", str(tmp_path / "no.png")])

        assert result.exit_code == 1
        testruns_client.attach_screenshots_to_test_run.assert_not_called()

    def test_add_screenshot_failure(self, testruns_client, png):
        testruns_client.attach_screenshots_to_test_run.side_effect = APIClientException(
            "Test run is locked", status_code=400
        )

        result = runner.invoke(testruns_app, ["add-screenshot", "77", str(png)])

        assert result.exit_code == 1

    def test_set_actual_appends_by_default(self, testruns_client):
        testruns_client.append_to_actual_results.return_value = {"updated": True, "warnings": []}

        result = runner.invoke(testruns_app, ["set-actual", "77", "--html", "<p>x</p>"])

        assert result.exit_code == 0
        testruns_client.append_to_actual_results.assert_called_once_with(
            77, "<p>x</p>", step=None, mode="append"
        )

    def test_set_actual_from_file_with_step_and_replace(self, testruns_client, tmp_path):
        source = tmp_path / "result.html"
        source.write_text("<p>from file</p>", encoding="utf-8")
        testruns_client.append_to_actual_results.return_value = {"updated": True, "warnings": []}

        result = runner.invoke(
            testruns_app,
            ["set-actual", "77", "--file", str(source), "--step", "3", "--replace"],
        )

        assert result.exit_code == 0
        testruns_client.append_to_actual_results.assert_called_once_with(
            77, "<p>from file</p>", step=3, mode="replace"
        )

    @pytest.mark.parametrize("args", [[], ["--html", "<p>x</p>", "--file", "f.html"]])
    def test_set_actual_needs_exactly_one_source(self, testruns_client, args):
        result = runner.invoke(testruns_app, ["set-actual", "77", *args])

        assert result.exit_code == 1
        testruns_client.append_to_actual_results.assert_not_called()

    def test_set_actual_failure(self, testruns_client):
        testruns_client.append_to_actual_results.side_effect = RuntimeError("boom")

        result = runner.invoke(testruns_app, ["set-actual", "77", "--html", "x"])

        assert result.exit_code == 1

    def test_get(self, testruns_client):
        testruns_client.get_test_run.return_value = {"id": 77, "fields": {"name": "Run"}}

        result = runner.invoke(testruns_app, ["get", "77"])

        assert result.exit_code == 0
        testruns_client.get_test_run.assert_called_once_with(77)

    def test_no_profile(self):
        with patch("jama_cli.commands.testruns.get_profile_or_env", return_value=None):
            result = runner.invoke(testruns_app, ["set-actual", "77", "--html", "x"])

        assert result.exit_code == 1
