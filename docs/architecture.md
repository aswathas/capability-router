# Architecture

## The problem

The machine this was built on holds:

- 636 `SKILL.md` files across four skill roots, 321 unique skill names
- 16 MCP tools on the local WhatsApp server
- 17 connector tools
- 18 Google Workspace CLI services

Every one of those is a capability the agent can use. Picking the right one from
a natural language prompt is work the agent does badly, inconsistently, and
without any record of whether it got it right. Hand written routing rules fix
the problem once and then rot, because nobody remembers which rule was for what.

## The three constraints that shaped everything

**1. MCP servers cost permanent context.** Every MCP server's tool schemas are
sent on every request. That is roughly 120 tokens per turn, forever, whether
the tools are used or not. The user rejected an MCP-based router for exactly
this reason, and it is the correct rejection.

**2. The agent already does the fuzzy matching.** Every skill description is
already in the agent's context, in full, every session. A router that
reimplemented fuzzy matching over those descriptions would be a worse, more
expensive copy of something the agent already does better. So the router does
not do fuzzy matching at all.

**3. A hook can implement slash commands.** mcode has eleven built-in slash
commands and no loader for user ones. But an unknown slash command is passed
through to the agent as a plain prompt, verified empirically with
`mcode exec "/ponytail" --max-steps 1`. That single fact is what makes a hook
enough: the runtime does not need to change.

Put together: the hook does the two things the agent cannot know (exact slash
resolution, and what the user corrected before) and nothing else.

## The shape

```
your prompt
   |
   +-- starts with "/"  --> SLASH PATH
   |                       exact slug lookup against the catalog
   |                       argument passed through, valid values listed
   |                       injects one line
   |
   +-- a pinned rule matches  --> injects one line
   |
   +-- looks like a correction --> learn the route, lower the wrong one, stay silent
   |
   +-- looks like a confirmation --> raise confidence, stay silent
   |
   +-- looks like a rephrase --> the last route was wrong, lower it, stay silent
   |
   +-- a learned rule matches --> injects one line
   |
   +-- nothing --> silent
```

Correction, confirmation and rephrase are checked before the learned path on
purpose. A turn where the user is correcting the router should never also
receive an automatic route suggestion.

## The three paths

### Slash path

Exact. `/ponytail` resolves to the catalog entry `ponytail` and nothing else
does. The eleven builtin command names are reserved and never shadowed:
`help new model status doctor context skills mcp usage compact export`.

The argument after the name is passed through untouched. If the target declares
an `argument-hint`, the valid values are listed alongside it.

This path works for all 321 skills, including the ones marked
`disable-model-invocation: true`, because the user typed the name explicitly.

### Static path

Rules the user writes by hand in `~/.routing/routes.static.json`. They have
keywords and a `require` count. No confidence, no decay, no confidence
arithmetic. They fire whenever their keywords are present, and they outrank a
learned rule.

This is the layer that makes "one rule, written once" true. A `gmail →
gws-gmail` rule written here applies to every request that mentions gmail,
forever, and the same file is read by both runtimes.

The router never writes this file.

### Learned path

Rules the router learned from corrections the user typed. Each carries a
confidence score and a set of pattern words. A learned rule fires when at
least 60 percent of its pattern words appear in the prompt and its confidence is
at or above 0.50.

Only routes the user confirmed can reach this path.

## Context cost

| Item | Tokens |
|---|---|
| The 321 skill descriptions | already in context, not new cost |
| The plugin hook | 0 permanent |
| The injected line | about 25, only on a firing turn |
| The learned table | never in context, read on demand |
| The catalog | never in context, read on demand |

The router adds no MCP server, no skill description, and no permanent context.
That is the whole reason it is a hook.

## Data

Everything lives in `~/.routing/`, shared by mcode and the commandcode CLI, so
a rule learned in one works in the other.

| File | Written by | Contents |
|---|---|---|
| `catalog.json` | `build_catalog.py` | one record per capability |
| `catalog-report.json` | `build_catalog.py` | merges, collisions, exclusions |
| `routes.static.json` | **the user** | pinned rules, never auto-written |
| `routes.learned.json` | the router | learned rules with confidence |
| `usage.jsonl` | the router | append-only log, capped at 2000 lines |
| `quarantine.json` | the router | rules whose target vanished |

### Catalog record

```json
{
  "slug": "ponytail",
  "kind": "skill",
  "title": "ponytail",
  "description": "Lazy senior dev mode: the smallest change that fully solves the task...",
  "slash": "/ponytail",
  "argument_hint": "[lite|full|ultra|off]",
  "auto_routable": true,
  "source": "C:/Users/ADMIN/.minimax/skills/ponytail/SKILL.md"
}
```

`kind` is one of `skill`, `mcp_tool`, `connector`, `cli`. `auto_routable` is
false when the skill declares `disable-model-invocation: true`, and those
records are reachable by slash and by pinned rule but never fire automatically.

## Where the router runs

The hook is registered by dropping the plugin in
`%USERPROFILE%\.minimax\plugins\capability-router\`. mcode discovers it, and it
is enabled by default.

The plugin manifest declares one hook file and no MCP server:

```json
{
  "schemaVersion": 1,
  "name": "capability-router",
  "hooks": ["hooks/router.json"]
}
```

The hook file carries one `UserPromptSubmit` handler. The runtime spawns it
with the prompt payload as JSON on stdin. Whatever it prints on stdout enters
the context inside a `<plugin-hook-context>` block. When it prints nothing,
the turn is untouched.

The launcher scripts are thin on purpose. `router.ps1` and `router.sh` do
nothing but hand stdin to `router.py` and pass stdout back, so the Windows path
and the POSIX path cannot drift apart. There is exactly one implementation of
the routing logic.

## What the router will never do

- Call a tool. It only says which capability to use.
- Touch a permission, an `ai_enabled` flag, or a send gate.
- Route to a skill marked `disable-model-invocation` without the user typing it.
- Shadow a builtin slash command.
- Raise its own confidence because a route was used.
- Write to `routes.static.json`.
