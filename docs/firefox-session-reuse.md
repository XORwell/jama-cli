# Reuse a Firefox session

Set up [browser session login](../README.md#browser-session-login-sso) before using this option.

By default `login` opens its own browser profile, which is a **second** Jama session. If your
instance allows only one session per account, that second login and your real browser session
evict each other, so you cannot browse and use the CLI/MCP server at the same time.

`--from-browser` avoids that: it reads the Jama session cookies Firefox already has and
reuses them, so browser, CLI and MCP server share **one** session. No second login, nothing is
evicted.

```bash
jama login --from-browser firefox     # read the session from Firefox
# optional: a non-default Firefox profile, or an explicit cookie-store path
jama login --from-browser firefox --browser-cookie-profile "abcd1234.default-release"
jama login --from-browser firefox --browser-cookies-path "<dir with profiles.ini>"
```

`--from-browser` applies to that one call. The stored session remembers that it came from
Firefox, so when it later ends, every process using it (other terminals, the MCP server)
reads Firefox again instead of logging in on its own, whatever its own settings say. To
make *every* login go through Firefox, including the first one and after `jama logout`, set
`session_source: firefox` in the profile or `JAMA_SESSION_SOURCE=firefox` in the
environment, also in the `env` block of the MCP server. Reading the browser is
non-interactive, so it works with `login_interactive: never`. Sign in to Jama in Firefox first; if
you sign out there, the shared session ends for the CLI too (that coupling is the point).

**Where Firefox is looked for.** Windows: `%APPDATA%\Mozilla\Firefox`. macOS:
`~/Library/Application Support/Firefox`. Linux: `~/.mozilla/firefox`, `~/.config/mozilla/firefox`,
Snap (`~/snap/firefox/common/.mozilla/firefox`) and Flatpak
(`~/.var/app/org.mozilla.firefox/.mozilla/firefox`). In WSL the Windows host's Firefox and a
Firefox inside WSL are both considered; with several installs the most recently used profile wins.
For the Windows side the Windows user is asked of Windows (`cmd.exe`, also when Windows is not on
`PATH`), not guessed, and the drives are located through `/proc/mounts`, so a custom automount
root in `/etc/wsl.conf` works. With interop off, the single Windows user that has a Firefox
profile is used; with several, none is picked. `--browser-cookies-path` overrides all of this.

**Where the cookies are.** Jama's `JSESSIONID` and `jama-csrf-token` are session cookies, and
Firefox never writes session cookies to `cookies.sqlite`. While Firefox runs they are only in its
session store, `sessionstore-backups/recovery.jsonlz4`, which Firefox rewrites about every 15
seconds. So right after signing in to Jama, wait a few seconds before `jama login --from-browser
firefox`. Private windows, containers and partitioned cookies are ignored. Only the two Jama
cookies, and only for your configured host, are ever read; copies of locked files are deleted
right after reading. Firefox keeps cookie values in clear text, so no decryption and no Windows
component is involved.

**Logout.** A session taken over from Firefox *is* your browser's session. `jama logout` therefore
only removes the stored copy and tells you so ("Removed the stored session; your browser session
is still active"). `jama logout --end-server-session` really ends it on the server, which also
signs you out in the browser. `jama status` shows where the stored session came from (`source`).

**Only Firefox is supported.** Chrome and Edge (version 127 and later) bind the cookie key to
the Windows user with App-Bound Encryption. Getting around that from outside the browser is what
credential-stealing malware does, and endpoint security treats it that way, so this tool does not
attempt it. `--from-browser chrome` or `edge` stops with an error and does **not** fall back to a
fresh login (which would evict your browser session). Use Firefox, or plain `jama login`.

> Reading another application's browser cookies may be restricted by your company policy or
> flagged by endpoint security. And, as with any session reuse, confirm with your Jama admin that
> reusing a web session for REST is allowed on your instance.

For MCP, `logout_session` also removes only the stored copy unless `end_server_session` is true.

## Settings

Environment variables override the profile.

| Profile key | Environment variable | Default | Meaning |
|---|---|---|---|
| `session_source` | `JAMA_SESSION_SOURCE` | off (log in) | Reuse the browser's session: `firefox` |
| `browser_cookie_profile` | `JAMA_BROWSER_COOKIE_PROFILE` | main profile | Browser profile to read cookies from |
| `browser_cookies_path` | `JAMA_BROWSER_COOKIES_PATH` | auto-detected | Path to Firefox's `cookies.sqlite` or the directory with `profiles.ini` |
