# Instagram publishing

How a carousel was measured, rendered, and posted with the AiChargeLabs Instagram
MCP, and what had to be true before the first post could happen.

This is the write-up of a side quest that turned into a systems problem: the
product was already installed, licensed, and running. It still could not post,
because it had no session, and the only documented way to get one is a CLI that
was not installed.

## The product

`aichargelabs-instagram-mcp` is a closed-source MCP server for Instagram. It
ships 35 tools: read and search DMs, triage and draft replies, send messages and
media, publish posts, reels and stories, handle comments, manage the account,
follow and block, and read highlights and notes.

| Piece | What it is |
|---|---|
| `instagram-mcp.exe` | The MCP server, the command line, and the Instagram login. One program. |
| `everyhand-daemon.exe` | The shared local service. One port for every Everyhand product. |
| `ig-daemon.exe` | The Instagram service when Instagram runs on its own. |

The session is encrypted on the machine with Windows DPAPI. Nothing goes
through an AiChargeLabs cloud except the licence check.

## Install

The package is not on public PyPI. It is on the vendor's own index:

```
pip install aichargelabs-instagram-mcp --index-url https://aichargelabs.com/pip/simple/
```

Two things bite on Windows.

**The daemon holds the files.** Installing the package replaces the shared
runtime, and a running `everyhand-daemon.exe` locks its own files. Windows
refuses the write with `Access is denied` on a `.pyd`. Stop it first:

```
whatsapp-mcp daemon stop --all
```

**The install rolls back halfway.** When the write fails, pip moves the old
package aside into a `~name` directory and cannot move it back. The next
install then fails on the leftover. Delete the leftover directory before
retrying.

## Login

```
instagram-mcp.exe login --username <handle>
```

The password is asked on screen and hidden. A two-factor code is asked when the
account uses 2FA. The password is not kept unless `--remember` is passed.

`login` without `--username` fails with `--username required (or
--sessionid-env)`. There is no interactive prompt for the handle, so a helper
that asks for it first is needed if the handle is not already known.

If Instagram answers with a challenge, approve it in the Instagram app and run
`instagram-mcp.exe login --check`.

The session lands in `%APPDATA%\instagram-mcp\`, encrypted with DPAPI. It
cannot be copied to another machine.

## Publish

```
POST /ig/publish
{"kind": "album", "caption": "...", "paths": [".../slide-01.png", ...]}
```

Kinds: `photo`, `album`, `video`, `reel`, `story_photo`, `story_video`. An
album needs between 2 and 10 paths.

Upload paths must live in one of: the Everyhand media store, the temp folder,
Pictures, Videos, Downloads, Desktop, Music, or a folder listed in
`IG_UPLOAD_DIRS`. Anything else is refused and written to the audit log as
`blocked_path`.

**Publishing is gated.** The first call does not publish. It returns
`needs_confirm: true`, `confirm_mode: "code"`, `expires_in_s: 360`, and a six
digit code is shown on the account owner's screen as a Windows notification.
Repeating the same call with `confirm: <code>` completes it.

The code is in no reply and no file. It cannot be read by the assistant and it
must never be guessed. Four wrong attempts lock the request.

Limits: 3 publishes a minute, 10 an hour, 25 a day.

## The local API surface

The daemon serves the product over loopback HTTP on one port, and it uses two
different token realms. Getting this wrong looks like a missing route.

| Header | Realm | Works on |
|---|---|---|
| `x-ig-token` | product engine | `/ig/*` |
| `x-everyhand-token` | shared daemon | `/health` |

The engine token is `%APPDATA%\everyhand\store\daemon.token`. With the wrong
header every route answers `401 bad token`, which reads like an auth problem
instead of a header-name problem. With the right header and a wrong path the
answer is `404 no such route`. That difference is the only reliable way to
tell the two apart.

Routes that exist on the product engine, discovered by probing:

| Route | Method | What it wants |
|---|---|---|
| `/ig/status` | GET | connection state, licence, limits |
| `/ig/health` | GET | daemon pid, version, connection |
| `/ig/license` | GET | licence state |
| `/ig/threads` | GET | the inbox |
| `/ig/thread` | GET, POST | one chat, or mute/hide/title/leave |
| `/ig/messages` | GET | messages in a chat |
| `/ig/search` | GET | `?query=` |
| `/ig/user` | GET | `?username=` or `?user_id=` |
| `/ig/profile` | GET, POST | a profile, by thread id |
| `/ig/comments` | POST | `url`, `code`, `media_id` or `media_pk` |
| `/ig/stories` | POST | stories |
| `/ig/send` | POST | `text` required |
| `/ig/publish` | POST | `kind` required |
| `/ig/account` | POST | account state |

There is **no login route**. Login is a CLI command and nothing else. Every
other route answers `503 not connected (state=logged_out)` until a session
exists.

## The carousel pipeline

Two scripts, both in `content/instagram/`.

`build_carousel.py` renders eight slides at 1080x1350 with Playwright and
Chromium, then writes the caption and a `deck.html` next to them.

**No number in the carousel is typed by hand.** The slide text is read from
`scripts/measure_context.py`, which counts the real prompt cost of the running
setup with `tiktoken` and the `cl100k_base` encoding. If the token counts move,
the slides move with them. The deck cannot drift from the measurement.

`publish_instagram.py` drives the publish call:

```
python publish_instagram.py --status       # connection, licence, limits
python publish_instagram.py --caption-only  # print the caption, publish nothing
python publish_instagram.py                 # publish, print the confirm preview
python publish_instagram.py --confirm <code> # finish a gated publish
```

## Files

| File | Purpose |
|---|---|
| `content/instagram/build_carousel.py` | renders the 8 slides, the caption and the deck |
| `content/instagram/publish_instagram.py` | status, publish and confirm against the local daemon |
| `scripts/measure_context.py` | the token ledger every number comes from |

Output goes to `%USERPROFILE%\Pictures\capability-router-carousel\`.

## What failed, and why

| Attempt | Result | Cause |
|---|---|---|
| `pip install aichargelabs-instagram-mcp` | no matching distribution | the package is not on public PyPI, it needs the vendor index |
| `POST /hub/install` on the daemon | 401 | there is no install route on the daemon, products come from pip |
| `eh-host.exe --help` | empty output | it is an engine host, it needs a handshake from the daemon on stdin |
| searching for `instagram-mcp.exe` on disk | nothing | the product was never installed, only its packaged engine was in the hub |
| probing `/ig/login`, `/ig/session`, ... | 404 | login is a CLI command, not an HTTP route |
| pip install while the daemon ran | `Access is denied` on a `.pyd` | the running daemon locks its own files |
