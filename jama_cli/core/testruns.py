"""Safe edits of test run results: "Actual results" text and inline screenshots.

Every write is a read-modify-write: the run is fetched, ONLY the targeted
field or step is changed, everything a PUT needs is sent back, and the run is
read again to check that the write was stored and that nothing else changed.

Run-level field names and writability come from the instance's own definition
of the test run item type (``GET itemtypes``, ``typeKey == "TSTRN"``), not from
constants. Keys inside a step are not part of that definition and are constants
here. What a real Jama Cloud instance showed (details and what is still
unverified: ``docs/attachments-testruns-notes.md``):

- ``GET testruns/{id}`` omits empty fields, at run level and inside steps;
- the run-level ``actualResults`` is a writable TEXT field;
- the actual results of a step live under the step key ``result``. A step key
  ``actualResults`` is accepted by PUT with OK and silently dropped;
- the item type marks ``testRunSteps`` (STEPS) as ``readOnly``, yet a PUT of
  that field does store ``result`` and ``status`` of its steps. The flag does
  not describe PUT behaviour, so it is recorded but never used to refuse;
- writing a step ``status`` makes Jama recompute ``testRunStatus``.
"""

from __future__ import annotations

import copy
import weakref
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

# ``typeKey`` of the test run item type. The numeric id differs per instance.
TEST_RUN_TYPE_KEY = "TSTRN"
# Base names of the fields this module works with. On an instance they may carry
# a ``$<itemTypeId>`` suffix; the item type definition decides the real name.
RUN_ACTUAL_RESULTS_FIELD = "actualResults"
STEPS_FIELD = "testRunSteps"
STEPS_FIELD_TYPE = "STEPS"
# Keys inside a step object. They are not listed in the item type definition.
# The actual results of a step. This is the only step key ever written for them.
STEP_RESULT_KEY = "result"
# Keys that are read as the step's actual results if ``result`` is absent, for
# runs that carry them. They are never sent: Jama accepts and drops them.
STEP_RESULT_READ_FALLBACKS: tuple[str, ...] = ("actualResults",)
STEP_STATUS_KEY = "status"
# Fields a ``PUT testruns/{id}`` body carries by default (base names). Each is
# sent with its current value (modified where requested) when the run has it, so
# that a PUT that replaces the fields wholesale loses nothing.
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


def _base_name(name: str) -> str:
    """Field name without the ``$<itemTypeId>`` suffix of instance-specific fields."""
    return name.split("$", 1)[0]


def _is_empty(value: Any) -> bool:
    """Jama leaves empty fields out of a GET, so absent and empty are the same."""
    return value is None or value == "" or value == []


def _same(left: Any, right: Any) -> bool:
    return left == right or (_is_empty(left) and _is_empty(right))


@dataclass(frozen=True)
class TestRunSchema:
    """The test run fields of one Jama instance, from its item type definition."""

    __test__ = False  # not a pytest test class

    item_type_id: int
    # Real name of the run-level actual results field, and whether it is read-only.
    actual_results: str
    actual_results_read_only: bool
    # Real name of the field with the steps (None if the type has none).
    steps: str | None
    # What the item type says. Informational only: a PUT of the steps field
    # stores step results and statuses even when this is True.
    steps_read_only: bool
    field_names: frozenset[str]

    @classmethod
    def from_item_type(cls, item_type: dict[str, Any]) -> TestRunSchema:
        definitions = [f for f in item_type.get("fields") or [] if isinstance(f, dict)]
        by_name = {str(f["name"]): f for f in definitions if f.get("name")}

        def find(base: str) -> dict[str, Any] | None:
            if base in by_name:
                return by_name[base]
            return next((f for name, f in by_name.items() if _base_name(name) == base), None)

        actual = find(RUN_ACTUAL_RESULTS_FIELD)
        if actual is None:
            raise TestRunError(
                f"The test run item type of this Jama instance (id {item_type.get('id', '?')}) "
                f"has no '{RUN_ACTUAL_RESULTS_FIELD}' field, so actual results cannot be written."
            )
        steps = next(
            (f for f in by_name.values() if f.get("fieldType") == STEPS_FIELD_TYPE), None
        ) or find(STEPS_FIELD)
        return cls(
            item_type_id=int(item_type.get("id") or 0),
            actual_results=str(actual["name"]),
            actual_results_read_only=bool(actual.get("readOnly")),
            steps=str(steps["name"]) if steps else None,
            steps_read_only=bool(steps.get("readOnly")) if steps else True,
            field_names=frozenset(by_name),
        )

    def resolve(self, name: str) -> str:
        """Map a base name given by a caller to this instance's field name."""
        if name in self.field_names:
            return name
        return next((n for n in sorted(self.field_names) if _base_name(n) == name), name)

    @property
    def put_fields(self) -> tuple[str, ...]:
        """This instance's names of :data:`PUT_FIELDS`."""
        names = [self.steps] if self.steps else []
        names += [self.actual_results, self.resolve("assignedTo")]
        return tuple(names)


