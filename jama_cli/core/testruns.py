"""Safe edits of test run results: "Actual results" text and inline screenshots.

Every write is a read-modify-write: the run is fetched, ONLY the targeted
field(s) or step(s) are changed, everything a PUT needs is sent back, and the
run is read again to check that nothing else changed.

The field names and the set of fields a PUT carries could not be checked
against a real Jama instance when this was written. They are kept in the
constants right below so that each one is a one-line change; see
``docs/attachments-testruns-notes.md``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from jama_cli.core.api import JamaApi
from jama_cli.core.attachments import (
    AttachmentService,
    FileSource,
    UploadedAttachment,
    html_contains_url,
    read_source,
    screenshot_block_html,
)
from jama_cli.core.exceptions import JamaException

# --- Test run field names (UNVERIFIED, adjust here) --------------------------

# Run-level rich-text field with the actual results.
RUN_ACTUAL_RESULTS_FIELD = "actualResults"
# Field holding the list of steps.
STEPS_FIELD = "testRunSteps"
# Per-step rich-text field with the actual results. The first name found on any
# step of the run is used; if none is present, the first entry is the default.
STEP_ACTUAL_RESULTS_FIELDS: tuple[str, ...] = ("actualResults", "result")
# The ONLY place that decides which fields a ``PUT testruns/{id}`` body carries.
# Each of them is sent with its current value (modified where requested) when
# the run has it, so that a PUT that replaces the fields wholesale loses nothing.
PUT_FIELDS: tuple[str, ...] = (STEPS_FIELD, RUN_ACTUAL_RESULTS_FIELD, "assignedTo")
# Where a run points at its test cycle (used to find the project if the run
# itself does not name it).
RUN_CYCLE_FIELD = "testCycle"

EditMode = Literal["append", "replace"]


class TestRunError(JamaException):
    """A test run could not be read or edited as requested."""

    __test__ = False  # not a pytest test class


class TestRunVerificationError(TestRunError):
    """After a PUT the run differs from what was intended."""

    __test__ = False


def build_put_body(fields: dict[str, Any], extra: Sequence[str] = ()) -> dict[str, Any]:
    """Body of ``PUT testruns/{id}``: the :data:`PUT_FIELDS` the run has, plus ``extra``."""
    names = [name for name in PUT_FIELDS if name in fields]
    names += [name for name in extra if name in fields and name not in names]
    return {"fields": {name: fields[name] for name in names}}


def run_fields(run: dict[str, Any]) -> dict[str, Any]:
    """The ``fields`` object of a test run."""
    fields = run.get("fields")
    if not isinstance(fields, dict):
        raise TestRunError(f"Test run {run.get('id', '?')} has no fields")
    return fields


def run_steps(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """The steps of a run (empty if it has none)."""
    steps = fields.get(STEPS_FIELD)
    if steps is None:
        return []
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        raise TestRunError(f"Unexpected format of the test run field {STEPS_FIELD!r}")
    return steps


def step_actual_results_field(steps: list[dict[str, Any]]) -> str:
    """Name of the per-step actual-results field used by this run."""
    for name in STEP_ACTUAL_RESULTS_FIELDS:
        if any(name in step for step in steps):
            return name
    return STEP_ACTUAL_RESULTS_FIELDS[0]


def _check_step(steps: list[dict[str, Any]], step: int, test_run_id: int) -> None:
    if not steps:
        raise TestRunError(f"Test run {test_run_id} has no steps")
    if not 1 <= step <= len(steps):
        raise TestRunError(
            f"Test run {test_run_id} has {len(steps)} step(s); step {step} does not exist "
            "(steps are numbered from 1)"
        )


@dataclass
class ActualResultsUpdate:
    """Outcome of an edit of an actual-results field."""

    test_run_id: int
    step: int | None
    field_name: str
    mode: str
    updated: bool
    html: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_run_id": self.test_run_id,
            "step": self.step,
            "field": self.field_name,
            "mode": self.mode,
            "updated": self.updated,
            "html": self.html,
            "warnings": list(self.warnings),
        }


@dataclass
class ScreenshotsResult:
    """Outcome of attaching screenshots to a test run."""

    test_run_id: int
    step: int | None
    updated: bool
    attachments: list[UploadedAttachment]
    embedded: list[str]
    skipped: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_run_id": self.test_run_id,
            "step": self.step,
            "updated": self.updated,
            "attachments": [a.to_dict() for a in self.attachments],
            "embedded": list(self.embedded),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
        }


class TestRunService:
    """Read-modify-write edits of test runs on top of :class:`JamaApi`."""

    __test__ = False  # not a pytest test class

    def __init__(self, api: JamaApi, attachments: AttachmentService | None = None) -> None:
        self._api = api
        self._attachments = attachments or AttachmentService(api)

    async def get_test_run(self, test_run_id: int) -> dict[str, Any]:
        """Get a test run with its steps."""
        return await self._api.get_test_run(test_run_id)

    # ----- actual results -------------------------------------------------

    async def append_to_actual_results(
        self,
        test_run_id: int,
        html: str,
        step: int | None = None,
        mode: EditMode = "append",
    ) -> ActualResultsUpdate:
        """Add HTML to the actual results of a run (``step=None``) or of a 1-based step.

        The existing HTML is kept and ``html`` is appended to it. Only
        ``mode="replace"`` replaces the content of the targeted field.
        """
        if mode not in ("append", "replace"):
            raise ValueError("mode must be 'append' or 'replace'")

        def transform(existing: str) -> str:
            return existing + html if mode == "append" else html

        return await self._edit_actual_results(test_run_id, step, transform, mode)

    async def _edit_actual_results(
        self,
        test_run_id: int,
        step: int | None,
        transform: Callable[[str], str],
        mode: str,
    ) -> ActualResultsUpdate:
        run = await self._api.get_test_run(test_run_id)
        before = run_fields(run)
        fields = copy.deepcopy(before)

        target: dict[str, Any]
        if step is None:
            target, name = fields, RUN_ACTUAL_RESULTS_FIELD
        else:
            steps = run_steps(fields)
            _check_step(steps, step, test_run_id)
            target, name = steps[step - 1], step_actual_results_field(steps)

        existing = target.get(name) or ""
        if not isinstance(existing, str):
            raise TestRunError(f"The field {name!r} of test run {test_run_id} is not text")
        new = transform(existing)
        if new == existing:
            return ActualResultsUpdate(test_run_id, step, name, mode, False, existing)

        target[name] = new
        # Jama's own error (locked cycle, missing permission, ...) propagates as it is.
        await self._api.put_test_run(test_run_id, build_put_body(fields))

        after = run_fields(await self._api.get_test_run(test_run_id))
        warnings = _verify_untouched(test_run_id, before, after, {} if step is None else {step})
        if step is not None:
            _verify_run_level_unchanged(test_run_id, before, after)
            stored = run_steps(after)[step - 1].get(name)
        else:
            stored = after.get(name)
        warnings += _verify_target(test_run_id, name, existing, new, stored, mode)
        return ActualResultsUpdate(
            test_run_id,
            step,
            name,
            mode,
            True,
            stored if isinstance(stored, str) else new,
            warnings,
        )

    # ----- screenshots ----------------------------------------------------

    async def project_of_run(self, test_run_id: int, run: dict[str, Any] | None = None) -> int:
        """The project a test run belongs to (from the run, else from its cycle)."""
        if run is None:
            run = await self._api.get_test_run(test_run_id)
        fields = run_fields(run)
        for candidate in (run.get("project"), fields.get("project")):
            if isinstance(candidate, int):
                return candidate
        cycle_id = fields.get(RUN_CYCLE_FIELD)
        if isinstance(cycle_id, int):
            cycle = await self._api.get_test_cycle(cycle_id)
            cycle_fields = cycle.get("fields")
            candidates = [cycle.get("project")]
            if isinstance(cycle_fields, dict):
                candidates.append(cycle_fields.get("project"))
            for candidate in candidates:
                if isinstance(candidate, int):
                    return candidate
        raise TestRunError(
            f"Could not determine the project of test run {test_run_id}; pass the project id"
        )

    async def attach_screenshots_to_test_run(
        self,
        test_run_id: int,
        files: Sequence[FileSource | tuple[str, bytes]],
        step: int | None = None,
        caption: str | None = None,
        project_id: int | None = None,
        use_cache: bool = True,
    ) -> ScreenshotsResult:
        """Upload images and embed them in the actual results of a run or step.

        Each file becomes a ``<p>caption</p><p><img .../></p>`` block appended to
        the existing HTML. All images of one call go into a single PUT. An image
        whose URL the field already contains is not added again.

        Args:
            test_run_id: Test run to add the screenshots to
            files: Paths, or ``(file name, bytes)`` pairs
            step: 1-based step index; ``None`` targets the run-level field
            caption: Plain text shown above each image (also its alt text)
            project_id: Project for the attachments (default: the run's project)
            use_cache: Reuse earlier uploads of the same bytes
        """
        if not files:
            raise TestRunError("No files given")

        # Everything that can fail cheaply fails before the first upload.
        sources = [
            read_source(f[1], f[0]) if isinstance(f, tuple) else read_source(f) for f in files
        ]
        run = await self._api.get_test_run(test_run_id)
        if step is not None:
            _check_step(run_steps(run_fields(run)), step, test_run_id)
        if project_id is None:
            project_id = await self.project_of_run(test_run_id, run)

        uploads: list[UploadedAttachment] = []
        warnings: list[str] = []
        for file_name, content in sources:
            uploaded = await self._attachments.upload_attachment(
                test_run_id,
                content,
                file_name=file_name,
                project_id=project_id,
                link=True,
                # The image works without the Attachments-tab link, so a refused
                # link must not stop the embed.
                link_optional=True,
                use_cache=use_cache,
            )
            uploads.append(uploaded)
            warnings += uploaded.warnings

        embedded: list[str] = []
        skipped: list[str] = []

        def transform(existing: str) -> str:
            embedded.clear()
            skipped.clear()
            blocks = ""
            for uploaded in uploads:
                url = uploaded.embed_url
                if html_contains_url(existing, url) or url in embedded:
                    skipped.append(url)
                    continue
                blocks += screenshot_block_html(url, caption or uploaded.name, caption)
                embedded.append(url)
            return existing + blocks

        update = await self._edit_actual_results(test_run_id, step, transform, "append")
        for url in embedded:
            if not html_contains_url(update.html, url):
                update.warnings.append(
                    f"The image {url} is not in the stored field; Jama may have removed it."
                )
        return ScreenshotsResult(
            test_run_id=test_run_id,
            step=step,
            updated=update.updated,
            attachments=uploads,
            embedded=list(embedded),
            skipped=list(skipped),
            warnings=warnings + update.warnings,
        )

    # ----- generic partial update -----------------------------------------

    async def update_test_run(
        self,
        test_run_id: int,
        data: dict[str, Any] | None = None,
        step: int | None = None,
        step_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Partial update of a test run that cannot wipe other steps or fields.

        ``data`` is ``{"fields": {...}}`` (or the fields object itself). Its
        values are merged into the current run:

        - ``testRunSteps`` is overlaid by position: entry *i* updates step *i+1*
          with the keys it names, ``{}``/``null`` leaves that step alone, and
          steps beyond the given list are kept as they are;
        - every other field replaces the current value.

        ``step`` + ``step_fields`` update the named keys of one 1-based step.
        """
        supplied = dict(data or {})
        nested = supplied.get("fields")
        changes: dict[str, Any] = dict(nested) if isinstance(nested, dict) else supplied
        if (step is None) != (step_fields is None):
            raise TestRunError("step and step_fields must be given together")
        if not changes and not step_fields:
            raise TestRunError("Nothing to update")

        run = await self._api.get_test_run(test_run_id)
        before = run_fields(run)
        fields = copy.deepcopy(before)
        touched: dict[int, set[str]] = {}

        step_changes: list[tuple[int, dict[str, Any]]] = []
        if STEPS_FIELD in changes:
            overlay = changes.pop(STEPS_FIELD)
            if not isinstance(overlay, list):
                raise TestRunError(f"{STEPS_FIELD} must be a list")
            for index, entry in enumerate(overlay, start=1):
                if entry:
                    if not isinstance(entry, dict):
                        raise TestRunError(f"Entry {index} of {STEPS_FIELD} must be an object")
                    step_changes.append((index, entry))
        if step is not None and step_fields:
            step_changes.append((step, step_fields))

        if step_changes:
            steps = run_steps(fields)
            for index, entry in step_changes:
                _check_step(steps, index, test_run_id)
                steps[index - 1].update(entry)
                touched.setdefault(index, set()).update(entry)

        fields.update(changes)
        if fields == before:
            return {"test_run_id": test_run_id, "updated": False, "warnings": []}

        await self._api.put_test_run(test_run_id, build_put_body(fields, extra=list(changes)))

        after = run_fields(await self._api.get_test_run(test_run_id))
        warnings = _verify_untouched(test_run_id, before, after, touched)
        if RUN_ACTUAL_RESULTS_FIELD not in changes:
            _verify_run_level_unchanged(test_run_id, before, after)
        return {
            "test_run_id": test_run_id,
            "updated": True,
            "updated_fields": sorted(changes),
            "updated_steps": sorted(touched),
            "warnings": warnings,
        }


def _verify_untouched(
    test_run_id: int,
    before: dict[str, Any],
    after: dict[str, Any],
    touched: dict[int, set[str]] | set[int],
) -> list[str]:
    """Check that the PUT changed no step (or step key) it was not meant to change.

    ``touched`` maps 1-based step numbers to the keys that were written; a plain
    set of step numbers means "only the actual-results field of these steps".
    """
    steps_before = run_steps(before)
    steps_after = run_steps(after)
    if len(steps_before) != len(steps_after):
        raise TestRunVerificationError(
            f"Test run {test_run_id} had {len(steps_before)} step(s) before the update and has "
            f"{len(steps_after)} now. Check the run in Jama."
        )
    actual_field = step_actual_results_field(steps_before)
    problems: list[str] = []
    for number, (old, new) in enumerate(zip(steps_before, steps_after, strict=True), start=1):
        if isinstance(touched, dict):
            written = touched.get(number, set())
        else:
            written = {actual_field} if number in touched else set()
        changed = sorted(
            key
            for key in set(old) | set(new)
            if key not in written and old.get(key) != new.get(key)
        )
        if changed:
            problems.append(f"step {number}: {', '.join(changed)}")
    if problems:
        raise TestRunVerificationError(
            f"The update of test run {test_run_id} changed content it was not meant to change "
            f"({'; '.join(problems)}). Check the run in Jama."
        )
    return []


def _verify_run_level_unchanged(
    test_run_id: int, before: dict[str, Any], after: dict[str, Any]
) -> None:
    if before.get(RUN_ACTUAL_RESULTS_FIELD) != after.get(RUN_ACTUAL_RESULTS_FIELD):
        raise TestRunVerificationError(
            f"The update of test run {test_run_id} changed the run-level "
            f"{RUN_ACTUAL_RESULTS_FIELD!r}, which it was not meant to change. Check the run in Jama."
        )


def _verify_target(
    test_run_id: int, name: str, existing: str, expected: str, stored: Any, mode: str
) -> list[str]:
    """Check the written field. Returns warnings; raises if the write was lost."""
    if stored == expected:
        return []
    if not isinstance(stored, str) or not stored or stored == existing:
        raise TestRunVerificationError(
            f"Jama accepted the update of test run {test_run_id} but did not store the new "
            f"{name!r}. The field name or the fields accepted by PUT may differ on this instance "
            "(see docs/attachments-testruns-notes.md)."
        )
    if mode == "append" and existing and not stored.startswith(existing):
        raise TestRunVerificationError(
            f"After the update of test run {test_run_id} the previous content of {name!r} is no "
            "longer intact. Check the run in Jama."
        )
    return [f"Jama stored {name!r} differently from what was sent (HTML clean-up on save)."]
