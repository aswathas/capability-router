# Runtime research

The design was constrained by eight facts about the agent runtime. All of them
were verified before a line of router code was written, because three of them
decided whether the whole approach was possible.

Every finding here was read out of the installed runtime, not guessed from
documentation.

## 1. mcode has eleven builtin slash commands, and no loader for user ones

`help new model status doctor context skills mcp usage compact export`

Read from `chunks/chunk-HEAI577S.js`, where the builtin command table is a
literal object:

```js
var c={help:{name:"help",description:"Show available commands"},
new:{name:"new",description:"Start a fresh session in the current workspace"},
...
context:{name:"context",description:"Show the Runtime-owned context snapshot"},
...
};
```

There is no mechanism to register a `/mycommand`. That ruled out the obvious
design, where the router ships a command file the runtime picks up.

## 2. An unknown slash command is passed through as a plain prompt

This is the finding that made the project possible.

```sh
mcode exec "/ponytail" --max-steps 1
```

The run started and hit the step limit. It did not error with "unknown
command". The runtime had no idea what `/ponytail` meant, so it handed the
whole string to the agent as text.

Which means a hook that understands `/ponytail` gives the user slash commands
with **no runtime change at all**.

## 3. MCP tool schemas are sent on every request

An MCP server's tools are fetched and attached to every model request. Roughly
120 tokens per tool, per turn, permanently.

This is why the router is a hook and not an MCP server, and why it is a
non-negotiable design constraint rather than a preference. A router exposed as
MCP tools would have cost more context than it saved.

## 4. Only plugin hooks get `MINIMAX_HOOKS_DIR` and `MINIMAX_HOOKS_DATA`

From `chunks/chunk-66K6XTTT.js`, in the hook process launcher:

```js
let d={...xtn(),...t.origin?{MINIMAX_HOOKS_DIR:t.pluginRoot,MINIMAX_HOOKS_DATA:c}:{MINIMAX_PLUGIN_ROOT:t.pluginRoot,...},
MINIMAX_PROJECT_DIR:r.cwd,...}
```

User scope hooks get `MINIMAX_PROJECT_DIR` and the standard environment. No
hook-specific variables.

**Consequence:** a user scope hook cannot use a relative path to find its own
scripts. Every user scope hook on this machine uses absolute paths. Plugin
scope hooks may use `${MINIMAX_HOOKS_DIR}`, which the runtime expands.

## 5. Hook file locations, and a collision on this machine

- user scope: `<DATA_DIR>/hooks.json`, data dir `<DATA_DIR>/v2/hook-data/user`
- project scope: `<project root>/.minimax/hooks.json`

The project root here is `C:\Users\ADMIN`, so the project scope path resolves
to `C:\Users\ADMIN\.minimax\hooks.json`, which is **the same file** as the user
scope path. Only the user scope is active. Turning on the project scope would
run every hook twice for nothing.

## 6. The plugin manifest accepts a `hooks` array of JSON paths

From the MiniMax plugin manifest validator, the allowed top level keys include
`hooks`, and hook paths must match:

```js
kAt=/^(?:[A-Za-z0-9._-]+\/)*[A-Za-z0-9._-]+\.json$/u
```

So `hooks/router.json` is a valid entry, and the hook file itself uses the
same schema as `hooks.json`:

```json
{
  "enabled": true,
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "...", "commandWindows": "...", "timeout": 5 } ] }
    ]
  }
}
```

The `commandWindows` field is what makes the same hook work on Windows. The
`timeout` field is in seconds.

## 7. Skill frontmatter already carries the routing metadata

Scanned across 636 `SKILL.md` files:

| Field | Count |
|---|---|
| `name` | 636 |
| `description` | 636 |
| `disable-model-invocation: true` | 242 |
| `argument-hint` | 22 |
| `allowed-tools` | 8 |
| `compatibility` | 6 |

`disable-model-invocation: true` is the switch between automatic routing and
slash-only routing. It already exists in the corpus, so the router does not
have to invent a convention.

## 8. The agent already performs fuzzy matching, for free

Every skill description is in the agent's context on every turn. A router that
reimplemented matching over those descriptions would be a strictly worse copy
of existing behaviour, running on every prompt, and would cost context to do
it.

This is why the router's only automatic paths are **exact** (slash lookup,
pinned rules) and **learned** (rules the user wrote down or corrected). Fuzzy
matching stays where it belongs, in the agent.

## What else was checked and found wanting

- **`mcode mcp`** is a TUI-only command. There is no CLI way to dump the MCP
  tool registry, which is why the catalog builder probes stdio MCP servers
  directly instead of asking the runtime.
- **`mcode plugin list --all`** is not a valid flag. `--available` is.
- **`mcode plugin marketplace list`** answers "Plugin marketplaces are not
  available in this build."
- **`claude-mem`** is installed at `C:\Users\ADMIN\.claude-mem` but dormant:
  empty corpora, no API key. It was not used.
- **No `mdfile` app, connector, MCP server or skill** exists on this machine.
  It is the user's own local mdview project at `C:\Users\ADMIN\Projects\mdview`.
- **The commandcode CLI reads a different hook file**, so it needs its own
  registration entry. Both runtimes read the same `~/.routing/`, which is what
  makes one learned table serve both.
