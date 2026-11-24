"""Opt-in test against a REAL Jama instance: test run results and screenshots.

Skipped unless the variables below are set. The test creates its own scratch
fixture: a NEW test cycle under an existing test plan, which makes Jama generate
fresh test runs from one of the plan's test groups. It then writes to one of
those runs only. Nothing that existed before is modified.

Use a sandbox instance or a scratch project. Never point this at production.

Required:

- ``JAMA_LIVE_URL``             base URL, e.g. https://jama.example.com/contour
- ``JAMA_LIVE_TEST_PLAN_ID``    id of a test plan in a scratch project
- ``JAMA_LIVE_TEST_GROUP_ID``   id of a test group of that plan with at least one
  test case that has steps
- credentials, one of:
  ``JAMA_LIVE_CLIENT_ID`` + ``JAMA_LIVE_CLIENT_SECRET`` (OAuth),
  ``JAMA_LIVE_API_KEY``, or ``JAMA_LIVE_USERNAME`` + ``JAMA_LIVE_PASSWORD``;
  or ``JAMA_LIVE_AUTH=session`` to use the stored web session of ``jama login``
  (with ``JAMA_LIVE_USERNAME`` if the session was stored for an account)

Optional:

- ``JAMA_LIVE_PROJECT_ID``      project for the attachments (default: the run's)
- ``JAMA_LIVE_CLEANUP=1``       delete the created test cycle afterwards. Off by
  default so the result can be looked at in the web UI. The delete call
  (``DELETE testcycles/{id}``) has not been verified against a real instance; if
  Jama refuses it, the test still passes and prints the cycle id to remove by hand.

    pytest tests/test_attachments_live.py -m integration -s
"""

from __future__ import annotations

import base64
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from jama_cli.core.api import JamaApi
from jama_cli.core.attachments import AttachmentService, UploadCache
from jama_cli.core.exceptions import JamaException
from jama_cli.core.http_client import JamaHttpClient
from jama_cli.core.session import SessionManager, SessionSettings
from jama_cli.core.testruns import STEP_RESULT_KEY, TestRunService, run_fields, run_steps

# A valid 1x1 PNG.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

_REQUIRED = ("JAMA_LIVE_URL", "JAMA_LIVE_TEST_PLAN_ID", "JAMA_LIVE_TEST_GROUP_ID")


def _has_credentials() -> bool:
    env = os.environ
    return bool(
        env.get("JAMA_LIVE_AUTH") == "session"
        or (env.get("JAMA_LIVE_CLIENT_ID") and env.get("JAMA_LIVE_CLIENT_SECRET"))
        or env.get("JAMA_LIVE_API_KEY")
        or (env.get("JAMA_LIVE_USERNAME") and env.get("JAMA_LIVE_PASSWORD"))
    )


def _http_from_env() -> JamaHttpClient:
    env = os.environ
    url = env["JAMA_LIVE_URL"]
    if env.get("JAMA_LIVE_AUTH") == "session":
        settings = SessionSettings(
            base_url=url, username=env.get("JAMA_LIVE_USERNAME"), login_interactive="never"
        )
        return JamaHttpClient(base_url=url, session=SessionManager(settings))
    if env.get("JAMA_LIVE_CLIENT_ID") and env.get("JAMA_LIVE_CLIENT_SECRET"):
        credentials = (env["JAMA_LIVE_CLIENT_ID"], env["JAMA_LIVE_CLIENT_SECRET"])
        return JamaHttpClient(base_url=url, credentials=credentials, oauth=True)
    if env.get("JAMA_LIVE_API_KEY"):
        return JamaHttpClient(base_url=url, credentials=(env["JAMA_LIVE_API_KEY"], ""))
    credentials = (env["JAMA_LIVE_USERNAME"], env["JAMA_LIVE_PASSWORD"])
    return JamaHttpClient(base_url=url, credentials=credentials)


_CONFIGURED = all(os.environ.get(name) for name in _REQUIRED) and _has_credentials()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _CONFIGURED,
        reason=f"set {', '.join(_REQUIRED)} and credentials to run against a Jama sandbox",
    ),
]


async def _create_scratch_run(api: JamaApi) -> tuple[int, int]:
    """Create a test cycle from the plan's test group; return (cycle id, id of a run with steps)."""
    plan = int(os.environ["JAMA_LIVE_TEST_PLAN_ID"])
    group = int(os.environ["JAMA_LIVE_TEST_GROUP_ID"])
    today = time.strftime("%Y-%m-%d")
    cycle_id = await api.post_testplans_testcycles(
        plan, f"jama-cli live test {int(time.time())}", today, today, [group]
    )
    runs = await api.get_testruns(cycle_id)
    assert runs, f"test cycle {cycle_id} has no test runs; does the test group contain test cases?"
    for run in runs:
        full = await api.get_test_run(int(run["id"]))
        if len(run_steps(run_fields(full))) >= 1:
            return cycle_id, int(run["id"])
    pytest.fail(f"no test run of cycle {cycle_id} has steps; use a test case with steps")


