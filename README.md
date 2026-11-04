# Capability Router

Routes a prompt to the right capability: a skill, an MCP tool, a connector tool,
or a CLI service. It resolves slash commands exactly, applies rules you pinned,
and learns the routes you correct it on.

It is a **hook**, not an MCP server. That is deliberate:

- An MCP server sends its tool schemas on every request. That is permanent
  context cost, roughly 120 tokens per turn, forever.
- A hook sends nothing. Its stdout enters the context only on a turn where it
  actually fires, and it is about 25 tokens then.

Permanent context cost of this plugin: **zero**.

## Numbers

| | |
|---|---|
| Capabilities catalogued | 372 (321 skills, 16 MCP tools, 17 connector tools, 18 CLI services) |
| Permanent context cost | 0 tokens |
| Injected line | about 25 tokens, only on a firing turn |
| Hook latency | about 290 ms, including process start |
| Regression checks | 35, all passing |
| Bugs found and fixed during the build | 6, including one that failed silently |

Write-up published on LinkedIn:
[1,454 SKILL.md files, 372 capabilities, 0 tokens of permanent context](https://www.linkedin.com/feed/update/urn:li:share:7523850680181342208/)

## Documentation

Full documentation, written from scratch, is in [docs/](docs/README.md).

| Document | What it answers |
|---|---|
| [architecture.md](docs/architecture.md) | What it is, how it routes, what it costs. |
| [runtime-research.md](docs/runtime-research.md) | What was reverse engineered from the agent runtime before any code was written. |
| [build-log.md](docs/build-log.md) | The chronological build: decisions, dead ends, what changed. |
| [bugs-found.md](docs/bugs-found.md) | The six bugs, with symptom, cause, and how each was caught. |
| [antifragility.md](docs/antifragility.md) | The four guards and the confidence arithmetic. |
| [operations.md](docs/operations.md) | Install, rebuild, troubleshoot, extend, port. |
| [testing.md](docs/testing.md) | The suite, what it covers, what it does not. |
| [appendix-whatsapp-mcp.md](docs/appendix-whatsapp-mcp.md) | The case study that came first: a daemon that would not start. |
| [instagram-publishing.md](docs/instagram-publishing.md) | How the carousel was measured, rendered and posted, and what the Instagram MCP needed before the first post. |

The original design spec, written before any code, is at
[docs/superpowers/specs/](docs/superpowers/specs/2026-11-05-capability-router-design.md).
Its "Implementation notes" section records every place the build proved the
design wrong, which is the most useful part of the project.

## What it does

| Trigger | What happens |
|---|---|
| Prompt starts with `/` | Exact slug lookup. The argument is passed through. Valid argument values are listed. |
| A pinned rule matches | The pinned capability is injected. Pinned rules outrank learned ones. |
| A learned rule matches | The learned capability is injected. Only routes the user confirmed can fire. |
| The prompt corrects the last route | The router learns the new route and lowers the old one. |
| The prompt confirms the last route | Confidence in that route goes up. |
| Anything else | Nothing. The turn is untouched. |

The router never calls a tool. It only tells the agent which capability to use.
It never touches `ai_enabled`, a permission, or a send gate.

## Files

```
.minimax/plugins/capability-router/
  .minimax-plugin/plugin.json     manifest, hooks only, no MCP server
  hooks/router.json               one UserPromptSubmit hook
  scripts/router.py               the router. One implementation.
  scripts/router.ps1              Windows launcher, passes stdin through
  scripts/router.sh               POSIX launcher, passes stdin through
  scripts/build_catalog.py        rebuilds the catalog
  scripts/test_router.py          regression tests
  scripts/measure_context.py      measures what the setup costs in prompt tokens
  content/instagram/              carousel build and publish scripts
  docs/superpowers/specs/         the design spec
```

The launchers are thin. They hand the hook payload to `router.py` untouched, so
the Windows path and the POSIX path cannot drift apart.

## Data

Everything lives in `~/.routing/`, shared by mcode and the commandcode CLI.

| File | Who writes it | What it holds |
|---|---|---|
| `catalog.json` | `build_catalog.py` | one record per capability |
| `catalog-report.json` | `build_catalog.py` | what was merged, what collided, what was excluded |
| `routes.static.json` | **you** | pinned rules. The router never edits this. |
| `routes.learned.json` | the router | learned rules with a confidence score |
| `usage.jsonl` | the router | append-only log, capped at 2000 lines |
| `quarantine.json` | the router | rules whose target no longer exists |

## Pinned rules

`~/.routing/routes.static.json`. Write it once, it applies everywhere.

```json
{
  "version": 1,
  "rules": [
    {
      "slug": "gws-gmail",
      "keywords": ["gmail", "inbox", "email"],
      "require": 1
    }
  ]
}
```

- `slug` must exist in `catalog.json`.
- `keywords` are the words that trigger the rule.
- `require` is how many of them must appear. Default 1.

A pinned rule has no confidence and does not decay. It fires whenever its
keywords are there.

## Slash commands

Any capability in the catalog can be invoked directly.

```
/ponytail
/ponytail full
/whatsapp-mcp show unread chats
/wa-read-messages
/gws-gmail
/gws-gmail--cli
```

The eleven built-in commands are never shadowed: `help new model status doctor
context skills mcp usage compact export`.

## Learning

Correct the router and it remembers.

```
you:  find the invoice in my gmail inbox
you:  no, use gws-gmail instead
```

The correction names the capability. The request comes from the turn before
it. The router stores the pair and fires it next time a request like that
arrives.

Confirmations raise confidence: `that worked`, `perfect`, `exactly right`.

## The four guards

These are what make the system improve instead of degrade.

1. **Only user corrections raise confidence.** Usage never does. A route that
   merely got used is not evidence that it was right.
2. **Misses lower confidence.** A rephrase of the same request counts as a miss.
3. **Unused routes decay.** A rule nobody confirms fades, so a one-off
   coincidence stops firing.
4. **Stale slugs are quarantined.** A rule pointing at a skill that no longer
   exists moves to `quarantine.json` instead of firing at nothing.

Confidence starts at 0.60, rises 0.15 per confirmation, falls 0.20 per miss,
decays 0.01 per day unused, and is clamped to `[0.25, 0.95]`. A learned rule
fires at 0.50 or above.

## Rebuilding the catalog

```
python "%USERPROFILE%\.minimax\plugins\capability-router\scripts\build_catalog.py"
```

It reads skills from every skill root, MCP tools from each configured stdio
MCP server, connector tools from `mcode-tools connector tools`, and CLI
services from the `gws` CLI. Then it writes `catalog.json` and a report.

Run it again after adding, renaming or removing a skill.

## Tests

```
python "%USERPROFILE%\.minimax\plugins\capability-router\scripts\test_router.py"
```

35 checks covering the slash path, the pinned path, the learned path, all four
guards, slash-only skills, and malformed input.

## The commandcode CLI

The CLI reads a different settings file, so it needs its own registration entry.
Add this to `%USERPROFILE%\.commandcode\settings.json`, alongside the existing
`PostToolUse` hook:

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

Both runtimes read the same `~/.routing/`, so a rule learned in one works in the
other. A rule only needs to be written once.

## Notes

- The hook is registered by putting the plugin in
  `%USERPROFILE%\.minimax\plugins\`. It is enabled by default. Check with
  `mcode plugin list`.
- Hook commands use absolute paths on purpose. The runtime expands
  `${MINIMAX_HOOKS_DIR}`, but that points at a materialised cache copy, not the
  live plugin.
- `router.py` reads stdin as bytes. Windows text mode decodes stdin with the
  console code page, which corrupts a UTF-8 byte order mark and any non-ASCII
  prompt.