# One lookup per API connection ("per instance"): item types do not change while
# a process runs.
_SCHEMAS: weakref.WeakKeyDictionary[JamaApi, TestRunSchema] = weakref.WeakKeyDictionary()


async def test_run_schema(api: JamaApi) -> TestRunSchema:
    """The test run field definition of the instance behind ``api`` (cached)."""
    cached = _SCHEMAS.get(api)
    if cached is not None:
        return cached
    item_types = await api.get_item_types()
    match = next(
        (t for t in item_types if str(t.get("typeKey", "")).upper() == TEST_RUN_TYPE_KEY), None
    )
    if match is None or not isinstance(match.get("id"), int):
        raise TestRunError(
            f"This Jama instance has no item type with typeKey '{TEST_RUN_TYPE_KEY}'; "
            "the test run fields cannot be determined."
        )
    # itemtypes/{id} is the authoritative field list.
    schema = TestRunSchema.from_item_type(await api.get_item_type(match["id"]))
    _SCHEMAS[api] = schema
    return schema


test_run_schema.__test__ = False  # type: ignore[attr-defined]  # not a pytest test


def build_put_body(
    fields: dict[str, Any], extra: Sequence[str] = (), names: Sequence[str] = PUT_FIELDS
) -> dict[str, Any]:
    """Body of ``PUT testruns/{id}``: the ``names`` the run has, plus ``extra``."""
    chosen = [name for name in names if name in fields]
    chosen += [name for name in extra if name in fields and name not in chosen]
    return {"fields": {name: fields[name] for name in chosen}}


def step_result(step: dict[str, Any]) -> Any:
    """The actual results of a step: ``result``, else a read-side fallback key."""
    if not _is_empty(step.get(STEP_RESULT_KEY)):
        return step[STEP_RESULT_KEY]
    for key in STEP_RESULT_READ_FALLBACKS:
        if not _is_empty(step.get(key)):
            return step[key]
    return step.get(STEP_RESULT_KEY)


