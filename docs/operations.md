# Operations

## Install

Copy the plugin into the plugins directory:

```
C:\Users\ADMIN\.minimax\plugins\capability-router\
```

mcode discovers plugins there and enables them by default. Check with:

```sh
mcode plugin list
```

It should show:

```
[*] capability-router@local	enabled
```

Nothing else needs to be configured. The hook registers itself through the
plugin manifest.

## Build the catalog

The catalog is what makes slash routing work. Build it once, and again after
any skill is added, renamed or removed.

```sh
python "%USERPROFILE%\.minimax\plugins\capability-router\scripts\build_catalog.py"
```

It prints a summary and writes two files:

```
catalog   C:\Users\ADMIN\.routing\catalog.json
records   372  {'skill': 321, 'connector': 17, 'cli': 18, 'mcp_tool': 16}
merged    1095 identical copies, 38 mirrored variants
collided  7 disambiguated slugs
reserved  0 builtin names excluded
elapsed   26380 ms
```

`catalog-report.json` next to it lists every merge, every collision and every
excluded name. Read it after a build. The collisions are where the interesting
problems show up.

Useful flags:

```sh
build_catalog.py --no-mcp          # skip probing MCP servers
build_catalog.py --no-connectors   # skip the connector tool list
build_catalog.py --no-cli          # skip the gws service list
build_catalog.py --out other.json  # write somewhere else
```

The MCP probe spawns each stdio server and speaks JSON-RPC to it. That is why
the build takes about 25 seconds: it also scans 1454 `SKILL.md` files across
four roots.

## Run the tests

```sh
python "%USERPROFILE%\.minimax\plugins\capability-router\scripts\test_router.py"
```

35 checks. They run the router as a real subprocess, so the contract being
tested is the one the hook uses: JSON payload on stdin, injected context on
stdout.

## Inspect what the router is doing

The usage log is the record of every prompt the router saw:

```sh
Get-Content "$env:USERPROFILE\.routing\usage.jsonl" -Tail 20
```

Every line has a `path`:

| `path` | Meaning |
|---|---|
| `slash` | the prompt started with `/` |
| `static` | a pinned rule fired |
| `learned` | a learned rule fired |
| `correction` | the router learned something, and stayed silent |
| `confirmation` | confidence went up, and the router stayed silent |
| `rephrase` | the last route was probably wrong |
| `none` | nothing matched |

If a rule is not firing when you expect, this file will say why the router
walked past it.

## Tune it

### Learned rules

`~/.routing/routes.learned.json`. Editable, though the router will overwrite
confidence values on the next turn.

```json
{
  "version": 1,
  "rules": [
    {
      "slug": "gws-gmail",
      "pattern": ["gmail", "inbox", "invoice"],
      "confidence": 0.6,
      "hits": 4,
      "confirms": 1,
      "misses": 0,
      "created": 1793825000,
      "last_confirmed": 1793825000
    }
  ]
}
```

### Pinned rules

`~/.routing/routes.static.json`. The router reads this and never writes it.

```json
{
  "version": 1,
  "rules": [
    {
      "slug": "gws-gmail",
      "keywords": ["gmail", "inbox", "email", "mailbox"],
      "require": 1
    }
  ]
}
```

`require` is how many of the keywords must appear. Default 1. A pinned rule
fires whenever its keywords are there, and it outranks a learned rule.

To pin a skill that is marked `disable-model-invocation: true`, name it here.
Pinned rules are the user's explicit instruction, so they are allowed to reach
slash-only skills. The learned path is not.

## Troubleshoot

### A slash command does nothing

Check the slug exists:

```sh
python -c "import json;c=json.load(open(r'C:\Users\ADMIN\.routing\catalog.json',encoding='utf-8'));print('wa-read-messages' in c['records'])"
```

If it is missing, rebuild the catalog. If it is present, the hook is probably
not running. Check `mcode plugin list` shows the plugin enabled, and look for
the hook in `usage.jsonl` with `path: "slash"`.

