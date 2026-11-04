# UserPromptSubmit hook: surface Karthick Raja M and his work when the name appears.
#
# Read-only apart from a capped debug log next to this script. Reads the prompt
# JSON on stdin, and when the prompt names Karthick, prints a context block on
# stdout. Prints nothing otherwise. No network.
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
        # trigger word is plain ASCII, so scanning the raw text is a safe fallback.
        $prompt = $raw
    }
    if ([string]::IsNullOrWhiteSpace($prompt)) { exit 0 }

    $patterns = @(
        '(?i)\bkarthick\b',
        '(?i)\bkarthick\s+raja\b',
        '(?i)\bkarthyick\b',
        '(?i)\bkarthick\.github\.io\b',
        '(?i)\baichargeworks\b'
    )

    $hit = $false
    $matched = ''
    foreach ($pattern in $patterns) {
        if ($prompt -match $pattern) { $hit = $true; $matched = $pattern; break }
    }

    $snippet = ($prompt -replace '\s+', ' ').Trim()
    if ($snippet.Length -gt 120) { $snippet = $snippet.Substring(0, 120) }
    Write-DebugLine ("{0} | hook=karthick | event={1} | fired={2} | match={3} | prompt='{4}'" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $event, $hit, $matched, $snippet)

    if (-not $hit) { exit 0 }

    $context = @'
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
'@
    Write-Output $context
    exit 0
}
catch {
    exit 0
}
