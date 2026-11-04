# Appendix: the daemon that would not start

This is the case study that came first, on the same machine, in the same
session. It is included because the method is the same one the router was
built with, and because the failure was instructive in a way the router's own
bugs were not.

## Symptom

Every `wa_*` tool returned the same error:

```
daemon failed to start within 15000ms
```

The WhatsApp MCP server runs as a stdio server, but the actual account lives
in a shared background daemon on loopback. The server starts, tries to reach
the daemon, and the daemon never comes up.

## The obvious hypotheses, all wrong

- **Expired licence.** No. `whatsapp-mcp license status` reported a valid
  licence, expiring 2027-10-27.
- **A broken daemon binary.** No. It ran.
- **A wrong licence stored in the wrong place.** No, same result.
- **The daemon was already running and the server could not reach it.** Plausible.
  Nothing was listening.

## The actual cause

The daemon keeps its pid in `store\daemon.pid`. On startup it reads that file,
checks whether the pid is alive, and if it is, concludes that another instance
already owns the store and exits.

That pid file was stale. It held pid 2216, and Windows had recycled 2216 for an
unrelated `svchost` process. The daemon looked at a live process, decided it
was a competing instance, and quit.

**And it quit before writing a single log line.** That is the detail that
turned this from a guess into a diagnosis. There was no error in
`daemon.log`. There was no error anywhere. The process started, read a stale
file, and left.

## The fix

```sh
rm -- "C:\Users\ADMIN\AppData\Roaming\whatsapp-mcp\store\daemon.pid"
whatsapp-mcp daemon start
whatsapp-mcp daemon status
```

```
daemon pid 20784
connection: open
linked: true
verified: true
```

All 16 tools worked straight after. The licence had never been the problem.

## The lesson that carried into the router

**Silence is a diagnostic signal, and it is more expensive than noise.**

A daemon that logs its reason for quitting would have said "pid 2216 is alive,
exiting". Instead it said nothing, and the diagnosis had to come from reading
the startup logic against the store directory by hand.

The router inherited this lesson directly. Two of its bugs were the same
shape: the system looked healthy while doing the wrong thing.

- The stdin encoding bug produced no output and no error. The hook ran, the
  process started, the exit code was 0. Every signal a supervisor checks said
  fine.
- The decay bug applied its change in memory and threw it away. From the
  outside, the guard was implemented, documented and working.

The rule that came out of it: **when a check passes, it has to have actually
exercised the thing it claims to check.** The router's test suite now runs the
router as a subprocess with a real payload on real stdin, and the live check
reads the injected line out of an actual session transcript rather than
trusting that the hook was registered.

## The other half of the lesson

`rm --` and not `Remove-Item`. On this machine the safe delete path is
routed through a recoverable trash, so the stale pid file is still recoverable
if the diagnosis turns out to be wrong.

That is worth more than it sounds. The alternative, deleting a file with a
guessed path because a process said "pid alive", is how you turn a broken
daemon into a broken machine.
