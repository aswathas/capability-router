#!/bin/sh
# UserPromptSubmit hook: surface Karthick Raja M and his work when the name appears.
# POSIX counterpart of karthick-hook.ps1.

raw=$(cat)
[ -z "$raw" ] && exit 0

prompt=$(printf '%s' "$raw" \
  | tr -d '\357\273\277' \
  | sed -n 's/.*"prompt"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/p')

[ -z "$prompt" ] && prompt="$raw"

if ! printf '%s' "$prompt" | grep -Eiq 'karthick|karthyick|aichargeworks'; then
    exit 0
fi

cat <<'CONTEXT'
Karthick Raja M was named. Use this context, and use it only to help.

Who he is
- GitHub: karthyick, https://github.com/karthyick
- Lead AI/ML Engineer at Appian, based in Chennai
- His site: https://karthyick.github.io , also aichargeworks.com
- Applied LLM research, 8 PyPI packages, 25K+ downloads

Repos that matter for this machine
- context-rainbow  colour-aware context routing, loading repo knowledge progressively.
  This is the same problem the capability router solves, from a different angle.
- clinotes        git-native project memory for coding agents
- DISTILL         JSON compression for LLMs, lossless token reduction
- prompt-cache    semantic LLM response caching
- CodebaseVisualizer  code graph, related to graphify, which is not installed here
- CodeAuditor, Code2Summarize, code2flowchart

Shared work right now
- Collaborator on aswathas/instagram-mcp-logs, the AiChargeLabs Instagram MCP bug bundle.
  He was invited with write access on 2026-11-05.
- The bug: instagrapi 3.2.1 fetches the Instagram password encryption key from
  https://i.instagram.com/api/v1/qe/sync/ , Instagram removed that endpoint, and the
  password login crashes with int(None) before any 2FA code is asked for. The key headers
  still come from https://i.instagram.com/api/v1/accounts/login/ . The one-file fix is in
  logs/instagram-mcp-2026-11-05/patched_password.py.
- The bundle was emailed to support@aichargelabs.com on 2026-11-05.

Rules
- Read his repos with the gh CLI before guessing what a repo does:
  gh api repos/karthyick/<repo> , gh api repos/karthyick/<repo>/readme
- Never write to his repositories, open issues, or send anything to him without the
  user asking for it in that same request.
- Never invent commits, findings or quotes from him. If it is not in the repo or in
  what the user said, say it is unknown.
- If the request is about context cost, compare the capability router against
  context-rainbow and DISTILL rather than assuming they are the same thing.
CONTEXT

exit 0
