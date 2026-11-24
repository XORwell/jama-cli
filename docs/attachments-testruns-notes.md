# Attachments and test run screenshots: design and open points

This feature was implemented **without access to a real Jama instance**. Everything
below marked UNVERIFIED is an assumption taken from the task description or from
general knowledge of the Jama REST API. Each one names the single place in the code
to change if a real instance behaves differently. Please run the checklist at the
end against a scratch project before relying on the feature.

## Design

```
CLI (jama_cli/commands/attachments.py, testruns.py)      MCP (jama_mcp_server/core/attachment_tools.py)
            |  sync                                                   |  async
      JamaClient (core/client.py) -- SyncJamaApi.run() --+            |
                                                         v            v
                              AttachmentService (core/attachments.py)
                              TestRunService    (core/testruns.py)
                                                         |
                                     JamaApi (core/api.py): one method per HTTP call
                                                         |
                                     JamaHttpClient.request(): auth, session repair
```

- `jama_cli/core/api.py` has one small method per HTTP call
  (`post_project_attachment`, `put_attachment_file`, `post_item_attachment`,
  `get_attachment`, `get_attachment_file`, `get_file_by_url`,
  `post_internal_attachment`, `get_test_run`, `put_test_run`).
- `jama_cli/core/attachments.py` holds the logic: upload = create, PUT file, link,
  read `fields.attachment` (file id), build the embed URL, verify it through
  `files?url=`. It also holds the HTML helpers, the content-type table, the size
  limit and the local upload map.
- `jama_cli/core/testruns.py` holds the read-modify-write logic for test runs.
- The CLI and the MCP server are thin layers over these two services, so both
  behave the same.
- File content is always passed as `bytes`, so a request can be sent again after
  the HTTP client repaired a session.
- All URLs are built from the configured base URL (`JamaHttpClient.base_url`),
  including a context path such as `/contour`.

### Upload

1. `POST projects/{projectId}/attachments` with `{"fields": {"name", "description"}}`.
2. `PUT attachments/{id}/file`, multipart part `file` with file name and content type.
3. `POST items/{itemId}/attachments` with `{"attachment": id}` (skipped with `--no-link`).
4. `GET attachments/{id}`; the file id is `data.fields.attachment`.
5. Embed URL `<base>/attachment/<fileId>/<url-encoded file name>`.
6. `GET files?url=<embed url>` must return 200 with a non-empty body, otherwise
   `EmbedVerificationError`.

The project defaults to the `project` of the item (`GET items/{id}`).

### Session-auth fallback

Under `auth_type=session` only: if step 1 is refused, `POST <base>/ui/internal/attachments`
is used (multipart parts `file`, `itemId`, `attachmentDocument`, `originalFileName`). It
creates and links in one call, so steps 2 and 3 are skipped. The decision is taken from the
exception `JamaHttpClient` finally raises, i.e. after it has refreshed the CSRF token or
logged in again on its own:

- 401 or 403 from the REST create -> fallback (`REST_CREATE_REFUSED_STATUSES` in
  `core/attachments.py`);
- 401 with the "run `jama login`" hint (session could not be repaired) -> no fallback,
  the error is raised;
- any other status (400, 404, 5xx) -> no fallback;
- any other auth mode -> never a fallback (`JamaApi.uses_session_auth` is false).

If the internal endpoint fails too, the error names both failures.

### Test run edits

`TestRunService._edit_actual_results` and `TestRunService.update_test_run`:

1. `GET testruns/{id}`.
2. Change only the targeted field in a copy of `fields`.
3. `PUT testruns/{id}` with the body from `build_put_body()`: every field in
   `PUT_FIELDS` that the run has, with the complete, otherwise unmodified step list.
4. `GET testruns/{id}` again and compare:
   - step count changed, another step changed, another key of the targeted step
     changed, or the run-level field changed although a step was targeted
     -> `TestRunVerificationError`;
   - the targeted field still has its old value or is empty -> `TestRunVerificationError`
     ("did not store");
   - in append mode the old content is no longer the start of the field
     -> `TestRunVerificationError`;
   - the field was stored, but not byte-identical to what was sent (HTML clean-up by
     Jama) -> a warning, not an error.
