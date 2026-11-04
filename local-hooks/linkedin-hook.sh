#!/bin/sh
# UserPromptSubmit hook: route LinkedIn requests to the cli-anything-linkedin CLI.
# POSIX counterpart of linkedin-hook.ps1.

raw=$(cat)
[ -z "$raw" ] && exit 0

prompt=$(printf '%s' "$raw" \
  | tr -d '\357\273\277' \
  | sed -n 's/.*"prompt"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/p')

[ -z "$prompt" ] && prompt="$raw"

if ! printf '%s' "$prompt" | grep -Eiq 'linkedin|linked[[:space:]_-]in[[:space:]]+(post|profile|feed|page|account|group|message|network|connections?)'; then
    exit 0
fi

cat <<'CONTEXT'
LinkedIn request detected. Use the cli-anything-linkedin CLI.

cli-anything-linkedin is the tool. It wraps LinkedIn's official Posts API and sends
credentials only to api.linkedin.com. Do not use browser automation, do not scrape
cookies, and do not route this through a third-party service.

Binary: C:\Users\ADMIN\AppData\Local\Programs\Python\Python313\Scripts\cli-anything-linkedin.exe
Always pass --json. Success is {"ok": true, ...}. Failure is {"ok": false, "error": {...}}
with exit code 1.

Check access first
   cli-anything-linkedin --json auth status --verify
   If it is not authenticated, tell the user to run "cli-anything-linkedin auth login
   --port 8085". That opens a browser and the user has to approve. Never authenticate
   for them and never put a token on a command line.

Writing a post
   cli-anything-linkedin --json post create -f draft.md
   Use -f for anything multi-line; shell quoting mangles apostrophes.
   cli-anything-linkedin --json post create -t "short post"
   cli-anything-linkedin --json post create -f draft.md -v CONNECTIONS
   Visibility: PUBLIC (default), CONNECTIONS, or LOGGED_IN.
   Use --dry-run first on an unfamiliar payload. It prints the exact method, path, body.
   Capture the returned urn. It exists only in the x-restli-id response header, and
   LinkedIn will not let you read member posts back, so that urn is the only handle.

Editing and deleting
   cli-anything-linkedin --json post edit <urn> -f corrected.md
   Editing is commentary-only. Images, author and visibility are immutable. To change
   those, delete and repost.
   cli-anything-linkedin --json post delete <urn> --yes
   Never delete without an explicit request that names the post and the --yes flag.
   There is no restore endpoint. Use session undo for a reversible edit instead.

Drafts, schedule and voice
   cli-anything-linkedin --json draft list --status
   cli-anything-linkedin --json draft save -f draft.md
   cli-anything-linkedin --json schedule add <draft-id> --at <ISO>
   cli-anything-linkedin --json schedule run --limit 10
   cli-anything-linkedin --json voice show
   cli-anything-linkedin --json content generate -T "topic" -F build-log --save
   Formats: hook-story-lesson, contrarian, listicle, case-study, build-log.
   The voice profile lives in ~/.config/cli-anything-linkedin/voice.toml and drives the
   tone, the pillars and the banned phrases. Read it before writing, so the post sounds
   like the user and not like a template.

Rules
- Write the post first, show the user the exact text, and only post after they approve.
- 3000 characters per post. 150 API requests per day. Tokens expire after 60 days.
- Not possible through any API: comments, reactions, analytics, DMs, reading your own
  post history from LinkedIn. Do not attempt a workaround.
- postiee covers the parts this CLI does not: media uploads and local post history
  search. Use it only when the request needs those.
CONTEXT

exit 0
