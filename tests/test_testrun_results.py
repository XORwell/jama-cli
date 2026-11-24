"""Tests for test run "Actual results" edits and screenshots against a fake Jama."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from jama_cli.core.api import JamaApi
from jama_cli.core.attachments import AttachmentService, UploadCache
from jama_cli.core.client import JamaClient
from jama_cli.core.exceptions import APIClientException
from jama_cli.core.sync_wrapper import SyncJamaApi
from jama_cli.core.testruns import (
    PUT_FIELDS,
    TestRunError,
    TestRunService,
    TestRunVerificationError,
    build_put_body,
)
from jama_cli.models import JamaProfile
from tests.fake_jama_attachments import FakeJamaAttachments
from tests.test_attachments import PNG, make_http

RUN = 77


def make_runs(fake: FakeJamaAttachments, tmp_path: Path, cache: bool = True) -> TestRunService:
    api = JamaApi(make_http(fake, tmp_path))
    upload_cache = UploadCache(tmp_path / "uploads.json") if cache else None
    return TestRunService(api, AttachmentService(api, cache=upload_cache))


def fields_of(fake: FakeJamaAttachments) -> dict[str, Any]:
    return fake.test_runs[RUN]["fields"]


def steps_of(fake: FakeJamaAttachments) -> list[dict[str, Any]]:
    return fields_of(fake)["testRunSteps"]


@pytest.fixture
def fake() -> FakeJamaAttachments:
    return FakeJamaAttachments()


@pytest.fixture
def original(fake: FakeJamaAttachments) -> dict[str, Any]:
    return copy.deepcopy(fields_of(fake))


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "shot.png"
    path.write_bytes(PNG)
    return path


@pytest.fixture
def other_png(tmp_path: Path) -> Path:
    path = tmp_path / "second.png"
    path.write_bytes(PNG + b"-different")
    return path


# ---------------------------------------------------------------------------
# append_to_actual_results
# ---------------------------------------------------------------------------


class TestAppendToActualResults:
    async def test_append_to_run_level_keeps_everything_else(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        update = await runs.append_to_actual_results(RUN, "<p>more</p>")

        fields = fields_of(fake)
        assert fields["actualResults"] == original["actualResults"] + "<p>more</p>"
        assert fields["testRunSteps"] == original["testRunSteps"]
        assert fields["assignedTo"] == original["assignedTo"]
        assert update.updated is True and update.step is None
        assert len(fake.run_puts) == 1

    async def test_append_to_step_keeps_other_steps_statuses_and_html(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        await runs.append_to_actual_results(RUN, "<p>seen</p>", step=2)

        fields = fields_of(fake)
        steps = fields["testRunSteps"]
        assert steps[1]["actualResults"] == "<p>Error 500</p><p>seen</p>"
        # Everything else is byte-identical.
        assert steps[0] == original["testRunSteps"][0]
        assert steps[2] == original["testRunSteps"][2]
        assert [s["status"] for s in steps] == ["PASSED", "FAILED", "NOT_RUN"]
        for key in ("action", "expectedResult", "notes", "status"):
            assert steps[1][key] == original["testRunSteps"][1][key]
        assert fields["actualResults"] == original["actualResults"]

    async def test_put_carries_the_complete_step_list(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        await runs.append_to_actual_results(RUN, "<p>x</p>", step=3)

        sent = fake.run_puts[0]["fields"]
        assert set(sent) == set(PUT_FIELDS)
        assert len(sent["testRunSteps"]) == 3
        assert sent["testRunSteps"][:2] == original["testRunSteps"][:2]
        assert sent["actualResults"] == original["actualResults"]

    async def test_append_to_empty_field(self, fake: FakeJamaAttachments, tmp_path: Path) -> None:
        fields_of(fake)["actualResults"] = None
        runs = make_runs(fake, tmp_path)

        await runs.append_to_actual_results(RUN, "<p>first</p>")

        assert fields_of(fake)["actualResults"] == "<p>first</p>"

    async def test_replace_replaces_only_the_target(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        await runs.append_to_actual_results(RUN, "<p>new</p>", step=1, mode="replace")

        steps = steps_of(fake)
        assert steps[0]["actualResults"] == "<p>new</p>"
        assert steps[0]["status"] == "PASSED"
        assert steps[1:] == original["testRunSteps"][1:]
        assert fields_of(fake)["actualResults"] == original["actualResults"]

    async def test_replace_run_level(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        await runs.append_to_actual_results(RUN, "<p>only this</p>", mode="replace")

        assert fields_of(fake)["actualResults"] == "<p>only this</p>"
        assert steps_of(fake) == original["testRunSteps"]

    async def test_no_change_means_no_put(self, fake: FakeJamaAttachments, tmp_path: Path) -> None:
        runs = make_runs(fake, tmp_path)

        update = await runs.append_to_actual_results(RUN, "")

        assert update.updated is False
        assert fake.run_puts == []

    @pytest.mark.parametrize("step", [0, 4])
    async def test_unknown_step_is_rejected_before_any_write(
        self, fake: FakeJamaAttachments, tmp_path: Path, step: int
    ) -> None:
        runs = make_runs(fake, tmp_path)

        with pytest.raises(TestRunError, match="has 3 step"):
            await runs.append_to_actual_results(RUN, "<p>x</p>", step=step)
        assert fake.run_puts == []

    async def test_invalid_mode(self, fake: FakeJamaAttachments, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            await make_runs(fake, tmp_path).append_to_actual_results(
                RUN, "x", mode="prepend"  # type: ignore[arg-type]
            )

    async def test_locked_run_surfaces_jamas_error_without_retry(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path
    ) -> None:
        fake.refuse_run_update = (400, "Test run is locked because the cycle is closed")
        runs = make_runs(fake, tmp_path)

        with pytest.raises(APIClientException, match="cycle is closed"):
            await runs.append_to_actual_results(RUN, "<p>x</p>", step=1)

        assert len(fake.run_puts) == 1
        assert fields_of(fake) == original

    async def test_step_field_name_follows_the_run(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        """An instance that calls the per-step field ``result`` is handled."""
        for step in steps_of(fake):
            step["result"] = step.pop("actualResults")
        runs = make_runs(fake, tmp_path)

        update = await runs.append_to_actual_results(RUN, "<p>x</p>", step=1)

        assert update.field_name == "result"
        assert steps_of(fake)[0]["result"] == "<p>Loaded in <b>1s</b></p><p>x</p>"
        assert "actualResults" not in steps_of(fake)[0]

    async def test_write_that_jama_does_not_store_is_reported(
        self, fake: FakeJamaAttachments, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runs = make_runs(fake, tmp_path)
        frozen = copy.deepcopy(fake.test_runs[RUN])

        async def ignore_put(test_run_id: int, data: Any = None) -> int:  # noqa: ARG001
            return 200

        monkeypatch.setattr(runs._api, "put_test_run", ignore_put)

        with pytest.raises(TestRunVerificationError, match="did not store"):
            await runs.append_to_actual_results(RUN, "<p>x</p>", step=1)
        assert fake.test_runs[RUN] == frozen

    async def test_collateral_change_is_reported(
        self, fake: FakeJamaAttachments, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If a PUT changes another step, that must not go unnoticed."""
        runs = make_runs(fake, tmp_path)
        real_put = runs._api.put_test_run

        async def put_and_reset_status(test_run_id: int, data: Any = None) -> int:
            status = await real_put(test_run_id, data)
            steps_of(fake)[2]["status"] = "PASSED"
            return status

        monkeypatch.setattr(runs._api, "put_test_run", put_and_reset_status)

        with pytest.raises(TestRunVerificationError, match="step 3: status"):
            await runs.append_to_actual_results(RUN, "<p>x</p>", step=1)

    async def test_html_cleanup_by_jama_is_a_warning(
        self, fake: FakeJamaAttachments, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runs = make_runs(fake, tmp_path)
        real_put = runs._api.put_test_run

        async def put_and_normalise(test_run_id: int, data: Any = None) -> int:
            status = await real_put(test_run_id, data)
            fields = fields_of(fake)
            fields["actualResults"] = fields["actualResults"].replace("<br/>", "<br>")
            return status

        monkeypatch.setattr(runs._api, "put_test_run", put_and_normalise)

        update = await runs.append_to_actual_results(RUN, "<p>a<br/>b</p>")

        assert update.updated is True
        assert update.html.endswith("<p>a<br>b</p>")
        assert any("differently" in warning for warning in update.warnings)

    def test_put_body_is_built_in_one_place(self) -> None:
        fields = {"name": "x", "testRunSteps": [], "actualResults": "", "custom": 1}
        assert build_put_body(fields) == {"fields": {"testRunSteps": [], "actualResults": ""}}
        assert build_put_body(fields, extra=["custom"])["fields"]["custom"] == 1


# ---------------------------------------------------------------------------
# attach_screenshots_to_test_run
# ---------------------------------------------------------------------------


class TestAttachScreenshots:
    async def test_screenshot_in_step(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path, png: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        result = await runs.attach_screenshots_to_test_run(
            RUN, [png], step=2, caption="After login"
        )

        url = f"{fake.base}/attachment/9000/shot.png"
        steps = steps_of(fake)
        assert steps[1]["actualResults"] == (
            "<p>Error 500</p>" f'<p>After login</p><p><img src="{url}" alt="After login" /></p>'
        )
        assert steps[0] == original["testRunSteps"][0]
        assert steps[2] == original["testRunSteps"][2]
        assert steps[1]["status"] == "FAILED"
        assert fields_of(fake)["actualResults"] == original["actualResults"]
        assert result.embedded == [url]
        assert result.attachments[0].attachment_id == 500
        assert result.attachments[0].file_id == 9000
        # Created in the run's project and linked to the run.
        assert fake.attachments[500]["project"] == 3
        assert fake.links == {RUN: [500]}
        assert result.warnings == []

    async def test_run_level_without_caption_uses_file_name_as_alt(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path, png: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        await runs.attach_screenshots_to_test_run(RUN, [png])

        url = f"{fake.base}/attachment/9000/shot.png"
        assert fields_of(fake)["actualResults"] == (
            original["actualResults"] + f'<p><img src="{url}" alt="shot.png" /></p>'
        )
        assert steps_of(fake) == original["testRunSteps"]

    async def test_several_images_one_put(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path, other_png: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        result = await runs.attach_screenshots_to_test_run(
            RUN, [png, ("from-bytes.png", b"raw-image-bytes")], step=1, caption="c"
        )
        await runs.attach_screenshots_to_test_run(RUN, [other_png], step=1)

        assert len(result.embedded) == 2
        assert len(fake.run_puts) == 2  # one PUT per call, not per image
        assert steps_of(fake)[0]["actualResults"].count("<img ") == 3

    async def test_rerun_creates_no_duplicate(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        first = await make_runs(fake, tmp_path).attach_screenshots_to_test_run(
            RUN, [png], step=2, caption="After login"
        )
        after_first = copy.deepcopy(fields_of(fake))

        # Same call again, as a new process with the same upload map.
        second = await make_runs(fake, tmp_path).attach_screenshots_to_test_run(
            RUN, [png], step=2, caption="After login"
        )

        assert len(fake.attachments) == 1
        assert fields_of(fake) == after_first
        assert steps_of(fake)[1]["actualResults"].count("<img ") == 1
        assert len(fake.run_puts) == 1
        assert second.updated is False
        assert second.skipped == first.embedded
        assert fake.links == {RUN: [500]}

    async def test_same_file_twice_in_one_call_is_embedded_once(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        await runs.attach_screenshots_to_test_run(RUN, [png, png], step=1)

        assert len(fake.attachments) == 1
        assert steps_of(fake)[0]["actualResults"].count("<img ") == 1

    async def test_link_refused_still_embeds_and_warns(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        fake.refuse_link_for = {RUN}
        runs = make_runs(fake, tmp_path)

        result = await runs.attach_screenshots_to_test_run(RUN, [png], step=1)

        assert f"{fake.base}/attachment/9000/shot.png" in steps_of(fake)[0]["actualResults"]
        assert result.updated is True
        assert result.attachments[0].linked is False
        assert fake.links == {}
        assert len(result.warnings) == 1
        assert "Attachments tab" in result.warnings[0]
        assert "not allowed for this item type" in result.warnings[0]

    async def test_caption_and_alt_are_escaped(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)
        caption = '<script>alert("x")</script> & co'

        await runs.attach_screenshots_to_test_run(RUN, [png], step=3, caption=caption)

        stored = steps_of(fake)[2]["actualResults"]
        assert "<script>" not in stored
        assert "<p>&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; co</p>" in stored
        assert 'alt="&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; co"' in stored

    async def test_project_comes_from_the_cycle_if_the_run_has_none(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        del fake.test_runs[RUN]["project"]
        fake.test_cycles[40]["project"] = 8
        runs = make_runs(fake, tmp_path)

        await runs.attach_screenshots_to_test_run(RUN, [png])

        assert fake.attachments[500]["project"] == 8

    async def test_unknown_step_uploads_nothing(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        with pytest.raises(TestRunError, match="step 9 does not exist"):
            await runs.attach_screenshots_to_test_run(RUN, [png], step=9)
        assert fake.attachments == {}

    async def test_missing_file_uploads_nothing(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        with pytest.raises(Exception, match="File not found"):
            await runs.attach_screenshots_to_test_run(RUN, [png, tmp_path / "missing.png"])
        assert fake.attachments == {}

    async def test_session_fallback_for_a_test_run(self, tmp_path: Path, png: Path) -> None:
        fake = FakeJamaAttachments(auth="session")
        fake.refuse_rest_create = (403, "Forbidden")
        runs = make_runs(fake, tmp_path)

        result = await runs.attach_screenshots_to_test_run(RUN, [png], step=1)

        assert fake.internal_uploads[0]["parts"]["itemId"]["content"] == b"77"
        assert result.attachments[0].via_internal_endpoint is True
        assert result.attachments[0].embed_url in steps_of(fake)[0]["actualResults"]


# ---------------------------------------------------------------------------
# update_test_run (partial update)
# ---------------------------------------------------------------------------


class TestUpdateTestRun:
    async def test_partial_step_update_keeps_other_steps(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        result = await runs.update_test_run(
            RUN, {"fields": {"testRunSteps": [{"status": "PASSED"}]}}
        )

        steps = steps_of(fake)
        assert len(steps) == 3
        assert steps[0] == original["testRunSteps"][0]  # already PASSED
        assert steps[1:] == original["testRunSteps"][1:]
        assert result["updated"] is False

    async def test_positional_overlay(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        result = await runs.update_test_run(
            RUN, {"fields": {"testRunSteps": [{}, None, {"status": "PASSED"}]}}
        )

        steps = steps_of(fake)
        assert steps[2] == {**original["testRunSteps"][2], "status": "PASSED"}
        assert steps[:2] == original["testRunSteps"][:2]
        assert fields_of(fake)["actualResults"] == original["actualResults"]
        assert fields_of(fake)["assignedTo"] == original["assignedTo"]
        assert result["updated_steps"] == [3]

    async def test_single_step_and_run_field(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        await runs.update_test_run(
            RUN, {"actualResults": "<p>done</p>"}, step=2, step_fields={"status": "PASSED"}
        )

        assert fields_of(fake)["actualResults"] == "<p>done</p>"
        assert steps_of(fake)[1] == {**original["testRunSteps"][1], "status": "PASSED"}
        assert steps_of(fake)[0] == original["testRunSteps"][0]
        assert len(fake.run_puts[0]["fields"]["testRunSteps"]) == 3

    async def test_too_many_steps_and_empty_update_are_rejected(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        with pytest.raises(TestRunError, match="step 4 does not exist"):
            await runs.update_test_run(RUN, {"fields": {"testRunSteps": [{}, {}, {}, {"a": 1}]}})
        with pytest.raises(TestRunError, match="Nothing to update"):
            await runs.update_test_run(RUN, {})
        assert fake.run_puts == []


# ---------------------------------------------------------------------------
# JamaClient (sync facade used by the CLI)
# ---------------------------------------------------------------------------


class TestJamaClientTestRuns:
    def test_sync_facade(
        self, fake: FakeJamaAttachments, original: dict[str, Any], tmp_path: Path, png: Path
    ) -> None:
        http = make_http(fake, tmp_path)
        profile = JamaProfile(
            url=fake.base, auth_type="basic", username="user", password="pw"  # noqa: S106
        )
        client = JamaClient(profile, use_disk_cache=False)
        client._api = SyncJamaApi(JamaApi(http), http)
        try:
            assert client.get_test_run(RUN)["fields"]["name"] == "Login works"

            appended = client.append_to_actual_results(RUN, "<p>x</p>", step=1)
            shots = client.attach_screenshots_to_test_run(RUN, [png], step=1, caption="c")
            updated = client.update_test_run(RUN, step=3, step_fields={"status": "BLOCKED"})
        finally:
            client._api.close()

        assert appended["updated"] is True and appended["step"] == 1
        assert shots["attachments"][0]["file_id"] == 9000
        assert updated["updated_steps"] == [3]
        steps = steps_of(fake)
        assert steps[0]["actualResults"].startswith("<p>Loaded in <b>1s</b></p><p>x</p><p>c</p>")
        assert steps[1] == original["testRunSteps"][1]
        assert steps[2]["status"] == "BLOCKED"
