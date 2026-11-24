"""Opt-in test against a REAL Jama instance: a screenshot in a test run step.

Skipped unless all of these are set (use a scratch project / test run; the
test MODIFIES the test run by appending an image to a step's actual results):

- ``JAMA_LIVE_URL``            base URL, e.g. https://jama.example.com/contour
- ``JAMA_LIVE_TEST_RUN_ID``    id of a scratch test run that can be edited
- credentials, one of:
  ``JAMA_LIVE_CLIENT_ID`` + ``JAMA_LIVE_CLIENT_SECRET`` (OAuth),
  ``JAMA_LIVE_API_KEY``, or ``JAMA_LIVE_USERNAME`` + ``JAMA_LIVE_PASSWORD``;
  or ``JAMA_LIVE_AUTH=session`` to use the stored web session of ``jama login``
  (with ``JAMA_LIVE_USERNAME`` if the session was stored for an account)

Optional: ``JAMA_LIVE_STEP`` (default 1), ``JAMA_LIVE_PROJECT_ID``.

    pytest tests/test_attachments_live.py -m integration
"""

from __future__ import annotations

import base64
import os
import time

import pytest

from jama_cli.core.api import JamaApi
from jama_cli.core.attachments import AttachmentService
from jama_cli.core.http_client import JamaHttpClient
from jama_cli.core.session import SessionManager, SessionSettings
from jama_cli.core.testruns import TestRunService, run_fields, run_steps, step_actual_results_field

# A valid 1x1 PNG.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _http_from_env() -> JamaHttpClient | None:
    env = os.environ
    url = env.get("JAMA_LIVE_URL")
    if not url or not env.get("JAMA_LIVE_TEST_RUN_ID"):
        return None
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
    if env.get("JAMA_LIVE_USERNAME") and env.get("JAMA_LIVE_PASSWORD"):
        credentials = (env["JAMA_LIVE_USERNAME"], env["JAMA_LIVE_PASSWORD"])
        return JamaHttpClient(base_url=url, credentials=credentials)
    return None


_CONFIGURED = bool(
    os.environ.get("JAMA_LIVE_URL")
    and os.environ.get("JAMA_LIVE_TEST_RUN_ID")
    and (
        os.environ.get("JAMA_LIVE_AUTH") == "session"
        or (os.environ.get("JAMA_LIVE_CLIENT_ID") and os.environ.get("JAMA_LIVE_CLIENT_SECRET"))
        or os.environ.get("JAMA_LIVE_API_KEY")
        or (os.environ.get("JAMA_LIVE_USERNAME") and os.environ.get("JAMA_LIVE_PASSWORD"))
    )
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _CONFIGURED,
        reason="set JAMA_LIVE_URL, JAMA_LIVE_TEST_RUN_ID and credentials to run against Jama",
    ),
]


async def test_screenshot_in_test_run_step_loads_through_files_endpoint() -> None:
    http = _http_from_env()
    assert http is not None
    test_run_id = int(os.environ["JAMA_LIVE_TEST_RUN_ID"])
    step = int(os.environ.get("JAMA_LIVE_STEP", "1"))
    project = os.environ.get("JAMA_LIVE_PROJECT_ID")

    async with http:
        api = JamaApi(http)
        attachments = AttachmentService(api)  # no local upload map: always a real upload
        runs = TestRunService(api, attachments)

        before = run_fields(await api.get_test_run(test_run_id))
        steps_before = run_steps(before)
        name = step_actual_results_field(steps_before)

        result = await runs.attach_screenshots_to_test_run(
            test_run_id,
            [(f"jama-cli-live-{int(time.time())}.png", TINY_PNG)],
            step=step,
            caption="jama-cli live test",
            project_id=int(project) if project else None,
        )

        uploaded = result.attachments[0]
        # The embed URL uses the stored file's id, and Jama serves the file for it.
        assert f"/attachment/{uploaded.file_id}/" in uploaded.embed_url
        assert await api.get_file_by_url(uploaded.embed_url) == TINY_PNG
        assert await api.get_attachment_file(uploaded.attachment_id) == TINY_PNG

        steps_after = run_steps(run_fields(await api.get_test_run(test_run_id)))
        assert len(steps_after) == len(steps_before)
        assert f"/attachment/{uploaded.file_id}/" in steps_after[step - 1][name]
        for index, (old, new) in enumerate(zip(steps_before, steps_after, strict=True), start=1):
            if index != step:
                assert old == new
            else:
                assert old.get("status") == new.get("status")
                assert (new.get(name) or "").startswith(old.get(name) or "")
