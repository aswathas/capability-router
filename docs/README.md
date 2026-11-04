# Documentation

The capability router, written down from scratch.

Read in this order if you are new. Skip to what you need if you are not.

| Document | What it answers |
|---|---|
| [architecture.md](architecture.md) | What the thing is, how it routes, what it costs in context. |
| [runtime-research.md](runtime-research.md) | What was reverse engineered from the agent runtime, and why it constrained the design. |
| [build-log.md](build-log.md) | The chronological build: decisions, dead ends, and what changed and why. |
| [bugs-found.md](bugs-found.md) | The six real bugs, including the one that failed silently. |
| [antifragility.md](antifragility.md) | The four guards, the confidence arithmetic, and worked examples. |
| [operations.md](operations.md) | Install, rebuild the catalog, troubleshoot, extend, port to another runtime. |
| [testing.md](testing.md) | The test suite, what it covers, and how to add a case. |
| [appendix-whatsapp-mcp.md](appendix-whatsapp-mcp.md) | The case study that came first: a daemon that would not start. |

The original design spec, written before any code, is kept unmodified at
[superpowers/specs/2026-11-05-capability-router-design.md](superpowers/specs/2026-11-05-capability-router-design.md).
It is worth reading because the "Implementation notes" section at the end
records every place the build proved the design wrong. Those corrections are
the most useful part of the whole project.

## The one-paragraph version

An agent with 636 skills, 16 MCP tools, 17 connector tools and 18 CLI services
cannot reliably pick the right one from a prompt, and hand-written routing rules
rot. This project adds a **hook**, not an MCP server. The hook resolves slash
commands exactly, applies rules the user pinned by hand, and learns the routes
the user corrects it on. It injects about 25 tokens on a turn where it fires and
nothing at all otherwise. Permanent context cost: zero. It gets better with use
and cannot get worse, because four guards stop usage from being mistaken for
evidence.
