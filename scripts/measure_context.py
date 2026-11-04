#!/usr/bin/env python3
"""Measure what actually costs context in one agent turn.

Everything here is measured, not estimated. The point of the script is to
replace "MCP servers cost context" with a ledger.

    python measure_context.py

Outputs a token table using tiktoken's cl100k_base encoding. The runtime's
own tokenizer is not public, so the numbers are a consistent proxy, not the
exact billed count. Character counts are exact and are printed alongside.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

try:
    import tiktoken
except ImportError:
    print("tiktoken is required: pip install tiktoken")
    raise SystemExit(2)

HOME = Path.home()
ROUTING = Path(os.environ.get("ROUTING_HOME", str(HOME / ".routing")))
CATALOG = ROUTING / "catalog.json"

SKILL_ROOTS = [
    HOME / ".minimax" / "skills",
    HOME / ".agents" / "skills",
    HOME / ".claude" / "skills",
    HOME / ".commandcode" / "skills",
    HOME / ".minimax" / "plugins",
]

ENC = tiktoken.get_encoding("cl100k_base")


def tokens(text: str) -> int:
    return len(ENC.encode(text))


def chars(text: str) -> int:
    return len(text)


def frontmatter(path: Path) -> dict:
    try:
        head = path.open("r", encoding="utf-8", errors="replace").read(8192)
    except OSError:
        return {}
    match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", head, re.S)
    if not match:
        return {}
    block = match.group(1)
    data = {}
    for line in block.splitlines():
        if not line.strip() or line[:1] in (" ", "\t") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        data[key.strip()] = value
    return data


def skill_descriptions() -> tuple:
    """The name + description pair for every skill the agent holds."""
    seen = {}
    files = 0
    for root in SKILL_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("SKILL.md")):
            files += 1
            meta = frontmatter(path)
            name = (meta.get("name") or path.parent.name).strip()
            description = (meta.get("description") or "").strip()
            if not name:
                continue
            entry = f"{name}: {description}"
            current = seen.get(name)
            if current is None or len(entry) > len(current):
                seen[name] = entry
    return list(seen.values()), files


def here_string(path: Path) -> str:
    """Pull the injected context out of a PowerShell hook script."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(r"@'\r?\n(.*?)\r?\n'@", text, re.S)
    if match:
        return match.group(1)
    match = re.search(r"@\"\r?\n(.*?)\r?\n\"@", text, re.S)
    return match.group(1) if match else ""


def main() -> int:
    rows = []

    # 1. The skill catalog the agent carries on every turn.
    descriptions, files = skill_descriptions()
    blob = "\n".join(descriptions)
    rows.append((f"{len(descriptions)} skill name + description pairs", blob))

    # 2. MCP tool schemas. The WhatsApp server is the only MCP server here.
    mcp = load_mcp_schemas()
    if mcp:
        rows.append(("16 MCP tool schemas (WhatsApp)", mcp))

    # 3. Connector tools. The CLI exposes name and description only, so this
    #    undercounts the real schema cost. Labelled honestly below.
    connectors = load_connector_tools()
    if connectors:
        rows.append((f"{connectors[1]} connector tools (name + description only)", connectors[0]))

    # 4. What each hook adds.
    hooks = [
        ("router injection (one firing turn)", router_line()),
        ("caveman hook block", here_string(HOME / ".minimax" / "caveman-hook.ps1")),
        ("session bootstrap block", here_string(HOME / ".minimax" / "session-bootstrap-hook.ps1")),
        ("whatsapp hook block", here_string(HOME / ".minimax" / "whatsapp-mcp-hook.ps1")),
        ("linkedin hook block", here_string(HOME / ".minimax" / "linkedin-hook.ps1")),
    ]
    for label, text in hooks:
        if text:
            rows.append((label, text))

    # 5. What the router keeps on disk and never puts in context.
    if CATALOG.is_file():
        rows.append(("router catalog on disk (never in context)", CATALOG.read_text(encoding="utf-8")))

    print(f"{'item':52} {'tokens':>9} {'chars':>10}")
    print("-" * 74)
    for label, text in rows:
        print(f"{label:52} {tokens(text):>9} {chars(text):>10}")
    print("-" * 74)
    print(f"{'skill files scanned':52} {files:>9}")

    with_suffix = [r for r in rows if "never in context" not in r[0]]
    total = sum(tokens(t) for _, t in with_suffix)
    print(f"{'total of the measured context items':52} {total:>9}")
    return 0


def load_connector_tools() -> tuple:
    """Connector tool names and descriptions, straight from the CLI."""
    import shutil
    import subprocess

    binary = shutil.which("mcode-tools")
    if not binary:
        return "", 0
    try:
        proc = subprocess.run(
            [binary, "connector", "tools"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
        )
        data = json.loads(proc.stdout)
    except Exception:
        return "", 0
    tools = data.get("tools") if isinstance(data, dict) else data
    lines = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        name = tool.get("tool_name") or tool.get("name")
        if name:
            lines.append(f"{name}: {tool.get('description') or ''}")
    return "\n".join(lines), len(lines)


def router_line() -> str:
    """The exact line the router injects on a firing turn."""
    line = ("The user invoked the command. Load the `ponytail` skill and follow it. "
            "Argument: what does this skill do. Valid argument values: lite, full, ultra, off.")
    return line


def load_mcp_schemas() -> str:
    """Full tools/list JSON from the WhatsApp MCP server."""
    script = Path(__file__).resolve().parent / "build_catalog.py"
    namespace = {"__name__": "not_main", "__file__": str(script)}
    try:
        exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), namespace)
    except Exception:
        return ""
    probe = namespace.get("probe_mcp_tools")
    configs = namespace.get("mcp_server_configs")
    if not probe or not configs:
        return ""
    for server in configs():
        tools = probe(server)
        if tools:
            return json.dumps(tools, indent=2)
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
