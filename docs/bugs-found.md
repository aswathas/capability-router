# Bugs found

Six real bugs, found while building. Every one is written down here with the
symptom, the cause, and how it was caught, because the symptom and the cause
were never close together in any of them.

| # | Bug | Symptom | Cause | Caught by |
|---|---|---|---|---|
| 1 | Silent failure | No output, no error | stdin decoded as cp1252 | Live test in the real runtime |
| 2 | Double dash collapsed | `/gws-gmail--cli` did not resolve | slug builder collapsed `--` into `-` | Unit test |
| 3 | Self-punishment | Confidence fell every time the router worked | rephrase guard treated a repeat as a mistake | Unit test |
| 4 | Decay lost | Rules never faded | decay applied in memory, never persisted | Unit test |
| 5 | Junk slugs | `/tdd--skill-3` | mirrored skills treated as distinct | Catalog build report |
| 6 | Dead static layer | `routes.static.json` was ignored | never wired into the router | Writing the build log |

## 1. Silent failure

**Symptom.** The router printed nothing, for every prompt, including ones that
should have fired. No error, no log line, exit code 0.

**Cause.** Windows text mode decodes `sys.stdin` with the console code page,
cp1252 on this machine. The hook payload is UTF-8. Two things broke:

- A UTF-8 byte order mark, `EF BB BF`, decoded as three stray characters
  instead of `U+FEFF`, so `raw.lstrip("\ufeff")` did not remove it.
- Any non-ASCII character in the prompt would have been mangled too.

The payload then failed to parse. The router caught the `ValueError`, treated
the payload as empty, and exited cleanly.

**Why it is the worst of the six.** The hook was invoked correctly, the
process started correctly, the exit code was 0. Every signal a supervisor would
look at said "fine". A crash would have been visible. This was invisible.

**Fix.** Read bytes, decode UTF-8 explicitly.

```python
stream = getattr(sys.stdin, "buffer", None)
data = stream.read()
raw = data.decode("utf-8", errors="replace")
```

**How it was caught.** Not by the tests. The tests passed a payload through
Python's `subprocess` with `text=True, encoding="utf-8"`, which is already
correct, so they never produced a BOM or a code page problem. It surfaced the
first time the real `.ps1` launcher was driven from a PowerShell pipeline, which
prepends a BOM. The unit tests were testing the router, not the launcher plus
the router. Live verification was not optional.

## 2. Double dash collapsed

**Symptom.** `/gws-gmail--cli` and `/connector--matrix--batch-text-to-music`
both resolved to nothing.

**Cause.** The slug builder normalised every run of non-alphanumeric
characters to a single dash. `--` became `-`. But a double dash is a real
separator in this catalog: it encodes the `__` in a connector tool name, and
it is the disambiguation suffix.

```python
# before
flat = re.sub(r"[^a-z0-9]+", "-", text)     # "gws-gmail--cli" -> "gws-gmail-cli"

# after
flat = "--".join(
    re.sub(r"[^a-z0-9]+", "-", part).strip("-")
    for part in text.split("--")
)                                             # "gws-gmail--cli" -> "gws-gmail--cli"
```

**How it was caught.** Two unit tests failed on the first run: "slash reaches a
CLI surface" and "slash reaches a connector tool". The catalog was right, the
router was wrong.

## 3. Self-punishment

**Symptom.** A learned rule that fired correctly lost 0.20 of confidence every
time it fired. Confidence fell 0.60 to 0.40 and then stopped, pinned at the
floor. The router was destroying the routes that worked.

**Cause.** The rephrase guard, whose job is to detect "the user asked again
because the last route was wrong", compared the current prompt to the previous
one and treated anything above 0.70 similarity as a rephrase. Repeating the
same request is similarity 1.00, so it was counted as a mistake.

**Fix.** Only a *similar but different* request is a rephrase. An identical
repeat is the router working.

```python
score = similarity(prior, tokens)
if REPHRASE_THRESHOLD <= score < IDENTICAL_THRESHOLD:   # 0.70 .. 0.98
    ...lower the confidence...
```

**How it was caught.** The unit test "guard 1: usage never raises confidence"
failed with `0.6 -> 0.39999999999999997`. The guard was supposed to prove
confidence never rises on usage. It proved something worse.

## 4. Decay lost

**Symptom.** Guard 3, "unused routes decay", did not work. Rules kept their
confidence forever.

**Cause.** Decay was applied inside `match_learned`, which only runs rules
through the learned path. On a turn where no rule fired, the function returned
early and the decayed values were never written back to disk. The decay
happened in memory and died there.

**Fix.** Apply decay once per turn, before anything else, and persist when it
changed anything.

```python
if apply_decay_all(learned, stamp):
    save_json(LEARNED_PATH, learned)
```

`apply_decay` also had to move **out** of `match_learned`, because otherwise it
would run twice in the same turn and subtract the decay twice.

**How it was caught.** The unit test "decay lowered the rule" failed. The test
itself had a bug too, which is worth recording: it mutated a rule object
returned by a helper that re-read the file from disk, so the mutation was
applied to a detached copy and never saved. The test was fixed to mutate the
parsed document it then wrote. Both the test and the router were wrong at the
same time, in opposite directions.

## 5. Junk slugs

**Symptom.** The catalog contained `/tdd--skill`, `/tdd--skill-2` through
`/tdd--skill-7`. `/docx--skill-3`. `/teach--skill-7`. 45 disambiguated slugs
in total.

**Cause.** The same skill exists in four skill roots with slightly different
frontmatter. The design said "same slug, different content, keep both, suffix
the second". Applied to mirrors, that produces nonsense.

**Fix.** A skill name is the identity. Mirrored copies merge into one record.
The richest description wins, and `auto_routable` is the strictest of the
copies, because a copy that disables model invocation is a safety instruction.
The suffix rule now applies only across kinds: the `gws-gmail` skill and the
`gws gmail` CLI service get `/gws-gmail` and `/gws-gmail--cli`.

**How it was caught.** By reading the build report, which lists every
collision. The report existed precisely so that this class of problem would be
visible instead of quiet.

## 6. Dead static layer

**Symptom.** `routes.static.json` was created, documented, and ignored. A
pinned rule did nothing.

**Cause.** The router loaded `catalog.json` and `routes.learned.json`. It
never loaded the static file. The path constant was defined and unused.

**Fix.** Implemented as a real path, above the learned path in precedence:

```python
static = load_static()
if static.get("rules"):
    record = match_static(prompt, static, catalog)
    if record:
        print(inject_line(record, "", invoked=False, lead="Pinned rule."))
        return 0
```

**How it was caught.** By writing the build log, which asked the obvious
question: what does each file in the data directory actually do. The answer for
this one was "nothing".

## The pattern

Four of the six were found by the test suite, one by reading a build report,
and one by writing prose.

Not one was found by running the thing once and looking at it. The bugs that
matter are the ones where the system looks like it is working while doing the
wrong thing, and those do not show up in a smoke test.
