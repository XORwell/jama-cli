# Session auth: design note

Auth mode `session` reuses a Jama web session (cookies `JSESSIONID` + `jama-csrf-token`) for
REST calls. Code: `jama_cli/core/session_store.py`, `session.py`, `browser_login.py`, the session
path in `http_client.py`, and `commands/auth.py`.

## Store format

One JSON file per `(base_url, account)`: `~/.jama/sessions/<sha256(base_url|account)[:24]>.json`
(`JAMA_SESSION_DIR` / `session_file` override the location). `account` is the configured
`username`, or empty when it is not known before the login.

```json
{
  "base_url": "https://host/contour",
  "username": "from users/current",
  "cookies": [{"name": "...", "value": "...", "domain": "...", "path": "..."}],
  "csrf_token": "...",
  "created_at": 0.0,
  "last_validated_at": 0.0
}
```

All cookies that apply to the base URL are kept, not only the two Jama ones, because load
balancers in front of Jama may need their own. Mode 0600 (Windows: ACL reduced to the current
user with `icacls`), directory 0700.

## Lock strategy

- `filelock.FileLock` on `<file>.lock`, held for a whole login (probe, login, save) and for
  every write of the file. It is acquired by non-blocking polling on the event loop, so waiting
  for another process's interactive login does not block other coroutines. The wait is bounded
  by `login_timeout + 60 s`.
- Inside one process an `asyncio.Lock` serialises recovery between coroutines (the file lock is
  re-entrant per instance and would not).
- Writes are atomic: temp file in the same directory, `fsync`, `os.replace`.
- Reads are lock-free; they see either the old or the new file.

## Refresh sequence

Jama checks the `jama-csrf-token` header on every call, reads included. A request can therefore
be turned down for two different reasons:

- CSRF problem, session alive: 401 whose `meta.message` contains "csrf" (any case; Jama sends
  "CSRF Exception" for a wrong or missing header);
- dead session: 401 with an empty or other message, or a 3xx whose `Location` contains
  `/login`, `/saml` or `j_acegi`.

A 401 that mentions "permission" is neither. It is returned to the caller immediately and never
causes a retry or a login.

For each request that is turned down, each step runs at most once:

1. CSRF repair, for every HTTP method:
   1. if the `jama-csrf-token` cookie holds a different value than the header that was sent,
      use the cookie's value as the header, save, retry;
   2. otherwise, or if that was not enough: one authenticated GET (`users/current`) that sends
      the cookie's value as the header, never the header that was just rejected. Take over its
      `Set-Cookie`, save, retry. A write that was turned down *without* a CSRF message also
      gets this step; a read that looks like a dead session skips it, because the GET could
      only confirm that.
2. Re-read the store. If it holds a different session than the one that just failed, retry
   with it.
3. Take the lock and re-read the store. If it now holds a different session and that one passes
   the probe, use it. Otherwise log in (respecting `login_interactive`), save, retry.
4. Still turned down: `UnauthorizedException` telling the user to run `jama login`.

One deliberate rule: if the GET in step 1.2 is accepted, the session is proven alive and holds
the current token, so the result of the retry is final and steps 2 and 3 are skipped. Logging in
again could not fix a request that a live session with a fresh token cannot perform, and it
would cost the user an interactive login. Steps 2 and 3 run when that GET is turned down too.

### Cookies set by ordinary responses

`Set-Cookie` is taken over from every response, not only from the probe, in case Jama replaces
`jama-csrf-token` or `JSESSIONID` during a session:

- a response that accepted the request: all cookies;
- a CSRF rejection: only `jama-csrf-token`;
- a dead-session response: nothing, since the anonymous `JSESSIONID` it may carry must not
  replace the stored session.

A change is saved under the lock with the usual atomic write, and only if the store still holds
the session being updated (same `JSESSIONID` as before the change). An update therefore never
overwrites a newer login from another process and never brings back a session that was logged
out.

## Login

The only success criterion is the authenticated probe (`GET rest/v1/users/current`, falling
back to `projects?maxResults=1`), with manual redirects. Browser mode polls it every 500 ms with
the cookies of the browser context, ignores the landing URL, and tolerates page and context
errors during the SAML redirect chain. Headless is tried first when a browser profile exists;
a visible login form, or 20 s without a session, switches to a visible window.

## Verified against a real Jama instance

Checked against a Jama Cloud instance with SSO on 2026-11-24:

- `rest/v1` accepts the web session cookies plus the `jama-csrf-token` header (GET, POST, PUT,
  DELETE);
- the CSRF header is required on every call, reads included; a wrong or missing one gives
  401 "CSRF Exception";
- the SSO button is recognised and the login through the login page works (tested under WSLg);
- `JSESSIONID` works outside the browser (other process, other user agent);
- a dead session is a 401 with an empty `meta.message` and no redirect;
- `logout.req` with the CSRF header ends the session on the server (the old cookies get a 401
  afterwards);
- a successful DELETE answers with an empty body.

## Still open

The automated tests run against a fake Jama (`tests/fake_jama.py`) that reproduces the
behaviour above. Not known yet:

- whether the logout frees the floating license seat at once (only visible to a Jama admin on
  the license page);
- whether Jama replaces the CSRF token or `JSESSIONID` during a long session. The client takes
  over such a change if it arrives as `Set-Cookie`; whether a CSRF rejection carries the new
  token is not known, so the fake covers both cases;
- how long Jama's idle timeout is.
