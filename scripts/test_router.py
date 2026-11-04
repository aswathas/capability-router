#!/usr/bin/env python3
"""Regression tests for the capability router.

Runs the router as a real subprocess so the tested contract is the one the
hook uses: JSON payload on stdin, injected context on stdout.

    python test_router.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTER = HERE / "router.py"
CATALOG_SOURCE = Path(os.environ.get("ROUTING_HOME", str(Path.home() / ".routing"))) / "catalog.json"

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append((name, detail))
        print(f"  FAIL  {name}  {detail}")


def run(router_home: Path, prompt: str, cwd: Path = None):
    env = dict(os.environ)
    env["ROUTING_HOME"] = str(router_home)
    payload = json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "test",
        "cwd": str(cwd or Path.home()),
        "prompt": prompt,
    })
    proc = subprocess.run(
        [sys.executable, str(ROUTER)],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )
    return proc.stdout.strip()


def learned(router_home: Path) -> dict:
    path = router_home / "routes.learned.json"
    if not path.is_file():
        return {"rules": []}
    return json.loads(path.read_text(encoding="utf-8"))


def rule_for(router_home: Path, slug: str):
    for rule in learned(router_home).get("rules", []):
        if rule.get("slug") == slug:
            return rule
    return None


def fresh_home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="router-test-"))
    shutil.copy(CATALOG_SOURCE, home / "catalog.json")
    return home


def main() -> int:
    if not CATALOG_SOURCE.is_file():
        print(f"catalog missing: {CATALOG_SOURCE}")
        return 2

    home = fresh_home()
    try:
        run_all(home)
    finally:
        shutil.rmtree(home, ignore_errors=True)

    print()
    print(f"passed {len(PASSED)}   failed {len(FAILED)}")
    for name, detail in FAILED:
        print(f"  FAILED: {name}  {detail}")
    return 1 if FAILED else 0


def run_all(home: Path):
    print("slash path")
    out = run(home, "/ponytail")
    check("slash resolves a skill", "ponytail" in out and "skill" in out, out)
    check("slash says the user invoked it", "user invoked" in out.lower(), out)

    out = run(home, "/ponytail fix the parser")
    check("slash keeps the argument", "fix the parser" in out, out)

    out = run(home, "/status")
    check("builtin command is never shadowed", out == "", out)

    out = run(home, "/help")
    check("builtin help is never shadowed", out == "", out)

    out = run(home, "/gws-gmail--cli")
    check("slash reaches a CLI surface", "Run:" in out and "gws gmail" in out, out)

    out = run(home, "/wa-read-messages")
    check("slash reaches an MCP tool", "wa_read_messages" in out, out)

    out = run(home, "/connector--matrix--batch-text-to-music")
    check("slash reaches a connector tool", "connector__matrix__batch_text_to_music" in out, out)

    out = run(home, "/no-such-capability-xyz")
    check("unknown slash stays silent", out == "", out)

    out = run(home, "please refactor this function")
    check("plain prompt stays silent", out == "", out)

    print("learning path")
    request = "find the invoice in my gmail inbox"
    out = run(home, request)
    check("no rule yet means no injection", out == "", out)

    out = run(home, "no, use gws-gmail instead")
    check("correction stays silent", out == "", out)
    rule = rule_for(home, "gws-gmail")
    check("correction learned the capability", rule is not None, "no rule")
    if rule:
        check("new rule starts at 0.60", abs(rule["confidence"] - 0.60) < 0.001, str(rule))
        check("rule captured the earlier request", "invoice" in rule["pattern"], str(rule["pattern"]))
        check("rule did not capture the correction", "instead" not in rule["pattern"], str(rule["pattern"]))

    out = run(home, request)
    check("learned rule fires on the same request", "gws-gmail" in out, out)

    before = rule_for(home, "gws-gmail")["confidence"]
    for _ in range(3):
        run(home, request)
    after = rule_for(home, "gws-gmail")["confidence"]
    check("guard 1: usage never raises confidence", abs(before - after) < 0.001, f"{before} -> {after}")

    print("guard 2: a miss lowers confidence")
    before = rule_for(home, "gws-gmail")["confidence"]
    out = run(home, "find the invoice in my gmail inbox today")
    after = rule_for(home, "gws-gmail")["confidence"]
    check("miss lowered the rule", after < before, f"{before} -> {after}")
    check("miss did not fire", out == "", out)

    print("guard 3: unused rules decay")
    data = learned(home)
    for rule in data.get("rules", []):
        if rule.get("slug") == "gws-gmail":
            rule["last_confirmed"] = int(time.time()) - 10 * 86400
    (home / "routes.learned.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    before = rule_for(home, "gws-gmail")["confidence"]
    run(home, "something entirely unrelated to this request")
    after = rule_for(home, "gws-gmail")["confidence"]
    check("decay lowered the rule", after < before, f"{before} -> {after}")

    print("confirmation")
    home2 = fresh_home()
    try:
        run(home2, "find the invoice in my gmail inbox")
        run(home2, "no, use gws-gmail instead")
        before = rule_for(home2, "gws-gmail")["confidence"]
        run(home2, "find the invoice in my gmail inbox")
        fired = rule_for(home2, "gws-gmail")["confidence"]
        run(home2, "that worked")
        after = rule_for(home2, "gws-gmail")["confidence"]
        check("confirmation raised confidence", after > fired, f"{fired} -> {after}")
        check("usage before confirmation did not", abs(fired - before) < 0.001, f"{before} -> {fired}")
    finally:
        shutil.rmtree(home2, ignore_errors=True)

    print("guard 4: stale slugs are quarantined")
    home3 = fresh_home()
    try:
        run(home3, "find the invoice in my gmail inbox")
        run(home3, "no, use gws-gmail instead")
        catalog = json.loads((home3 / "catalog.json").read_text(encoding="utf-8"))
        catalog["records"].pop("gws-gmail", None)
        (home3 / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
        run(home3, "find the invoice in my gmail inbox")
        check("stale rule was removed", rule_for(home3, "gws-gmail") is None, "rule still there")
        quarantine = home3 / "quarantine.json"
        check("stale rule was quarantined", quarantine.is_file(), "no quarantine file")
        if quarantine.is_file():
            entries = json.loads(quarantine.read_text(encoding="utf-8")).get("rules", [])
            check("quarantine names the slug", any(r.get("slug") == "gws-gmail" for r in entries), str(entries))
    finally:
        shutil.rmtree(home3, ignore_errors=True)

    print("slash-only skills never fire automatically")
    home4 = fresh_home()
    try:
        run(home4, "write a test for the parser")
        run(home4, "no, use tdd instead")
        rule = rule_for(home4, "tdd")
        check("correction still learned tdd", rule is not None, "no rule")
        out = run(home4, "write a test for the parser")
        check("slash-only skill did not auto fire", out == "", out)
    finally:
        shutil.rmtree(home4, ignore_errors=True)

    print("static path")
    home5 = fresh_home()
    try:
        (home5 / "routes.static.json").write_text(json.dumps({
            "version": 1,
            "rules": [{"slug": "gws-gmail", "keywords": ["invoice", "mailbox"], "require": 1}],
        }), encoding="utf-8")
        out = run(home5, "check the mailbox for the invoice")
        check("static rule fires", "gws-gmail" in out, out)
        check("static rule says pinned", "Pinned rule" in out, out)
        out = run(home5, "something unrelated entirely")
        check("static rule stays quiet", out == "", out)
        check("static file was not rewritten",
              json.loads((home5 / "routes.static.json").read_text(encoding="utf-8"))["rules"][0]["slug"] == "gws-gmail",
              "static file changed")
    finally:
        shutil.rmtree(home5, ignore_errors=True)

    print("pinned rule outranks a learned rule")
    home6 = fresh_home()
    try:
        (home6 / "routes.static.json").write_text(json.dumps({
            "version": 1,
            "rules": [{"slug": "gws-docs", "keywords": ["invoice"], "require": 1}],
        }), encoding="utf-8")
        run(home6, "get the invoice")
        run(home6, "no, use gws-gmail instead")
        out = run(home6, "get the invoice")
        check("pinned rule wins", "gws-docs" in out and "gws-gmail" not in out, out)
    finally:
        shutil.rmtree(home6, ignore_errors=True)

    print("robustness")
    env = dict(os.environ)
    env["ROUTING_HOME"] = str(home)
    proc = subprocess.run(
        [sys.executable, str(ROUTER)],
        input="not json at all",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    check("garbage input does not crash", proc.returncode == 0, proc.stderr[-200:])

    proc = subprocess.run(
        [sys.executable, str(ROUTER)],
        input="",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    check("empty input does not crash", proc.returncode == 0, proc.stderr[-200:])


if __name__ == "__main__":
    raise SystemExit(main())
