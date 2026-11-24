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
    TestRunSchema,
    TestRunService,
    TestRunVerificationError,
    build_put_body,
    step_result,
)
from jama_cli.models import JamaProfile
from tests.fake_jama_attachments import FRESH_RUN, FakeJamaAttachments, test_run_item_type
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
        assert steps[1]["result"] == "<p>Error 500</p><p>seen</p>"
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
        assert steps[0]["result"] == "<p>new</p>"
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

    async def test_step_that_still_carries_actual_results_is_read_correctly(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        """``actualResults`` on a step is a read-side fallback; it is never written."""
        legacy = {"action": "<p>a</p>", "status": "PASSED", "actualResults": "<p>old</p>"}
        assert step_result(legacy) == "<p>old</p>"
        assert step_result({**legacy, "result": "<p>new</p>"}) == "<p>new</p>"
        assert step_result({"action": "<p>a</p>"}) is None

        step = steps_of(fake)[0]
        step["actualResults"] = step.pop("result")
        runs = make_runs(fake, tmp_path)

        update = await runs.append_to_actual_results(RUN, "<p>x</p>", step=1)

        assert update.field_name == "result"
        assert steps_of(fake)[0]["result"] == "<p>Loaded in <b>1s</b></p><p>x</p>"
        assert all(
            "actualResults" not in sent for sent in fake.run_puts[0]["fields"]["testRunSteps"]
        )

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
# What a real instance showed: fresh runs, the ``result`` step key, item types
# ---------------------------------------------------------------------------


class TestObservedBehaviour:
    async def test_get_omits_empty_fields(self, fake: FakeJamaAttachments, tmp_path: Path) -> None:
        run = await make_runs(fake, tmp_path).get_test_run(FRESH_RUN)

        assert "actualResults" not in run["fields"]
        for step in run["fields"]["testRunSteps"]:
            assert set(step) <= {"action", "expectedResult", "notes", "status"}
            assert "result" not in step and "actualResults" not in step

    async def test_first_write_to_a_fresh_step_lands_in_result(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        """No step has a result key yet. The old code wrote ``actualResults``, which Jama drops."""
        runs = make_runs(fake, tmp_path)

        update = await runs.append_to_actual_results(FRESH_RUN, "<p>seen</p>", step=2)

        steps = fake.test_runs[FRESH_RUN]["fields"]["testRunSteps"]
        assert steps[1]["result"] == "<p>seen</p>"
        assert update.updated is True and update.field_name == "result"
        assert update.html == "<p>seen</p>"
        assert "result" not in steps[0]
        assert [s["status"] for s in steps] == ["NOT_RUN", "NOT_RUN"]
        assert "actualResults" not in fake.test_runs[FRESH_RUN]["fields"]

    async def test_first_run_level_write_to_a_fresh_run(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        """The item type lists the field; GET omitting it means empty, not unknown."""
        runs = make_runs(fake, tmp_path)

        update = await runs.append_to_actual_results(FRESH_RUN, "<p>first</p>")

        assert fake.test_runs[FRESH_RUN]["fields"]["actualResults"] == "<p>first</p>"
        assert update.field_name == "actualResults"

    async def test_writing_never_sends_a_step_actual_results_key(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        await runs.append_to_actual_results(FRESH_RUN, "<p>a</p>", step=1)
        await runs.append_to_actual_results(RUN, "<p>b</p>", step=3, mode="replace")
        await runs.attach_screenshots_to_test_run(FRESH_RUN, [png], step=2)
        await runs.update_test_run(RUN, step=1, step_fields={"actualResults": "<p>c</p>"})
        await runs.update_test_run(RUN, {"fields": {"testRunSteps": [{"status": "FAILED"}]}})

        assert len(fake.run_puts) == 5
        for put in fake.run_puts:
            for step in put["fields"]["testRunSteps"]:
                assert not {"actualResults", "actualResult", "actual"} & set(step)

    async def test_step_actual_results_in_an_update_is_written_as_result(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        result = await runs.update_test_run(
            FRESH_RUN, step=1, step_fields={"actualResults": "<p>c</p>"}
        )

        assert fake.test_runs[FRESH_RUN]["fields"]["testRunSteps"][0]["result"] == "<p>c</p>"
        assert any("written as 'result'" in warning for warning in result["warnings"])
        with pytest.raises(TestRunError, match="both 'result' and 'actualResults'"):
            await runs.update_test_run(
                FRESH_RUN, step=1, step_fields={"actualResults": "<p>x</p>", "result": "<p>y</p>"}
            )

    async def test_status_update_through_step_fields(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)
        before = copy.deepcopy(fake.test_runs[FRESH_RUN]["fields"]["testRunSteps"])

        result = await runs.update_test_run(FRESH_RUN, step=1, step_fields={"status": "PASSED"})

        fields = fake.test_runs[FRESH_RUN]["fields"]
        assert fields["testRunSteps"][0] == {**before[0], "status": "PASSED"}
        assert fields["testRunSteps"][1] == before[1]
        assert result["updated"] is True and result["updated_steps"] == [1]
        # Jama recomputes the run status; that is not a collateral change.
        assert fields["testRunStatus"] == "INPROGRESS"
        assert result["warnings"] == []

    async def test_step_key_that_jama_drops_is_reported(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        with pytest.raises(TestRunVerificationError, match="did not store step 1: comment"):
            await runs.update_test_run(FRESH_RUN, step=1, step_fields={"comment": "x"})

    async def test_read_only_flag_of_the_steps_field_does_not_block_a_put(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)
        schema = await runs.schema()

        assert schema.steps == "testRunSteps" and schema.steps_read_only is True
        await runs.append_to_actual_results(FRESH_RUN, "<p>x</p>", step=1)
        assert len(fake.run_puts) == 1


class TestItemTypeDrivenFields:
    async def test_test_run_type_is_found_by_type_key_not_by_id(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        fake.item_types[-1]["id"] = 4711
        fake.item_types.reverse()
        runs = make_runs(fake, tmp_path)

        schema = await runs.schema()

        assert schema.item_type_id == 4711
        assert schema.actual_results == "actualResults"
        assert schema.actual_results_read_only is False
        assert "GET rest/v1/itemtypes/4711" in fake.routes()

    async def test_run_level_field_name_comes_from_the_item_type(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        """An instance whose field carries a ``$<typeId>`` suffix."""
        for definition in fake.item_types[-1]["fields"]:
            if definition["name"] == "actualResults":
                definition["name"] = "actualResults$89"
        fields = fields_of(fake)
        fields["actualResults$89"] = fields.pop("actualResults")
        fake.result_fields = ("actualResults$89", "assignedTo")
        runs = make_runs(fake, tmp_path)

        update = await runs.append_to_actual_results(RUN, "<p>more</p>")

        assert update.field_name == "actualResults$89"
        sent = fake.run_puts[0]["fields"]
        assert sent["actualResults$89"].endswith("<p>more</p>")
        assert "actualResults" not in sent

    async def test_read_only_run_level_field_fails_before_any_write(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        for definition in fake.item_types[-1]["fields"]:
            if definition["name"] == "actualResults":
                definition["readOnly"] = True
        runs = make_runs(fake, tmp_path)

        with pytest.raises(TestRunError, match="read-only on this Jama instance"):
            await runs.append_to_actual_results(RUN, "<p>x</p>")
        assert fake.run_puts == []
        assert fake.count("GET", f"rest/v1/testruns/{RUN}") == 0

    async def test_instance_without_a_test_run_type_or_field_is_a_clear_error(
        self, tmp_path: Path
    ) -> None:
        fake = FakeJamaAttachments()
        fake.item_types[-1]["typeKey"] = "OTHER"
        with pytest.raises(TestRunError, match="typeKey 'TSTRN'"):
            await make_runs(fake, tmp_path).append_to_actual_results(RUN, "<p>x</p>")

        fake = FakeJamaAttachments()
        fake.item_types[-1]["fields"] = [
            f for f in fake.item_types[-1]["fields"] if f["name"] != "actualResults"
        ]
        with pytest.raises(TestRunError, match="has no 'actualResults' field"):
            await make_runs(fake, tmp_path).append_to_actual_results(RUN, "<p>x</p>")
        assert fake.run_puts == []

    async def test_definition_is_fetched_once_per_connection(
        self, fake: FakeJamaAttachments, tmp_path: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        await runs.append_to_actual_results(RUN, "<p>a</p>")
        await runs.append_to_actual_results(RUN, "<p>b</p>", step=1)
        await runs.update_test_run(RUN, step=3, step_fields={"status": "PASSED"})

        assert fake.count("GET", "rest/v1/itemtypes") == 1
        assert fake.count("GET", "rest/v1/itemtypes/89") == 1

    def test_schema_from_a_definition(self) -> None:
        schema = TestRunSchema.from_item_type(test_run_item_type())

        assert schema.put_fields == ("testRunSteps", "actualResults", "assignedTo")
        assert schema.resolve("defects_found") == "defects_found$89"
        assert schema.resolve("unknown") == "unknown"


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
        assert steps[1]["result"] == (
            "<p>Error 500</p>" f'<p>After login</p><p><img src="{url}" alt="After login" /></p>'
        )
        assert steps[0] == original["testRunSteps"][0]
        assert steps[2] == original["testRunSteps"][2]
        assert steps[1]["status"] == "FAILED"
        assert fields_of(fake)["actualResults"] == original["actualResults"]
        assert result.embedded == [url]
        assert result.attachments[0].attachment_id == 500
        assert result.attachments[0].file_id == 9000
        # Created in the run's project. A test run is not an item: no link is
        # attempted, and that is reported as info, not as a warning.
        assert fake.attachments[500]["project"] == 3
        assert fake.links == {}
        assert fake.count("POST", f"rest/v1/items/{RUN}/attachments") == 0
        assert fake.count("GET", f"rest/v1/items/{RUN}") == 0
        assert result.warnings == []
        assert any("no Attachments tab via REST" in note for note in result.info)

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
        assert steps_of(fake)[0]["result"].count("<img ") == 3

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
        assert steps_of(fake)[1]["result"].count("<img ") == 1
        assert len(fake.run_puts) == 1
        assert second.updated is False
        assert second.skipped == first.embedded
        assert fake.links == {}

    async def test_same_file_twice_in_one_call_is_embedded_once(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)

        await runs.attach_screenshots_to_test_run(RUN, [png, png], step=1)

        assert len(fake.attachments) == 1
        assert steps_of(fake)[0]["result"].count("<img ") == 1

    async def test_caption_and_alt_are_escaped(
        self, fake: FakeJamaAttachments, tmp_path: Path, png: Path
    ) -> None:
        runs = make_runs(fake, tmp_path)
        caption = '<script>alert("x")</script> & co'

        await runs.attach_screenshots_to_test_run(RUN, [png], step=3, caption=caption)

        stored = steps_of(fake)[2]["result"]
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
        assert result.attachments[0].embed_url in steps_of(fake)[0]["result"]


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
        assert steps[0]["result"].startswith("<p>Loaded in <b>1s</b></p><p>x</p><p>c</p>")
        assert steps[1] == original["testRunSteps"][1]
        assert steps[2]["status"] == "BLOCKED"
