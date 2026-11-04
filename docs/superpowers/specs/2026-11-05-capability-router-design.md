# Capability Router — design spec

Date: 2026-11-05
Status: approved by user, ready for implementation

## Problem

The user owns 636 skills, 16+ MCP tools, 17 connector tools, and 15 CLI service
surfaces. Hand-written routing rules are required today for every capability the
user wants the agent to reach for. Those rules rot, and there is no record of which
routing was actually correct.

The goal is a system that routes a prompt to the right capability with no manual
configuration, and that improves from use without ever becoming worse than the
hand-written rules it started with.

## Non-goals

- The router never calls a tool. It only tells the agent which capability to use.
- The router never weakens an existing permission, `ai_enabled` flag, or send gate.
- The router does not become a second copy of the skill catalog. The agent already
  holds every skill description in context; duplicating them would be pure cost.

## Key findings that constrain the design

1. **mcode has 11 built-in slash commands and no user-command loader.**
   `help new model status doctor context skills mcp usage compact export`.
   Verified by reading `chunks/chunk-HEAI577S.js`.

2. **An unknown slash command is passed through to the agent as a plain prompt.**
   Verified empirically: `mcode exec "/ponytail" --max-steps 1` ran and hit the
   step limit rather than erroring with an unknown-command message.
   Therefore a hook can implement slash resolution without any runtime change.

3. **Skill frontmatter already carries the routing metadata.**
   Scanned across 636 `SKILL.md` files: `name` and `description` on all 636,
   `argument-hint` on 22, `disable-model-invocation: true` on 242,
   `allowed-tools` on 8, `compatibility` on 6.

4. **`disable-model-invocation: true` is the natural switch** between automatic
   routing and slash-only routing. Those 242 skills are exactly the ones that
   should require explicit invocation.

5. **The agent already performs fuzzy matching for free.** Every skill
   description is in the agent's context each session. A router that reimplemented
   fuzzy matching would be a worse, more expensive copy of existing behaviour.

6. **Two runtimes read different hook files.** mcode reads
   `%USERPROFILE%\.minimax\hooks.json`; the commandcode CLI reads
   `%USERPROFILE%\.commandcode\settings.json`. A shared data path is required for
   one learned table to serve both.

7. **MCP tool schemas are sent on every request.** An MCP-based router would add
   permanent context cost. The user rejected this explicitly.

8. **Only plugin hooks receive `MINIMAX_HOOKS_DIR` and `MINIMAX_HOOKS_DATA`.**
   User-scope hooks receive `MINIMAX_PROJECT_DIR` plus standard environment only.
   Verified in `chunks/chunk-66K6XTTT.js` and `chunks/chunk-YYSTRBDA.js`.

## Architecture

A local plugin, `capability-router@local`, containing no MCP server. It ships one
`UserPromptSubmit` hook. The hook runs outside the agent's context system; only
its stdout enters the context, and only when it fires.

```
your prompt
   |
   +-- starts with "/" ?  --> SLASH PATH
   |                          exact slug lookup, argument validated
   |                          against argument-hint
   |                          inject one line
   |
   +-- learned rule matches ? --> inject one line
   |
   +-- looks like a correction ? --> learn, stay silent
   |
   +-- otherwise --> silent
```

Fuzzy matching is intentionally absent from the hook. The agent performs it using
descriptions already in its context. The hook adds only the two things the agent
cannot know: exact slash resolution, and what the user corrected before.

## The two dispatch paths

### Slash path

Prompt begins with `/`. The hook parses `/name` and an optional argument.

- `name` is resolved exactly against the catalog slug.
- The 11 built-in command names are reserved and never shadowed.
- If the resolved skill carries `argument-hint`, the argument is validated
  against it. An invalid argument is still passed through, with a note.
- The injected line is capability-shaped:
  - skill -> `Load the <name> skill and follow it.`
  - mcp tool -> `Call the <tool> tool.`
  - cli -> `Run: <exact command>`

This path works for all 636 skills, including the 242 that are marked
`disable-model-invocation`, because the user typed them explicitly.

### Learned path

A learned rule matches the prompt. Injects the capability line. This path only
ever fires for routes the user confirmed.

### Correction capture

The hook detects correction phrasing and learns from it. No agent involvement,
no file editing by the user.

Patterns recognised: `no, use X`, `not X, use Y`, `instead use X`, `use X instead`,
`rather use X`, `wrong, use X`, `I meant X`.

On a match the hook extracts the capability name, resolves it to a catalog slug,
extracts the request portion of the message as the pattern, and writes a learned
rule.

## Data files

Canonical location: `~/.routing/`. Shared by mcode and the commandcode CLI.

| File | Owner | Contents |
|---|---|---|
| `catalog.json` | generated | one record per capability |
| `routes.static.json` | user | pinned rules, never auto-written |
| `routes.learned.json` | machine | learned rules with confidence |
| `usage.jsonl` | machine | append-only prompt/routing log, capped |
| `quarantine.json` | machine | rules whose slug no longer exists |

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

`auto_routable` is `false` when the skill declares `disable-model-invocation: true`.

### Catalog sources

| Source | How it is read | Records |
|---|---|---|
| Skills | `SKILL.md` frontmatter across three skill roots | 636 dirs, 256 unique names |
| MCP tools | runtime registry names | 16+ |
| Connectors | `mcode-tools connector tools` | 17 |
| CLIs | `gws --help` service list | 15 services |

### Collision rules

