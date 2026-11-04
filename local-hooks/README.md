# Local hooks

Two user scope hooks that ship alongside this plugin on the machine it was
built on. They live in `%USERPROFILE%\.minimax\`, not inside the plugin,
because they are not part of the router. They are the machine's own setup.

Copies are here so the source travels with the project. **These files in
`~/.minimax/` are the live ones.** After editing here, copy them back:

```sh
Copy-Item ".\session-bootstrap-hook.ps1" "$env:USERPROFILE\.minimax\session-bootstrap-hook.ps1" -Force
Copy-Item ".\linkedin-hook.ps1"         "$env:USERPROFILE\.minimax\linkedin-hook.ps1" -Force
```

## session-bootstrap-hook

Event: `SessionStart`. Injects the token toolkit and the shipping discipline,
once per session, not once per turn.

- Shell output goes through `rtk`, never the raw command.
- `rtk smart <file>` for a two line summary before reading a file fully.
- `/context` for the runtime context snapshot, `/compact` to shorten a long
  conversation.
- The capability router resolves `/name` for any catalogued capability.
- `graphify` is checked for at runtime. It is not installed on this machine, so
  the block says so honestly rather than pretending.
- When a task finishes: document it, commit it, push it. Public repo unless
  told otherwise.
- A separate git worktree only when the task needs an isolated checkout.

## linkedin-hook

Event: `UserPromptSubmit`. Fires when a prompt mentions LinkedIn and injects
the `cli-anything-linkedin` command surface.

It carries the parts that are easy to get wrong:

- Always `--json`. Check `auth status --verify` before doing anything else.
- Capture the returned `urn`. It exists only in the `x-restli-id` header and
  LinkedIn will not read member posts back, so that urn is the only handle.
- Never delete a post without an explicit request naming it and `--yes`.
- The approval gate: write the post, show the user the text, post only after
  they approve.
- The things the API cannot do: comments, reactions, analytics, DMs, reading
  your own post history.

It injects context only. It never posts anything by itself.

## Registration

Both are registered in `%USERPROFILE%\.minimax\hooks.json`:

```json
"SessionStart": [
  {
    "hooks": [
      {
        "type": "command",
        "name": "Session toolkit and shipping discipline",
        "command": "sh \"$HOME/.minimax/session-bootstrap-hook.sh\"",
        "commandWindows": "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"C:\\Users\\ADMIN\\.minimax\\session-bootstrap-hook.ps1\"",
        "timeout": 5
      }
    ]
  }
],
"UserPromptSubmit": [
  {
    "hooks": [
      {
        "type": "command",
        "name": "Route LinkedIn prompts to the cli-anything-linkedin CLI",
        "command": "sh \"$HOME/.minimax/linkedin-hook.sh\"",
        "commandWindows": "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"C:\\Users\\ADMIN\\.minimax\\linkedin-hook.ps1\"",
        "timeout": 5
      }
    ]
  }
]
```

Hook commands use absolute paths. The runtime only sets `MINIMAX_HOOKS_DIR` for
plugin hooks, so a user scope hook cannot rely on it.