def _steps_for_put(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The step list as it is sent: complete, minus the keys Jama would drop."""
    return [
        {key: value for key, value in step.items() if key not in STEP_RESULT_READ_FALLBACKS}
        for step in steps
    ]


def run_fields(run: dict[str, Any]) -> dict[str, Any]:
    """The ``fields`` object of a test run."""
    fields = run.get("fields")
    if not isinstance(fields, dict):
        raise TestRunError(f"Test run {run.get('id', '?')} has no fields")
    return fields


def run_steps(
    fields: dict[str, Any], steps_field: str | None = STEPS_FIELD
) -> list[dict[str, Any]]:
    """The steps of a run (empty if it has none)."""
    steps = fields.get(steps_field) if steps_field else None
    if steps is None:
        return []
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        raise TestRunError(f"Unexpected format of the test run field {steps_field!r}")
    return steps


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

    async def schema(self) -> TestRunSchema:
        """Field names and writability of test runs on this instance (cached)."""
        return await test_run_schema(self._api)

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
        Run level is the item type's ``actualResults`` field, a step is its
        ``result`` key.
        """
        if mode not in ("append", "replace"):
            raise ValueError("mode must be 'append' or 'replace'")

        def transform(existing: str) -> str:
            return existing + html if mode == "append" else html

        return await self._edit_actual_results(test_run_id, step, transform, mode)

    def _put_body(
        self, schema: TestRunSchema, fields: dict[str, Any], extra: Sequence[str] = ()
    ) -> dict[str, Any]:
        """The PUT body: the run's result fields, with steps cleaned of dropped keys."""
        body = build_put_body(fields, extra=extra, names=schema.put_fields)
        if schema.steps and schema.steps in body["fields"]:
            body["fields"][schema.steps] = _steps_for_put(run_steps(fields, schema.steps))
        return body

    async def _edit_actual_results(
        self,
        test_run_id: int,
        step: int | None,
        transform: Callable[[str], str],
        mode: str,
    ) -> ActualResultsUpdate:
        schema = await self.schema()
        if step is None and schema.actual_results_read_only:
            raise TestRunError(
                f"The field {schema.actual_results!r} is read-only on this Jama instance (item "
                f"type {schema.item_type_id}); it cannot be written through the REST API."
            )

        run = await self._api.get_test_run(test_run_id)
        before = run_fields(run)
        fields = copy.deepcopy(before)

        # Jama omits empty fields from a GET: a run-level field the item type
        # lists, or a step without a result, is empty, not unknown.
        target: dict[str, Any]
        if step is None:
            target, name = fields, schema.actual_results
            existing = target.get(name) or ""
        else:
            steps = run_steps(fields, schema.steps)
            _check_step(steps, step, test_run_id)
            target, name = steps[step - 1], STEP_RESULT_KEY
            existing = step_result(target) or ""

        if not isinstance(existing, str):
            raise TestRunError(f"The field {name!r} of test run {test_run_id} is not text")
        new = transform(existing)
        if new == existing:
            return ActualResultsUpdate(test_run_id, step, name, mode, False, existing)

        target[name] = new
        # Jama's own error (locked cycle, missing permission, ...) propagates as it is.
        await self._api.put_test_run(test_run_id, self._put_body(schema, fields))

        after = run_fields(await self._api.get_test_run(test_run_id))
        if step is None:
            warnings = _verify_untouched(test_run_id, before, after, {}, schema.steps)
            stored = after.get(name)
        else:
            # The content of a fallback key was carried over into ``result``.
            written = {STEP_RESULT_KEY, *STEP_RESULT_READ_FALLBACKS}
            warnings = _verify_untouched(test_run_id, before, after, {step: written}, schema.steps)
            _verify_run_level_unchanged(test_run_id, before, after, schema.actual_results)
            stored = run_steps(after, schema.steps)[step - 1].get(name)
        label = name if step is None else f"{name} of step {step}"
        warnings += _verify_target(test_run_id, label, existing, new, stored)
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
            step: 1-based step index (its ``result``); ``None`` targets the run-level field
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
        schema = await self.schema()
        run = await self._api.get_test_run(test_run_id)
        if step is not None:
            _check_step(run_steps(run_fields(run), schema.steps), step, test_run_id)
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

        ``step`` + ``step_fields`` update the named keys of one 1-based step,
        e.g. ``{"status": "PASSED"}`` or ``{"result": "<p>...</p>"}``. A step key
        ``actualResults`` is written as ``result`` (Jama drops ``actualResults``).
        The update fails if Jama did not store a step value that was sent.
        """
        supplied = dict(data or {})
        nested = supplied.get("fields")
        changes: dict[str, Any] = dict(nested) if isinstance(nested, dict) else supplied
        if (step is None) != (step_fields is None):
            raise TestRunError("step and step_fields must be given together")
        if not changes and not step_fields:
            raise TestRunError("Nothing to update")

        warnings: list[str] = []
        step_changes: list[tuple[int, dict[str, Any]]] = []
        overlay = next(
            (changes.pop(k) for k in list(changes) if _base_name(k) == STEPS_FIELD), None
        )
        if overlay is not None:
            if not isinstance(overlay, list):
                raise TestRunError(f"{STEPS_FIELD} must be a list")
            for index, entry in enumerate(overlay, start=1):
                if entry:
                    if not isinstance(entry, dict):
                        raise TestRunError(f"Entry {index} of {STEPS_FIELD} must be an object")
                    step_changes.append((index, dict(entry)))
        if step is not None and step_fields:
            step_changes.append((step, dict(step_fields)))

        # Never send a key Jama accepts and drops: the step's actual results are ``result``.
        for index, entry in step_changes:
            for legacy in STEP_RESULT_READ_FALLBACKS:
                if legacy not in entry:
                    continue
                value = entry.pop(legacy)
                if STEP_RESULT_KEY in entry and entry[STEP_RESULT_KEY] != value:
                    raise TestRunError(
                        f"Step {index} has both {STEP_RESULT_KEY!r} and {legacy!r} with "
                        f"different values; give only {STEP_RESULT_KEY!r}."
                    )
                entry[STEP_RESULT_KEY] = value
                warnings.append(
                    f"Step {index}: {legacy!r} was written as {STEP_RESULT_KEY!r}, the key "
                    "Jama stores per-step actual results under."
                )

        schema = await self.schema()
        changes = {schema.resolve(name): value for name, value in changes.items()}
        actual = schema.actual_results
        if actual in changes and schema.actual_results_read_only:
            raise TestRunError(f"The field {actual!r} is read-only on this Jama instance.")

        run = await self._api.get_test_run(test_run_id)
        before = run_fields(run)
        fields = copy.deepcopy(before)
        touched: dict[int, set[str]] = {}

        if step_changes:
            steps = run_steps(fields, schema.steps)
            for index, entry in step_changes:
                _check_step(steps, index, test_run_id)
                steps[index - 1].update(entry)
                keys = set(entry)
                if STEP_RESULT_KEY in entry:
                    keys.update(STEP_RESULT_READ_FALLBACKS)
                touched.setdefault(index, set()).update(keys)

        fields.update(changes)
        if all(_same(fields.get(k), before.get(k)) for k in set(fields) | set(before)):
            return {"test_run_id": test_run_id, "updated": False, "warnings": warnings}

        await self._api.put_test_run(
            test_run_id, self._put_body(schema, fields, extra=list(changes))
        )

        after = run_fields(await self._api.get_test_run(test_run_id))
        warnings += _verify_untouched(test_run_id, before, after, touched, schema.steps)
        if actual not in changes:
            _verify_run_level_unchanged(test_run_id, before, after, actual)
        _verify_step_writes(test_run_id, step_changes, after, schema.steps)
        for name in changes:
            previous = before.get(name)
            if isinstance(fields.get(name), str) or isinstance(previous, str):
                warnings += _verify_target(
                    test_run_id, name, previous or "", fields.get(name) or "", after.get(name)
                )
        return {
            "test_run_id": test_run_id,
            "updated": True,
            "updated_fields": sorted(changes),
            "updated_steps": sorted({index for index, _entry in step_changes}),
            "warnings": warnings,
        }


def _verify_untouched(
    test_run_id: int,
    before: dict[str, Any],
    after: dict[str, Any],
    touched: dict[int, set[str]],
    steps_field: str | None = STEPS_FIELD,
) -> list[str]:
    """Check that the PUT changed no step (or step key) it was not meant to change.

    ``touched`` maps 1-based step numbers to the keys that were written.
    """
    steps_before = run_steps(before, steps_field)
    steps_after = run_steps(after, steps_field)
    if len(steps_before) != len(steps_after):
        raise TestRunVerificationError(
            f"Test run {test_run_id} had {len(steps_before)} step(s) before the update and has "
            f"{len(steps_after)} now. Check the run in Jama."
        )
    problems: list[str] = []
    for number, (old, new) in enumerate(zip(steps_before, steps_after, strict=True), start=1):
        written = touched.get(number, set())
        changed = sorted(
            key
            for key in set(old) | set(new)
            if key not in written and not _same(old.get(key), new.get(key))
        )
        if changed:
            problems.append(f"step {number}: {', '.join(changed)}")
    if problems:
        raise TestRunVerificationError(
            f"The update of test run {test_run_id} changed content it was not meant to change "
            f"({'; '.join(problems)}). Check the run in Jama."
        )
    return []


def _verify_step_writes(
    test_run_id: int,
    step_changes: list[tuple[int, dict[str, Any]]],
    after: dict[str, Any],
    steps_field: str | None,
) -> None:
    """Check that the step values that were sent are really stored."""
    steps_after = run_steps(after, steps_field)
    lost: list[str] = []
    for number, entry in step_changes:
        stored = steps_after[number - 1]
        missing = sorted(key for key, value in entry.items() if not _same(stored.get(key), value))
        if missing:
            lost.append(f"step {number}: {', '.join(missing)}")
    if lost:
        raise TestRunVerificationError(
            f"Jama accepted the update of test run {test_run_id} but did not store "
            f"{'; '.join(lost)}. Jama silently drops step keys it does not know "
            "(see docs/attachments-testruns-notes.md)."
        )


def _verify_run_level_unchanged(
    test_run_id: int,
    before: dict[str, Any],
    after: dict[str, Any],
    name: str = RUN_ACTUAL_RESULTS_FIELD,
) -> None:
    if not _same(before.get(name), after.get(name)):
        raise TestRunVerificationError(
            f"The update of test run {test_run_id} changed the run-level "
            f"{name!r}, which it was not meant to change. Check the run in Jama."
        )


def _verify_target(
    test_run_id: int, name: str, existing: str, expected: str, stored: Any
) -> list[str]:
    """Check the written field. Returns warnings; raises if the write was lost."""
    if _same(stored, expected):
        return []
    if not isinstance(stored, str) or not stored or stored == existing:
        raise TestRunVerificationError(
            f"Jama accepted the update of test run {test_run_id} but did not store the new "
            f"{name}. Jama silently drops fields and step keys it does not know "
            "(see docs/attachments-testruns-notes.md)."
        )
    if existing and expected.startswith(existing) and not stored.startswith(existing):
        raise TestRunVerificationError(
            f"After the update of test run {test_run_id} the previous content of {name} is no "
            "longer intact. Check the run in Jama."
        )
    return [f"Jama stored {name} differently from what was sent (HTML clean-up on save)."]