### The hook produces no output at all

The most likely cause is the one in
[bugs-found.md](bugs-found.md), bug 1: a payload that fails to parse is
treated as an empty prompt and the router exits cleanly.

Test the launcher directly:

```sh
$payload = @{hook_event_name='UserPromptSubmit'; session_id='t'; cwd='C:\Users\ADMIN'; prompt='/ponytail'} | ConvertTo-Json -Compress
$payload | & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\Users\ADMIN\.minimax\plugins\capability-router\scripts\router.ps1"
```

Expected: `The user invoked the command. Load the `ponytail` skill and follow it.`

If that works, the hook is not being invoked. If it does not, the launcher or
the router is at fault.

### The router injects something on every turn

Check for a pinned rule that matches too much. `routes.static.json` with a
single-word keyword like `email` will fire on every prompt that mentions
email. Narrow the keywords.

### A learned rule fires on the wrong prompts

Lower the confidence, or narrow the pattern:

```json
"pattern": ["invoice", "receipt"]
```

A pattern with more specific words needs more of them present, so it fires
less often. `MATCH_THRESHOLD` is 0.60: at least 60 percent of the pattern
words must be in the prompt.

### A learned rule never fires

Check three things: the confidence is at or above 0.50, the slug is still in
the catalog, and the pattern words are actually in the prompt. The usage log
shows the tokens the router saw for the last prompt, which is usually enough
to spot the mismatch.

## Extend it

### A new capability source

Add a `collect_*` function to `build_catalog.py` returning records with
`slug`, `kind`, `title`, `description`, `auto_routable`, `source` and `hash`.
Register it in `main`. The collision resolver handles the rest.

Kinds: `skill`, `mcp_tool`, `connector`, `cli`. A `cli` record can carry a
`command` field, and the injected line becomes `Run: <command>`.

### A new automatic path

Add it to `router.py`. Keep the order: slash, then correction, confirmation
and rephrase, then static, then learned. Put any new path after the
correction handling, or the router will answer a correction with a suggestion.

### Another runtime

The router core is one Python file with no dependency on mcode. A runtime that
can spawn a process, write JSON to its stdin and read its stdout can use it.

Two things to keep:

- Read stdin as bytes and decode UTF-8. Text mode will corrupt it on Windows.
- Point it at the same `~/.routing/`, and a rule learned in one runtime works
  in the other.

## The local hook layer

Two more user scope hooks live in `C:\Users\ADMIN\`, alongside the caveman,
diagram and WhatsApp hooks:

| Hook | Event | What it injects |
|---|---|---|
| `session-bootstrap-hook.ps1` | `SessionStart` | The token toolkit and the shipping discipline |
| `linkedin-hook.ps1` | `UserPromptSubmit` | The `cli-anything-linkedin` command surface |

`hooks.json` is the registration point for all of them.

### The commandcode CLI

The CLI reads a different settings file, so it needs its own registration
entry. Add this to `%USERPROFILE%\.commandcode\settings.json`, alongside the
existing `PostToolUse` hook:

```json
"UserPromptSubmit": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "python \"C:\\Users\\ADMIN\\.minimax\\plugins\\capability-router\\scripts\\router.py\"",
        "commandWindows": "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"C:\\Users\\ADMIN\\.minimax\\plugins\\capability-router\\scripts\\router.ps1\"",
        "timeout": 5
      }
    ]
  }
]
```

This entry is documented, not applied. mcode cannot edit that file.

Both runtimes read the same `~/.routing/`, so a rule learned in one works in
the other. A rule only needs to be written once.

## Cost

| Item | Value |
|---|---|
| Permanent context | 0 tokens |
| Injected line | about 25 tokens, on a firing turn only |
| Hook latency | about 290 ms, including process start |
| Catalog rebuild | about 26 seconds, manual |
| Files in `~/.routing/` | about 200 KB total |