1. Same slug, same content hash -> one record; keep the richest copy.
2. Same slug, different content -> keep both; disambiguate with a source suffix,
   for example `/tdd--pstack`.
3. MCP tool `wa_read_messages` -> slug `wa-read-messages`.
4. The 11 built-in command names are reserved. A skill with one of those names is
   excluded from the catalog and recorded as a collision in the build report.

## The four antifragility guards

The system is adaptive, not antifragile, unless these hold. Each one closes a
specific way the system could get worse over time.

1. **Only user corrections raise confidence.** Usage never does. This closes the
   "I used it, therefore it was right" echo: the router suggested a capability,
   the agent followed it, and the task may still have failed.

2. **Errors lower confidence.** A tool error, a non-zero exit, or a rephrase of
   the same request lowers the confidence of the route that was suggested.

3. **Unused routes decay.** A learned rule loses confidence when it goes
   unconfirmed, so a rule that only ever worked once fades out.

4. **Stale slugs are quarantined.** Every learned rule stores the catalog
   version it was learned under and the slug it points at. If that slug no
   longer exists in the current catalog, the rule moves to `quarantine.json` and
   is not used. A renamed skill cannot leave the router confidently pointing at
   nothing.

Confidence starts at 0.60 on learn, rises by 0.15 per confirmation, falls by 0.20
per miss, decays by 0.01 per day unused, and is clamped to [0.25, 0.95]. A learned
rule fires at confidence 0.50 or above.

## Context cost

| Item | Tokens |
|---|---|
| 636 skill descriptions | already in context; not new cost |
| plugin hook | 0 permanent |
| injected line | ~25, only on a firing turn |
| learned table | never in context; read on demand |

The router adds no MCP server, no skill description, and no permanent context.

## Files

```
.minimax/plugins/capability-router/
  .minimax-plugin/plugin.json
  hooks/router.json
  scripts/router.py            core matcher, one implementation
  scripts/router.ps1           Windows launcher, passes stdin through
  scripts/router.sh            POSIX launcher
  scripts/build_catalog.py     regenerates ~/.routing/catalog.json
  docs/superpowers/specs/2026-11-05-capability-router-design.md
```

The matcher is implemented once in Python. The `.ps1` and `.sh` launchers are
thin wrappers that hand stdin to it untouched, so the two platforms cannot drift.

## Scope

Implemented as one unit: plugin, hook, catalog builder, learned store, guards.
No changes to the existing caveman, diagram, or WhatsApp hooks.

The commandcode CLI needs a separate registration entry pointing at the same
script and the same `~/.routing/` directory. That entry is documented, not
applied automatically.

## Implementation notes

Added after the build, where the implementation found the design to be
incomplete or wrong. The design above still holds; these are the corrections.

### A mirrored skill is one skill, not many

The design said "same slug, different content, keep both and suffix". For
skills that produces junk: the same skill exists in four skill roots with
slightly different frontmatter, so `/tdd` would have had eight siblings
(`/tdd--skill`, `/tdd--skill-2`, ...).

A skill name is the identity. Copies of the same name are now merged into one
record. The richest description wins, and `auto_routable` is the strictest of
the copies, because a copy that disables model invocation is a safety
instruction. The suffix rule still applies, but only across kinds: a skill and
a CLI service that want the same name get `/gws-gmail` and `/gws-gmail--cli`.

### The static layer is a real layer, not a file

The design listed `routes.static.json` as user-owned but never said how it
matches. It does now. A pinned rule carries keywords and a `require` count. It
has no confidence and does not decay. It fires whenever its keywords are
present, and it outranks a learned rule.

### A repeated request is not a mistake

The rephrase guard used to treat any prompt similar to the previous one as a
miss. That meant repeating the same request twice lowered confidence twice, so
the router punished itself for working. The guard now fires only between
similarity 0.70 and 0.98. An identical repeat is the router doing its job.

### Corrections must be corrections

The marker set used to include a bare "use X". Any prompt containing "use"
would have trained the router. The markers are now explicit corrections only:
`no, use X`, `instead use X`, `rather use X`, `I meant X`, `use X instead`.

A correction names the capability but usually not the task. When the
correction carries no request words of its own, the pattern comes from the
previous prompt, which is where the task actually was.

### Slash-only skills never fire automatically

`disable-model-invocation: true` is enforced on the learned path. Those 242
skills are reachable by slash and by a pinned rule, but a learned rule will
not auto-fire one of them.

### MCP tools are discovered, not hardcoded

The catalog builder speaks raw JSON-RPC to each configured stdio MCP server and
reads its `tools/list`. The WhatsApp server returns all 16 tools this way.
There is no hardcoded tool list to go stale.

### stdin is read as bytes

Windows text mode decodes stdin with the console code page. A UTF-8 byte order
mark arrives as three stray characters, the JSON does not parse, and the router
fails silently. `router.py` reads `sys.stdin.buffer` and decodes UTF-8 itself.

### Files added during the build

```
  README.md                     usage, data format, cmdc registration
  scripts/test_router.py        35 regression checks
  scripts/_make_icon.py         regenerates icon.png
```

### Measured result

Catalog on this machine: 372 records, 321 skills, 16 MCP tools, 17 connector
tools, 18 CLI services, 7 disambiguated slugs, 1095 identical copies merged,
38 mirrored variants merged, 0 builtin names touched.

Hook latency: about 290 ms per turn, including process start.
Injected line: about 25 tokens, only on a firing turn.
Permanent context cost: zero.

