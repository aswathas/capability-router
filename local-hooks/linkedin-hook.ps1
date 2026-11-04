# UserPromptSubmit hook: route LinkedIn requests to the cli-anything-linkedin CLI.
#
# Read-only apart from a capped debug log next to this script. Reads the prompt
# JSON on stdin, and when the prompt mentions LinkedIn, prints a context block
# on stdout so the agent reaches for the CLI instead of guessing. Prints nothing
# otherwise. No network.
#
# ASCII source is intentional: Windows PowerShell 5.1 reads it without a BOM.
$ErrorActionPreference = 'Stop'

$LogFile = 'C:\Users\ADMIN\.minimax\hook-debug.log'
$MaxLogLines = 300

function Write-DebugLine([string]$line) {
    try {
        Add-Content -LiteralPath $LogFile -Value $line -Encoding ASCII -ErrorAction Stop
        $all = @(Get-Content -LiteralPath $LogFile -ErrorAction SilentlyContinue)
        if ($all.Count -gt $MaxLogLines) {
            Set-Content -LiteralPath $LogFile -Value $all[($all.Count - $MaxLogLines)..($all.Count - 1)] -Encoding ASCII -ErrorAction SilentlyContinue
        }
    }
    catch {
        # A failed log write must never break the hook.
    }
}

try {
    $raw = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }

    # Some launchers hand stdin over with a UTF-8 BOM; ConvertFrom-Json rejects it.
    $raw = $raw.TrimStart([char[]]@([char]0xFEFF, ' ', "`t", "`r", "`n"))

    $prompt = ''
    $event = ''
    try {
        $obj = $raw | ConvertFrom-Json
        if ($obj.PSObject.Properties.Name -contains 'prompt') { $prompt = [string]$obj.prompt }
        if ($obj.PSObject.Properties.Name -contains 'hook_event_name') { $event = [string]$obj.hook_event_name }
    }
    catch {
        # Unparseable payload: the prompt text is still in there literally, and the
        # trigger words are plain ASCII, so scanning the raw text is a safe fallback.
        $prompt = $raw
    }
    if ([string]::IsNullOrWhiteSpace($prompt)) { exit 0 }

    $patterns = @(
        # the product name itself, one word
        '(?i)\blinkedin\b',
        # "LinkedIn post", "linked in profile", "linkedin feed"
        '(?i)\blinked[\s\-]in\s+(?:posts?|profiles?|feed|pages?|accounts?|groups?|messages?|network|presence|connections?)\b',
        # an explicit posting verb pointed at LinkedIn
        '(?i)\b(?:post|publish|share|schedule|cross[\s\-]?post)\b[^.\n]{0,30}?\b(?:to|on|for)\s+linked[\s\-_]?in\b'
    )

    $hit = $false
    $matched = ''
    foreach ($pattern in $patterns) {
        if ($prompt -match $pattern) { $hit = $true; $matched = $pattern; break }
    }

    $snippet = ($prompt -replace '\s+', ' ').Trim()
    if ($snippet.Length -gt 120) { $snippet = $snippet.Substring(0, 120) }
    Write-DebugLine ("{0} | hook=linkedin | event={1} | fired={2} | match={3} | prompt='{4}'" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $event, $hit, $matched, $snippet)

    if (-not $hit) { exit 0 }

    $context = @'
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
- Always attach the project link as a P.S. line at the end of every post. The user asks for this
  on every single post, so do not leave it out.
- 3000 characters per post. 150 API requests per day. Tokens expire after 60 days.
- Not possible through any API: comments, reactions, analytics, DMs, reading your own
  post history from LinkedIn. Do not attempt a workaround.
- postiee covers the parts this CLI does not: media uploads and local post history
  search. Use it only when the request needs those.
'@
    Write-Output $context
    exit 0
}
catch {
    exit 0
}
