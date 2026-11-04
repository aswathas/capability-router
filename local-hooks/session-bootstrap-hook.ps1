# SessionStart hook: inject the session toolkit and the shipping discipline.
#
# Runs once per session, not once per turn, so the block is kept small. It
# injects context only. It never calls a tool.
#
# ASCII source is intentional: Windows PowerShell 5.1 reads it without a BOM.
$ErrorActionPreference = 'Stop'

try {
    $graphify = Get-Command graphify -ErrorAction SilentlyContinue
    $graphifyLine = if ($graphify) {
        "- graphify is installed at $($graphify.Source). Use it before hand building a graph."
    } else {
        "- graphify is not installed on this machine. If it appears later, use it before hand building a graph."
    }

    $context = @"
Session toolkit (auto-injected).

Token discipline
- Shell output goes through rtk, never through the raw command: rtk read, rtk grep, rtk ls,
  rtk tree, rtk git, rtk gh, rtk diff, rtk log, rtk test, rtk json, rtk deps, rtk wc.
  Raw command output is the largest context waste on this machine.
- rtk smart <file> returns a 2-line summary. Read a file fully only when the summary is not enough.
- /context shows the runtime-owned context snapshot. Check it before dumping anything large.
- /compact shortens the active conversation when it grows long.

Capability routing
- The capability-router plugin resolves /name for any skill, MCP tool, connector tool or CLI
  service. 372 capabilities are catalogued. Use it instead of guessing a name.
- A pinned rule in ~/.routing/routes.static.json always wins over a learned one.
$graphifyLine

Shipping discipline
- When a task finishes: write the documentation, commit it, push it to GitHub. Public repo
  unless the user says otherwise. A finished task that is not committed is a lost task.
- Use a separate git worktree only when the task needs an isolated checkout. Not by default.
- Capture the returned urn or id when a create call returns one. Some of them exist nowhere else.
"@
    Write-Output $context
    exit 0
}
catch {
    exit 0
}
