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

For each request, on a session-rejected response (401 without "permission" in `meta.message`,
or a 3xx whose `Location` contains `/login`, `/saml` or `j_acegi`), each step at most once:

1. Non-GET only: one authenticated GET (`users/current`); take `jama-csrf-token` from its
   `Set-Cookie` (else from the cookie already held), update header and cookie, save, retry.
2. Re-read the store. If it holds a different session than the one that just failed, retry
   with it.
3. Take the lock and re-read the store. If it now holds a different session and that one passes
   the probe, use it. Otherwise log in (respecting `login_interactive`), save, retry.
4. Still rejected: `UnauthorizedException` telling the user to run `jama login`.

A 401 that mentions "permission" is returned to the caller immediately.

One deliberate deviation from a literal reading of the sequence: if the GET in step 1 succeeds,
the session is proven alive, so the result of the retried write is final and steps 2 and 3 are
skipped. Logging in again could not fix a write that a live session with a fresh token cannot
perform, and it would cost the user an interactive login.

## Login

The only success criterion is the authenticated probe (`GET rest/v1/users/current`, falling
back to `projects?maxResults=1`), with manual redirects. Browser mode polls it every 500 ms with
the cookies of the browser context, ignores the landing URL, and tolerates page and context
errors during the SAML redirect chain. Headless is tried first when a browser profile exists;
a visible login form, or 20 s without a session, switches to a visible window.

## Reusing the browser's session (`--from-browser`)

`session_source` (`firefox` | `chrome` | `edge`) replaces the login with reading the two Jama
cookies (`JSESSIONID`, `jama-csrf-token`) the user's own browser already holds for the configured
host. The result is validated with the same `probe()` and stored like any other session. This
avoids a second session on one-session-per-account instances, where the CLI's own login and the
user's browser session would otherwise evict each other.

It is wired as a `login_func`, so it feeds `SessionManager.login()` and `recover()` alike: a truly
dead session (not the CSRF case) is re-read from the browser instead of an interactive login, and
being non-interactive it honours `login_interactive: never`. Signing out in the browser ends the
shared session for the CLI too, by design.

Runtime target is "CLI/MCP under WSL, browser on the Windows host"; cookie stores are read from
`/mnt/c/Users/<windows-user>/...`, with the Windows user resolved via `cmd.exe`, not guessed. The
live, locked cookie database is never opened in place: it is copied with its `-wal`/`-shm`
sidecars to a temp file, opened read-only, and deleted afterwards. Only the two cookies, only for
the configured host, are read; values are never logged or raised.

- Firefox stores values in clear text (`moz_cookies`), so everything runs inside WSL.
- Chrome/Edge encrypt the values and, since v127, bind the key to the Windows user (App-Bound
  Encryption). Python reads the encrypted blobs and the wrapped key from the copied database and
  `Local State`, then hands them to a bundled PowerShell helper
  (`jama_cli/core/jama_read_chrome_cookies.ps1`, fed on stdin so no Windows path is translated).
  The helper runs as the user, DPAPI-unwraps the key and AES-GCM-decrypts the two values (v10),
  and prints only those values as JSON. App-Bound (v20) blobs are not unwrapped; the helper fails
  with a clear message and the CLI stops rather than silently logging in again. The helper
  contract (base64 blobs in, two values out) is mocked in the tests.

## Not verified against a real Jama instance

Everything above was tested against a fake Jama built from the stated facts
(`tests/fake_jama.py`), not against a real instance. To check on the real one:

- that `rest/v1` accepts the web session cookies plus the `jama-csrf-token` header;
- the SSO button selectors and the login page path `login.req`;
- that `JSESSIONID` stays valid when used from outside the browser (some setups bind sessions
  to a client IP or user agent);
- how a dead session really looks (401 message text, redirect targets);
- that `logout.req` with the CSRF header releases the seat.