def _others_unchanged(before: list[dict[str, Any]], after: list[dict[str, Any]], step: int) -> None:
    assert len(before) == len(after)
    for index, (old, new) in enumerate(zip(before, after, strict=True), start=1):
        if index != step:
            assert old == new, f"step {index} changed although only step {step} was written"


async def test_results_and_screenshots_on_a_freshly_generated_test_run() -> None:
    project = os.environ.get("JAMA_LIVE_PROJECT_ID")
    project_id = int(project) if project else None

    async with _http_from_env() as http:
        api = JamaApi(http)
        # A fresh upload map: the first call really uploads, the re-run reuses.
        cache_path = Path(tempfile.mkdtemp(prefix="jama-cli-live-")) / "uploads.json"
        runs = TestRunService(api, AttachmentService(api, cache=UploadCache(cache_path)))
        cycle_id, run_id = await _create_scratch_run(api)
        print(f"\ncreated test cycle {cycle_id}; working on test run {run_id}")

        try:
            # --- a fresh run: empty fields are omitted, steps have no result key ---
            fresh = run_fields(await api.get_test_run(run_id))
            steps_fresh = run_steps(fresh)
            schema = await runs.schema()
            assert schema.actual_results not in fresh
            assert all(STEP_RESULT_KEY not in step for step in steps_fresh)
            step = 1

            # --- set-actual: run level, then step ---
            run_level = await runs.append_to_actual_results(run_id, "<p>jama-cli live: run</p>")
            assert run_level.updated and run_level.field_name == schema.actual_results
            in_step = await runs.append_to_actual_results(
                run_id, "<p>jama-cli live: step</p>", step=step
            )
            assert in_step.updated and in_step.field_name == STEP_RESULT_KEY

            after_text = run_fields(await api.get_test_run(run_id))
            assert "jama-cli live: run" in after_text[schema.actual_results]
            assert "jama-cli live: step" in run_steps(after_text)[step - 1][STEP_RESULT_KEY]
            _others_unchanged(steps_fresh, run_steps(after_text), step)

            # --- add-screenshot: step, then run level ---
            name = f"jama-cli-live-{int(time.time())}.png"
            shot_step = await runs.attach_screenshots_to_test_run(
                run_id, [(name, TINY_PNG)], step=step, caption="live step", project_id=project_id
            )
            shot_run = await runs.attach_screenshots_to_test_run(
                run_id, [(name, TINY_PNG)], caption="live run", project_id=project_id
            )
            uploaded = shot_step.attachments[0]
            # The embed URL uses the stored file's id, and Jama serves the file for it.
            assert uploaded.file_id != uploaded.attachment_id
            assert f"/attachment/{uploaded.file_id}/" in uploaded.embed_url
            assert await api.get_file_by_url(uploaded.embed_url) == TINY_PNG
            assert await api.get_attachment_file(uploaded.attachment_id) == TINY_PNG
            # Same bytes, same project: the second call reuses the attachment.
            assert shot_run.attachments[0].attachment_id == uploaded.attachment_id
            # A test run is not an item: nothing is linked, and that is not a warning.
            assert uploaded.linked is False and shot_step.warnings == []

            after_shots = run_fields(await api.get_test_run(run_id))
            step_html = run_steps(after_shots)[step - 1][STEP_RESULT_KEY]
            assert uploaded.embed_url in step_html and "jama-cli live: step" in step_html
            assert uploaded.embed_url in after_shots[schema.actual_results]

            # --- idempotency: the same screenshot again changes nothing ---
            again = await runs.attach_screenshots_to_test_run(
                run_id, [(name, TINY_PNG)], step=step, caption="live step", project_id=project_id
            )
            assert again.updated is False and again.skipped == [uploaded.embed_url]
            unchanged = run_fields(await api.get_test_run(run_id))
            assert run_steps(unchanged)[step - 1][STEP_RESULT_KEY].count("<img") == 1

            # --- status update through step_fields ---
            status = await runs.update_test_run(run_id, step=step, step_fields={"status": "PASSED"})
            assert status["updated"] and status["updated_steps"] == [step]
            final = run_fields(await api.get_test_run(run_id))
            assert run_steps(final)[step - 1]["status"] == "PASSED"
            assert uploaded.embed_url in run_steps(final)[step - 1][STEP_RESULT_KEY]
            _others_unchanged(steps_fresh, run_steps(final), step)
        finally:
            shutil.rmtree(cache_path.parent, ignore_errors=True)
            if os.environ.get("JAMA_LIVE_CLEANUP") == "1":
                try:
                    await http.delete(f"testcycles/{cycle_id}")
                    print(f"deleted test cycle {cycle_id}")
                except JamaException as e:
                    print(
                        f"could not delete test cycle {cycle_id} ({type(e).__name__}); "
                        "remove it in the web UI"
                    )
            else:
                print(f"left test cycle {cycle_id} in place (set JAMA_LIVE_CLEANUP=1 to delete)")
