# Antifragility

A learning system is adaptive, not antifragile. It becomes antifragile only
when the specific ways it could get worse are closed in advance.

This router has four such guards. Each one closes one failure mode, and each
one is a hard rule in the code rather than a convention.

## The failure mode that matters most

The obvious way to build this is: the router suggests a capability, the agent
uses it, the task succeeds, so the router raises its confidence in that route.
That is wrong, and it is wrong in a way that is invisible until the router is
badly broken.

The router suggesting a route is not evidence the route was right. The agent
following a bad suggestion can still produce a confident, complete, wrong
answer. Raising confidence on usage trains the router on its own echo. The
error compounds silently, and the router gets more confident about the wrong
things over time.

So: **only user corrections raise confidence.** Never usage.

## The four guards

### Guard 1: only user corrections raise confidence

Confidence rises by 0.15 when the user says something that confirms the last
route: "that worked", "perfect", "exactly right", "that's right".

Nothing else raises it. Not a successful tool call, not a completed task, not
the route being used again.

### Guard 2: misses lower confidence

Confidence falls by 0.20 when the route was probably wrong. Two signals count:

- **A correction.** The user says "no, use something else instead". The
  previous route, if it fired, is lowered.
- **A rephrase.** The user asks for the same thing in different words. That
  usually means the last attempt did not land. The guard fires only between
  similarity 0.70 and 0.98, so a repeated identical request is not counted.
  See [bugs-found.md](bugs-found.md), bug 3.

### Guard 3: unused routes decay

A learned rule loses 0.01 of confidence per day it goes unconfirmed. A rule
that only ever worked once fades below the fire threshold and stops firing.

This is what stops a coincidence from becoming a habit. If "invoice" happened
to route to `gws-gmail` once, and the user never confirmed it, that rule
quietly dies instead of sitting there forever making a wrong suggestion.

### Guard 4: stale slugs are quarantined

Every learned rule stores the slug it points at. Every turn, the router checks
that slug still exists in the catalog. If it does not, the rule moves to
`quarantine.json` and is not used.

A renamed or deleted skill cannot leave the router confidently pointing at
nothing. The rule is not deleted, it is quarantined, so it can be inspected and
restored if the slug comes back.

## The arithmetic

| Event | Change |
|---|---|
| Correction confirms a route | +0.15 |
| Miss | -0.20 |
| Day unused | -0.01 |
| Learned from scratch | starts at 0.60 |
| Clamp | [0.25, 0.95] |
| Fires at | 0.50 or above |

## Worked examples

### A route the user confirmed

```
you:  find the invoice in my gmail inbox
      -> no rule, nothing injected

you:  no, use gws-gmail instead
      -> correction. The router resolves "gws-gmail" to a catalog slug.
         The request words come from the previous prompt, because the
         correction itself names no task.
         New rule: slug=gws-gmail, pattern=["gmail","inbox","invoice"],
         confidence=0.60

you:  find the invoice in my gmail inbox
      -> coverage 3/3, confidence 0.60 >= 0.50, fires.
         "Pinned rule"-style injection for the learned route.
         Confidence stays 0.60. Usage is not evidence.
```

Note the request text: the correction names the capability, not the task. The
task was in the previous turn. The router reads it from the usage log.

### A route the user rejected

```
you:  find the invoice in my gmail inbox
      -> learned rule fires, confidence 0.60

you:  no, use gws-sheets instead
      -> correction. The rule that just fired is lowered to 0.40.
         A new rule for gws-sheets is created at 0.60.
```

### A route nobody confirmed

```
you:  find the invoice in my gmail inbox
      -> learned rule fires

... 10 days, no confirmation ...

you:  find the invoice in my gmail inbox
      -> decay took 0.10 over the 10 days, so confidence is 0.50.
         Still at the fire threshold, but one more week and it is gone.
```

### A rule pointing at a renamed skill

```
you:  find the invoice in my gmail inbox
      -> learned rule for "gws-gmail"

... the gws-gmail skill is renamed to "gws-mail" ...

you:  find the invoice in my gmail inbox
      -> the slug is not in the catalog any more.
         The rule moves to quarantine.json and is not used.
         Nothing is injected. The router does not point at a ghost.
```

## Why the static layer needs no guards

A pinned rule has no confidence and does not decay. It was written by the user
on purpose, so the only thing that can change it is the user changing it.

This is deliberate, and it is the one place where the system deliberately does
**not** learn. A rule the user pinned is an instruction, not a hypothesis.

The corollary is that a bad pinned rule stays bad until the user fixes it. That
is the correct trade: the user wrote it, the user can see it, and it is one
file edit to change.

## Precedence

When more than one path could fire:

1. Slash path, because the user typed the name.
2. Correction and confirmation, which must be processed before anything fires,
   or the router would answer a correction with a suggestion.
3. Rephrase detection, for the same reason.
4. Static path, because the user pinned it on purpose.
5. Learned path, the weakest evidence.

## What this does not protect against

- A pinned rule that is simply wrong. That is the user's file, and the fix is
  one edit.
- A learned rule that keeps getting confirmed because the user likes the wrong
  thing. Confidence saturates at 0.95, and repeated confirmation will keep it
  there. No amount of machine-side cleverness fixes a bad preference.
- The agent choosing badly on its own, with no route involved. The router is
  not a fallback for the agent's own judgement. It is for the cases where the
  user has already said which way it should go.
