#!/usr/bin/env python3
"""Build the capability catalog.

Reads every capability source this machine exposes and writes one catalog to
``~/.routing/catalog.json``. The router reads that file at match time. It never
scans skills itself, because scanning on every prompt would be slow and would
put catalog size into the hot path.

Sources
  skills      SKILL.md frontmatter across the skill roots
  mcp         tools/list from each configured stdio MCP server
  connectors  mcode-tools connector tools
  cli         service list from the gws CLI

Collision rules
  same slug + same content hash   one record, keep the richest description
  same slug + different content   keep both, suffix with the kind tag
  reserved builtin names          excluded, reported

Usage
  python build_catalog.py [--out PATH] [--report PATH]
                           [--no-mcp] [--no-connectors] [--no-cli]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - fallback parser below
    yaml = None


ROUTING_DIR = Path(os.environ.get("ROUTING_HOME", str(Path.home() / ".routing")))
DEFAULT_CATALOG = ROUTING_DIR / "catalog.json"
DEFAULT_REPORT = ROUTING_DIR / "catalog-report.json"

# Built-in mcode slash commands. Never shadowed.
RESERVED_SLUGS = {
    "help", "new", "model", "status", "doctor", "context",
    "skills", "mcp", "usage", "compact", "export",
}

# Skill roots, highest priority first. A lower-priority root only wins a plain
# slug when the higher-priority root does not have that slug at all.
SKILL_ROOTS = [
    Path.home() / ".minimax" / "skills",
    Path.home() / ".agents" / "skills",
    Path.home() / ".claude" / "skills",
    Path.home() / ".commandcode" / "skills",
]

PLUGIN_DIR = Path.home() / ".minimax" / "plugins"

MAX_DESCRIPTION = 400
MAX_SOURCE_SCAN_BYTES = 8192

KIND_PRIORITY = {"skill": 0, "mcp_tool": 1, "connector": 2, "cli": 3}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def slug_for_skill(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return text.strip("-")


def slug_for_tool(name: str) -> str:
    """wa_read_messages -> wa-read-messages. connector__a__b -> connector--a--b."""
    parts = []
    for chunk in name.strip().lower().split("__"):
        part = re.sub(r"[^a-z0-9]+", "-", chunk).strip("-")
        if part:
            parts.append(part)
    return "--".join(parts)


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def clip(text: str, limit: int = MAX_DESCRIPTION) -> str:
    text = collapse(text)
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


def content_hash(title: str, description: str) -> str:
    payload = json.dumps(
        {"title": title, "description": collapse(description)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def run_command(command, timeout=60) -> tuple:
    """Run a command, return (stdout, stderr, returncode)."""
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        return proc.stdout, proc.stderr, proc.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc), -1


# --------------------------------------------------------------------------
# Frontmatter
# --------------------------------------------------------------------------

def parse_simple_yaml(block: str) -> dict:
    """Minimal YAML frontmatter reader. Handles the fields skills actually use."""
    data = {}
    lines = block.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1] in (" ", "\t"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value in (">", "|", ">-", "|-"):
            chunks = []
            while index < len(lines) and (not lines[index].strip() or lines[index][:1] in (" ", "\t")):
                chunks.append(lines[index].strip())
                index += 1
            data[key] = collapse(" ".join(chunks))
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1]
            data[key] = [part.strip().strip("'\"") for part in inner.split(",") if part.strip()]
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        data[key] = value
    return data


def parse_frontmatter(text: str) -> dict:
    match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match:
        return {}
    block = match.group(1)
    if yaml is not None:
        try:
            loaded = yaml.safe_load(block)
        except Exception:
            loaded = None
        if isinstance(loaded, dict):
            return loaded
    return parse_simple_yaml(block)


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "on")
    return bool(value)


# --------------------------------------------------------------------------
# Source: skills
# --------------------------------------------------------------------------

def skill_roots() -> list:
    roots = [root for root in SKILL_ROOTS if root.is_dir()]
    if PLUGIN_DIR.is_dir():
        for plugin in sorted(PLUGIN_DIR.iterdir()):
            candidate = plugin / "skills"
            if candidate.is_dir():
                roots.append(candidate)
    return roots


def collect_skills() -> tuple:
    records = []
    errors = []
    seen_files = 0
    for rank, root in enumerate(skill_roots()):
        try:
            paths = sorted(root.rglob("SKILL.md"))
        except OSError as exc:
            errors.append(f"{root}: {exc}")
            continue
        for path in paths:
            seen_files += 1
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    head = handle.read(MAX_SOURCE_SCAN_BYTES)
            except OSError as exc:
                errors.append(f"{path}: {exc}")
                continue
            meta = parse_frontmatter(head)
            name = meta.get("name")
            if not isinstance(name, str) or not name.strip():
                name = path.parent.name
            name = name.strip()
            description = clip(str(meta.get("description") or ""))
            hint = meta.get("argument-hint") or meta.get("argument_hint") or ""
            if not isinstance(hint, str):
                hint = str(hint)
            records.append({
                "kind": "skill",
                "slug": slug_for_skill(name),
                "title": name,
                "description": description,
                "argument_hint": hint.strip(),
                "auto_routable": not truthy(meta.get("disable-model-invocation")),
                "source": str(path).replace("\\", "/"),
                "root_rank": rank,
                "hash": content_hash(name, description),
            })
    return records, {"files_scanned": seen_files, "errors": errors[:20]}


# --------------------------------------------------------------------------
# Source: MCP servers
# --------------------------------------------------------------------------

def mcp_server_configs() -> list:
    """Every stdio MCP server the machine is configured to run."""
    servers = []
    seen = set()

    def add(name, spec):
        if not isinstance(spec, dict):
            return
        command = spec.get("command")
        if not command or not isinstance(command, str):
            return
        if spec.get("type") not in (None, "stdio"):
            return
        key = (name, command, tuple(spec.get("args") or []))
        if key in seen:
            return
        seen.add(key)
        servers.append({
            "name": name,
            "command": command,
            "args": [str(a) for a in (spec.get("args") or [])],
            "env": spec.get("env") if isinstance(spec.get("env"), dict) else {},
        })

    manifests = []
    if PLUGIN_DIR.is_dir():
        for plugin in sorted(PLUGIN_DIR.iterdir()):
            for name in ("servers.mcp.json", ".mcp.json"):
                candidate = plugin / name
                if candidate.is_file():
                    manifests.append(candidate)
    for candidate in (Path.home() / ".mcp.json", Path.home() / ".minimax" / "mcp.json"):
        if candidate.is_file():
            manifests.append(candidate)

    for manifest in manifests:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        block = data.get("mcpServers") if isinstance(data, dict) else None
        if not isinstance(block, dict):
            continue
        for name, spec in block.items():
            add(str(name), spec)

    manual = ROUTING_DIR / "mcp-servers.json"
    if manual.is_file():
        try:
            data = json.loads(manual.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = []
        for entry in data if isinstance(data, list) else []:
            if isinstance(entry, dict) and entry.get("command"):
                add(str(entry.get("name") or "manual"), entry)
    return servers


def probe_mcp_tools(server: dict, timeout=25.0) -> list:
    """Call tools/list on a stdio MCP server over raw JSON-RPC."""
    env = dict(os.environ)
    for key, value in (server.get("env") or {}).items():
        env[str(key)] = str(value)

    try:
        proc = subprocess.Popen(
            [server["command"], *server["args"]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError:
        return []

    lines = []
    finished = threading.Event()

    def reader():
        try:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    lines.append(line)
        except (OSError, ValueError):
            pass
        finished.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    def send(obj):
        try:
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError):
            pass

    send({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "capability-router", "version": "1.0.0"},
        },
    })
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    finished.wait(timeout)
    try:
        proc.kill()
    except OSError:
        pass

    tools = []
    for line in lines:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict) or message.get("id") != 2:
            continue
        for tool in (message.get("result") or {}).get("tools", []):
            if not isinstance(tool, dict):
                continue
            name = tool.get("name")
            if not name:
                continue
            tools.append({
                "kind": "mcp_tool",
                "slug": slug_for_tool(str(name)),
                "title": str(name),
                "description": clip(str(tool.get("description") or "")),
                "argument_hint": "",
                "auto_routable": True,
                "source": f"mcp:{server['name']}",
                "hash": content_hash(str(name), str(tool.get("description") or "")),
            })
    return tools


def collect_mcp() -> tuple:
    records = []
    errors = []
    for server in mcp_server_configs():
        tools = probe_mcp_tools(server)
        if not tools:
            errors.append(f"{server['name']}: no tools returned")
        records.extend(tools)
    return records, {"servers": len(mcp_server_configs()), "errors": errors}


# --------------------------------------------------------------------------
# Source: connectors
# --------------------------------------------------------------------------

def collect_connectors() -> tuple:
    binary = shutil.which("mcode-tools")
    if not binary:
        return [], {"errors": ["mcode-tools not on PATH"]}
    stdout, stderr, code = run_command([binary, "connector", "tools"], timeout=120)
    if code != 0:
        return [], {"errors": [f"exit {code}: {stderr[:200]}"]}
    try:
        data = json.loads(stdout)
    except ValueError:
        return [], {"errors": ["connector output is not JSON"]}
    tools = data.get("tools") if isinstance(data, dict) else data
    records = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        name = tool.get("tool_name") or tool.get("name")
        if not name:
            continue
        name = str(name)
        description = str(tool.get("description") or "")
        records.append({
            "kind": "connector",
            "slug": slug_for_tool(name),
            "title": name,
            "description": clip(description),
            "argument_hint": "",
            "auto_routable": True,
            "source": "connector",
            "hash": content_hash(name, description),
        })
    return records, {"errors": []}


# --------------------------------------------------------------------------
# Source: CLI services
# --------------------------------------------------------------------------

CLI_SOURCES = [
    {
        "binary": "gws",
        "prefix": "gws",
        "kind": "cli",
        "label": "gws",
        "summary": "Google Workspace CLI service.",
    },
]


def parse_gws_services(help_text: str) -> list:
    services = []
    inside = False
    for line in help_text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("SERVICES:"):
            inside = True
            continue
        if inside:
            if not stripped:
                if services:
                    break
                continue
            match = re.match(r"^([a-z][a-z0-9\-]*)\s{2,}(.*)$", stripped)
            if match:
                services.append((match.group(1), match.group(2).strip()))
    return services


def collect_cli() -> tuple:
    records = []
    errors = []
    for source in CLI_SOURCES:
        binary = shutil.which(source["binary"])
        if not binary:
            errors.append(f"{source['binary']}: not on PATH")
            continue
        stdout, stderr, code = run_command([binary, "--help"], timeout=60)
        if code != 0:
            errors.append(f"{source['binary']}: exit {code}")
            continue
        services = parse_gws_services(stdout) if source["binary"] == "gws" else []
        if not services:
            errors.append(f"{source['binary']}: no service list parsed")
            continue
        for service, description in services:
            title = f"{source['label']} {service}"
            records.append({
                "kind": source["kind"],
                "slug": slug_for_tool(f"{source['prefix']}_{service}"),
                "title": title,
                "description": clip(description or source["summary"]),
                "argument_hint": "",
                "auto_routable": True,
                "command": f"{source['label']} {service}",
                "source": f"cli:{source['binary']}",
                "hash": content_hash(title, description or source["summary"]),
            })
    return records, {"errors": errors}


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def merge_skill(first: dict, second: dict) -> dict:
    """Same skill name, different copy. One capability, one record.

    The name is the identity, so mirrored copies never become separate slugs.
    The richest description wins. `auto_routable` is the strictest of the two,
    because a copy that disables model invocation is a safety instruction.
    """
    merged = dict(first)
    if len(second.get("description", "")) > len(first.get("description", "")):
        merged["description"] = second["description"]
    if not merged.get("argument_hint") and second.get("argument_hint"):
        merged["argument_hint"] = second["argument_hint"]
    merged["auto_routable"] = bool(first.get("auto_routable")) and bool(second.get("auto_routable"))
    return merged


def resolve_collisions(records: list) -> tuple:
    """Assign final slugs, merge mirrors, report collisions."""
    skills = [rec for rec in records if rec.get("kind") == "skill"]
    others = [rec for rec in records if rec.get("kind") != "skill"]

    by_slug = {}
    collisions = []
    reserved = []
    duplicates = 0
    mirrors = []

    # Skills first. Same name is the same capability, so copies merge.
    for record in sorted(skills, key=lambda rec: (rec.get("root_rank", 99), rec.get("source", ""))):
        slug = record.get("slug") or ""
        if not slug:
            continue
        if slug in RESERVED_SLUGS:
            reserved.append({"slug": slug, "title": record.get("title"), "source": record.get("source")})
            continue
        existing = by_slug.get(slug)
        if existing is None:
            by_slug[slug] = record
            continue
        if existing["hash"] == record["hash"]:
            duplicates += 1
        else:
            mirrors.append({
                "slug": slug,
                "title": record.get("title"),
                "source": record.get("source"),
                "hash": record["hash"],
            })
        by_slug[slug] = merge_skill(existing, record)

    # Tools and CLI surfaces. These share slugs with skills often enough that
    # they get a kind suffix instead of silently overwriting.
    for record in sorted(others, key=lambda rec: (KIND_PRIORITY.get(rec.get("kind"), 9), rec.get("slug", ""))):
        slug = record.get("slug") or ""
        if not slug:
            continue
        if slug in RESERVED_SLUGS:
            reserved.append({"slug": slug, "title": record.get("title"), "source": record.get("source")})
            continue
        existing = by_slug.get(slug)
        if existing is None:
            by_slug[slug] = record
            continue
        if existing["hash"] == record["hash"]:
            duplicates += 1
            continue
        alternative = f"{slug}--{record.get('kind', 'x')}"
        counter = 2
        while alternative in by_slug:
            alternative = f"{slug}--{record.get('kind', 'x')}-{counter}"
            counter += 1
        moved = dict(record)
        moved["slug"] = alternative
        moved["slash"] = "/" + alternative
        moved["disambiguated_from"] = slug
        by_slug[alternative] = moved
        collisions.append({
            "slug": alternative,
            "disambiguated_from": slug,
            "kind": record.get("kind"),
            "title": record.get("title"),
            "source": record.get("source"),
        })

    return by_slug, collisions, reserved, duplicates, mirrors


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the capability catalog.")
    parser.add_argument("--out", default=str(DEFAULT_CATALOG))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--no-mcp", action="store_true")
    parser.add_argument("--no-connectors", action="store_true")
    parser.add_argument("--no-cli", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    started = time.time()
    records = []
    source_report = {}

    skill_records, skill_report = collect_skills()
    records.extend(skill_records)
    source_report["skills"] = skill_report

    if not args.no_mcp:
        mcp_records, mcp_report = collect_mcp()
        records.extend(mcp_records)
        source_report["mcp"] = mcp_report
    else:
        source_report["mcp"] = {"skipped": True}

    if not args.no_connectors:
        connector_records, connector_report = collect_connectors()
        records.extend(connector_records)
        source_report["connectors"] = connector_report
    else:
        source_report["connectors"] = {"skipped": True}

    if not args.no_cli:
        cli_records, cli_report = collect_cli()
        records.extend(cli_records)
        source_report["cli"] = cli_report
    else:
        source_report["cli"] = {"skipped": True}

    by_slug, collisions, reserved, duplicates, mirrors = resolve_collisions(records)

    catalog_records = {}
    for slug, record in sorted(by_slug.items()):
        entry = {
            "slug": slug,
            "kind": record.get("kind", "skill"),
            "title": record.get("title", slug),
            "description": record.get("description", ""),
            "slash": "/" + slug,
            "argument_hint": record.get("argument_hint", ""),
            "auto_routable": bool(record.get("auto_routable", True)),
            "source": record.get("source", ""),
        }
        if record.get("command"):
            entry["command"] = record["command"]
        if record.get("disambiguated_from"):
            entry["disambiguated_from"] = record["disambiguated_from"]
        catalog_records[slug] = entry

    catalog = {
        "version": hashlib.sha256(
            json.dumps(sorted(catalog_records), ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16],
        "built": int(time.time()),
        "count": len(catalog_records),
        "records": catalog_records,
    }

    write_json(Path(args.out), catalog)

    report = {
        "built": catalog["built"],
        "version": catalog["version"],
        "count": len(catalog_records),
        "by_kind": {},
        "duplicates_merged": duplicates,
        "mirrors_merged": len(mirrors),
        "mirror_variants": mirrors,
        "collisions": collisions,
        "reserved_excluded": reserved,
        "sources": source_report,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
    for record in catalog_records.values():
        report["by_kind"][record["kind"]] = report["by_kind"].get(record["kind"], 0) + 1
    write_json(Path(args.report), report)

    if not args.quiet:
        print(f"catalog   {args.out}")
        print(f"records   {len(catalog_records)}  {report['by_kind']}")
        print(f"merged    {duplicates} identical copies, {len(mirrors)} mirrored variants")
        print(f"collided  {len(collisions)} disambiguated slugs")
        print(f"reserved  {len(reserved)} builtin names excluded")
        print(f"elapsed   {report['elapsed_ms']} ms")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