5. A failing PUT (locked cycle, missing permission) raises Jama's own error. Nothing
   is retried.

Screenshots: all files are read and the step index is checked before the first upload;
each file is uploaded (and linked to the test run, a refused link is only a warning);
all `<p>caption</p><p><img .../></p>` blocks of one call are written with one PUT.

### Idempotency

- Local upload map: `~/.cache/jama-cli/uploads/<hash of base URL>.json`, key
  `"<projectId>:<sha256 of the bytes>"`, value attachment id, file id, embed URL, name.
  Before an entry is reused its embed URL is checked; a dead entry is dropped and the
  file is uploaded again. Before linking a reused attachment, `GET items/{id}/attachments`
  is read so that it is not linked twice.
- An `<img>` whose embed URL is already in the target field is not added again; if
  nothing would change, no PUT is sent.

### Behaviour changes to existing code

- `JamaClient.upload_attachment` now returns a dict (`attachment_id`, `file_id`,
  `embed_url`, ...) instead of an int. The old method never worked (it sent the
  file path as an attachment id).
- `JamaClient.download_attachment` writes the file's bytes and returns the path;
  it used to write the metadata as JSON and return nothing.
- MCP tool `update_test_run` merges `data` into the current run instead of sending
  it verbatim as the PUT body, returns a dict instead of the status number, and
  `data` is no longer required (`step` + `step_fields` is the alternative).
- `JamaApi._status()` accepts Jama's textual status (`"OK"`, `"Created"`) instead of
  raising `ValueError`. This affected every call that returned a status
  (`post_item_attachment`, `put_test_run`, `post_item_tag`, ...).

## UNVERIFIED assumptions and where to adjust them

