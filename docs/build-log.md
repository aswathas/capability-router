# Build log

The chronological record of how this was built, including the parts that did
not work. Read this if you want to know why the thing looks the way it does.

## The ask

The user wanted an intelligent capability router: a loop that routes a prompt to
the right skill, MCP tool, plugin or CLI, learns from which routing was
correct, and needs no manual hook configuration.

In their own words, the properties that mattered:

- Works "like plugin or tool connected without CLI agent", that is, a real
  integrated capability, not something the agent has to shell out to.
- "without taking much context". Near zero permanent context cost.
- Antifragile. It should improve with use, not degrade.
- Explicit slash invocation like `/ponytail` must work.
- Both a static and a dynamic layer.
- Global learning. One rule like `gmail → gws-gmail` should not need writing
  twice.

## Phase 1: the wrong turn, deliberately

The first design was a router exposed as an MCP server, with the agent calling
a `route()` tool.

It was rejected by the user with: "i dont want it mcp will take context
something different".

They were right, and the reason is now finding 3 in
[runtime-research.md](runtime-research.md): MCP tool schemas are attached to
every request. A router that costs permanent context to save the agent from
choosing a skill is a bad trade.

That rejection set the architecture: **hook only, no MCP server, no skill**. A
skill would have put a description in the context every session, which is the
same cost by another route.

## Phase 2: reverse engineering before design

Before designing anything, the runtime was read. Eight findings came out of it
(see [runtime-research.md](runtime-research.md)). Three mattered enormously:

- Unknown slash commands pass through as plain prompts. This is what made
  slash routing possible without touching the runtime.
- Only plugin hooks get `MINIMAX_HOOKS_DIR`. This decided that the router is a
  **plugin** with a hook, not a user scope hook.
- The skill corpus already carries `disable-model-invocation`. This decided
  that the router does not need to invent a convention for "route this only
  when I type it".

The corpus was also scanned: 636 `SKILL.md` files, 321 unique names, 241 name
collisions caused by the same skill being mirrored across four roots.

## Phase 3: design, and the four guards

The design went through the brainstorming skill and was approved before any
code. The part that mattered most was the argument that a learning system is
only antifragile if specific failure modes are closed in advance.

Four guards, chosen because each closes a distinct way the system gets worse:

1. Only user corrections raise confidence. Usage never does.
2. Misses lower confidence.
3. Unused routes decay.
4. Stale slugs are quarantined.

Guard 1 is the one that cannot be compromised. If usage raised confidence, the
router would train on its own echo: it suggests a route, the agent follows it,
the task still fails, and the router reads that as evidence it was right.

Also decided: the hook does **not** do fuzzy matching. The agent already has
every description in context. The hook adds only exact resolution and learned
history.

## Phase 4: building it

Order of work, and why:

1. `router.py` first, standalone, because the routing logic is the project.
2. `build_catalog.py` next, because the router needs a catalog to be useful
   and the catalog is the thing that can rot.
3. `router.ps1` and `router.sh` last, as thin pass-through launchers, so the
   two platforms could not drift.
4. The plugin manifest and hook file last of all, because the runtime contract
   was the last thing to be confirmed.

### The catalog builder

Four sources, each read the way it actually lives:

| Source | How it is read |
|---|---|
| Skills | `SKILL.md` frontmatter across four skill roots plus plugin skills |
| MCP tools | raw JSON-RPC `tools/list` spoken to each configured stdio server |
| Connector tools | `mcode-tools connector tools` |
| CLI services | the `gws --help` service list |

The MCP probe was the interesting one. There is no `mcode mcp` CLI to dump the
registry, so the builder spawns each server and speaks JSON-RPC to it
directly: `initialize`, `notifications/initialized`, `tools/list`. The
WhatsApp server returns all 16 tools this way, with no hardcoded list to go
stale.

### The first catalog was wrong

The first build produced 45 disambiguated slugs, including `/tdd--skill`,
`/tdd--skill-2` through `/tdd--skill-7`.

Cause: the same skill exists in four roots with slightly different frontmatter,
so "same slug, different content" fired, and the design said to keep both with
a suffix.

The design was wrong. A skill name is the identity. Mirrored copies are one
capability, and the suffix rule belongs **across kinds**, not across mirrors.
After the fix: 372 records, 7 disambiguated slugs, and the 7 are all real
cross-kind collisions, like the `gws-gmail` skill and the `gws gmail` CLI
service.

### The static layer was dead on arrival

`routes.static.json` was in the original design as "pinned rules, user owned,
never auto written". The router read `catalog.json` and `routes.learned.json`
and **never read the static file at all**.

That was the "static + dynamic" half of the request, implemented as a filename.
It was found while writing the build log, which is the argument for writing
the build log.

The static layer is now a real path: keywords plus a `require` count, no
confidence, no decay, outranks a learned rule, and the router never writes the
file.

## Phase 5: testing found four more bugs

The test suite went up from nothing to 35 checks. It found four bugs that
manual testing had missed. See [bugs-found.md](bugs-found.md) for all of them.

The most instructive one was the silent failure: the router produced no output
at all, with no error, because Windows text mode decoded stdin with the console
code page, the UTF-8 byte order mark survived as three stray characters, the
JSON did not parse, and the router treated an unparseable payload as an empty
prompt and exited cleanly.

A hook that fails silently is worse than a hook that crashes, because a crash
is visible.

## Phase 6: live verification

Tests run the router as a subprocess. That is the right contract, but it is
not the whole story, so the hook was verified inside the real runtime:

```sh
mcode exec "/ponytail what does this skill do" --max-steps 1
```

The session transcript contains:

```
The user invoked the command. Load the `ponytail` skill and follow it. Argument: what does this skill do. Valid argument values: lite, full, ultra, off.
```

inside the `<plugin-hook-context>` block, immediately followed by the raw
prompt. The hook fires in the real agent.

## Phase 7: the local hook layer

The same session added two more user scope hooks, both following the pattern
established by the caveman, diagram and WhatsApp hooks:

- **LinkedIn routing.** When a prompt mentions LinkedIn, inject the
  `cli-anything-linkedin` command surface, including the approval gate, the
  capture-the-urn rule, and the list of things the API cannot do.
- **Session bootstrap.** Once per session, inject the token toolkit (`rtk`,
  `/context`, `/compact`, the capability router) and the shipping discipline:
  document, commit, push when a task finishes; use a git worktree only when
  the task needs an isolated checkout.

Both inject context only. Neither calls a tool.

`graphify` was asked for by name in the same request. It is not installed on
this machine, is not a skill, and is not in the 244 skills in the skillhub
store. The bootstrap hook checks for it at runtime and says so honestly rather
than pretending.
