# Testing

```sh
python "%USERPROFILE%\.minimax\plugins\capability-router\scripts\test_router.py"
```

35 checks, about 40 seconds.

## The contract being tested

The tests run the router as a real subprocess with a JSON payload on stdin and
read the injected context off stdout. That is the contract the hook uses, so
the tests exercise the same surface the runtime does.

They do **not** exercise the PowerShell launcher. That gap is exactly where
bug 1 lived, a payload that failed to parse and was silently treated as an
empty prompt. See [bugs-found.md](bugs-found.md).

Each test gets its own routing home in a temporary directory, with a copy of
the real catalog. Nothing touches the live `~/.routing/`.

## What is covered

### The slash path

| Check | What it proves |
|---|---|
| slash resolves a skill | `/ponytail` loads the `ponytail` skill |
| slash says the user invoked it | the injected line is phrased as an instruction |
| slash keeps the argument | `/ponytail fix the parser` passes the argument through |
| builtin command is never shadowed | `/status` stays silent |
| builtin help is never shadowed | `/help` stays silent |
| slash reaches a CLI surface | `/gws-gmail--cli` runs the raw CLI |
| slash reaches an MCP tool | `/wa-read-messages` calls the tool by name |
| slash reaches a connector tool | the double dash survives the slug builder |
| unknown slash stays silent | `/no-such-capability-xyz` does nothing |
| plain prompt stays silent | an ordinary question is untouched |

### The learning path

| Check | What it proves |
|---|---|
| no rule yet means no injection | nothing fires before a rule exists |
| correction stays silent | a correction does not also trigger a route |
| correction learned the capability | the slug was captured |
| new rule starts at 0.60 | the confidence arithmetic is right |
| rule captured the earlier request | the pattern came from the previous turn |
| rule did not capture the correction | "instead" is not in the pattern |
| learned rule fires on the same request | the round trip works |

### The four guards

| Check | What it proves |
|---|---|
| guard 1: usage never raises confidence | three firings, confidence unchanged |
| miss lowered the rule | a rephrase costs 0.20 |
| miss did not fire | a rephrase suppresses the route |
| decay lowered the rule | 10 unused days cost 0.10 |
| confirmation raised confidence | "that worked" adds 0.15 |
| usage before confirmation did not | the raise came from the confirmation, not the use |
| stale rule was removed | guard 4 pulled the rule out |
| stale rule was quarantined | it landed in `quarantine.json` |
| quarantine names the slug | the record is readable, not deleted |
| slash-only skill did not auto fire | `disable-model-invocation` is enforced |

### The static path

| Check | What it proves |
|---|---|
| static rule fires | a pinned rule injects |
| static rule says pinned | the injected line is distinguishable from a learned one |
| static rule stays quiet | a prompt without the keywords does nothing |
| static file was not rewritten | the router never writes the user's file |
| pinned rule wins | a pinned rule outranks a learned one on the same prompt |

### Robustness

| Check | What it proves |
|---|---|
| garbage input does not crash | unparseable input exits 0 |
| empty input does not crash | empty stdin exits 0 |

## Add a case

The test file is a flat script with a `check` helper:

```python
check("name of the thing", condition, detail)
```

Conditions that fail print the detail, so make the detail useful.

For a new path, the shape is:

```python
print("some path")
homeX = fresh_home()
try:
    ...set up...
    out = run(homeX, "a prompt")
    check("what it does", "expected" in out, out)
finally:
    shutil.rmtree(homeX, ignore_errors=True)
```

`fresh_home()` gives an isolated routing directory with a copy of the catalog.
`run()` returns the injected stdout, stripped.

## What is not tested

- **The launchers.** `router.ps1` and `router.sh` are not exercised. They are
  thin, but a thin thing that is wrong is still wrong. Verify by hand:

  ```sh
  $payload = @{hook_event_name='UserPromptSubmit'; session_id='t'; cwd='C:\Users\ADMIN'; prompt='/ponytail'} | ConvertTo-Json -Compress
  $payload | & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\Users\ADMIN\.minimax\plugins\capability-router\scripts\router.ps1"
  ```

- **The real runtime.** Tests prove the router behaves. Only a live
  `mcode exec` proves the hook fires inside the agent. Do both after any
  change to the plugin manifest or the hook file.

- **Concurrency.** The router reads and writes plain JSON files with no
  locking. Two concurrent turns in the same session are sequential in practice,
  and the router is a per-user single session, so this has not bitten. If it
  ever does, atomic replace is already used for writes, so the worst case is a
  lost update, not a corrupt file.

- **A second machine.** The paths are absolute and Windows specific. Porting
  means changing the paths in the launchers, the catalog roots in
  `build_catalog.py`, and the binary path in `router.ps1`.