| # | Assumption | Where to change |
|---|------------|-----------------|
| 1 | The run-level rich-text field is `fields.actualResults`. | `RUN_ACTUAL_RESULTS_FIELD` in `jama_cli/core/testruns.py` |
| 2 | The steps are in `fields.testRunSteps`, a list of objects in step order. | `STEPS_FIELD` in `jama_cli/core/testruns.py` |
| 3 | The per-step actual-results field is `actualResults`. If no step of the run has that key but one has `result`, `result` is used. | `STEP_ACTUAL_RESULTS_FIELDS` in `jama_cli/core/testruns.py` (first match wins, first entry is the default) |
| 4 | `PUT testruns/{id}` accepts `{"fields": {...}}` with `testRunSteps`, `actualResults` and `assignedTo`, and rejects or ignores nothing in that set. | `PUT_FIELDS` in `jama_cli/core/testruns.py` (the only place that decides what a PUT carries) |
| 5 | Whether PUT needs the full `testRunSteps` list is unknown. The code always sends the full list, and each step object as it was read (all its keys). If Jama rejects read-only keys inside a step (e.g. `action`), filter them in `build_put_body()`. | `build_put_body()` in `jama_cli/core/testruns.py` |
| 6 | Jama omits no key that PUT needs: a field missing from the GET response is not sent. If an empty step field is omitted from GET, the default name of #3 is written. | `step_actual_results_field()` / `build_put_body()` |
| 7 | The run's project is `project` on the run (top level or in `fields`), else `project` of the cycle in `fields.testCycle`. Otherwise pass `--project` / `project_id`. | `TestRunService.project_of_run()`, `RUN_CYCLE_FIELD` |
| 8 | Under SSO, "refused" for the REST create is HTTP 401 or 403. The message is not inspected. If the refusal is another status, or should depend on the message, change it here. | `REST_CREATE_REFUSED_STATUSES` and `is_rest_create_refused()` in `jama_cli/core/attachments.py` |
| 9 | A 401 with an empty message is first treated as a dead session by the HTTP client (CSRF refresh, re-login). The fallback only happens if the 401 survives that, so a refusal with an empty 401 costs one extra GET (CSRF refresh) and one repeated POST before the fallback. | `JamaHttpClient._session_request` (not changed here) |
| 10 | The internal endpoint takes `itemId`, `attachmentDocument` (JSON) and `originalFileName` as plain form fields and `file` as a file part, answers with JSON containing `meta.id`, and needs no further parameters or headers. | `JamaApi.post_internal_attachment()` in `jama_cli/core/api.py` |
| 11 | The file id is `data.fields.attachment` of `GET attachments/{id}`. | `FILE_ID_FIELD` / `file_id_of()` in `jama_cli/core/attachments.py` |
| 12 | The embed URL uses the uploaded file name, URL-encoded with `%20` for spaces. | `build_embed_url()` in `jama_cli/core/attachments.py` |
| 13 | `GET attachments/{id}/file` and `GET files?url=` return the bytes directly (no redirect to another host) and accept `Accept: */*`. A redirect would be reported as an error. | `JamaApi.get_attachment_file()` / `get_file_by_url()` |
| 14 | `PUT attachments/{id}/file` accepts the multipart part name `file`; the response body is not read. | `JamaApi.put_attachment_file()` |
| 15 | `POST items/{id}/attachments` and `PUT testruns/{id}` answer with a JSON body (the code parses it). An empty body would raise after the write succeeded. | `JamaHttpClient.post()` / `put()` |
| 16 | `GET items/{id}/attachments` lists linked attachments with their `id`. If it fails, the link is simply attempted. A repeated link either returns 409 (treated as linked) or is prevented by this check. | `AttachmentService._is_linked()` / `link_attachment()` |
| 17 | `GET items/{id}` works for a test run id (only used when `upload_attachment` is called for a run without a project id; the test-run commands pass the project). | `AttachmentService._project_of_item()` |
| 18 | Jama keeps existing HTML byte-identical when a field is saved again. If it rewrites existing HTML on every save, the "previous content no longer intact" check raises although nothing was lost. | `_verify_target()` in `jama_cli/core/testruns.py` |
| 19 | Jama's rich-text clean-up keeps `<img src=... alt=... />` inside `<p>`. If it strips the image, the result carries a warning ("not in the stored field"). | `screenshot_block_html()` in `jama_cli/core/attachments.py` |

## Checklist for the real instance

Use a scratch project and a scratch test run.

1. `jama -o json testruns get <runId>`: compare the field names with #1 to #3 and #7.
2. `jama attachments upload <itemId> some.png --json`: `attachment_id` and `file_id`
   differ, the embed URL opens in a logged-in browser, and the file is on the item's
   Attachments tab.
3. `jama attachments download <attachmentId> -o out.png` and
   `jama attachments download-url "<embed url>" -o out2.png`: both files equal the original.
4. `jama testruns set-actual <runId> --html "<p>cli test</p>" --step 1`: only step 1
   changed in the UI; statuses unchanged. A `TestRunVerificationError` here points at
   #3 to #6 or #18.
5. `jama testruns add-screenshot <runId> some.png --step 1 --caption "cli test"`: the
   image shows in step 1; run it a second time: no second attachment, no second image.
   A warning about the Attachments tab means the instance does not allow linking to
   test runs.
6. With `auth_type: session` as an SSO user: repeat 2 and 5 with `-vv`. The log line
   "Jama refused the REST attachment create; using the internal web UI endpoint" shows
   the fallback was used. If the upload fails instead, note the HTTP status and message
   Jama returned (#8, #10).
7. Try 4 on a run in a locked/closed cycle: Jama's error is shown, nothing is changed.
8. Optional: the opt-in live test, see the docstring of `tests/test_attachments_live.py`.

## Not done

- The HTTP-mode MCP server (`jama_mcp_server/core/server.py`) was not changed; the new
  tools exist in the stdio server only.
- No retry and no rollback: if the embed URL check fails after the upload, the
  attachment that was just created stays in Jama.
