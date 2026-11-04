#!/usr/bin/env python3
"""Capability router hook.

Reads a hook payload on stdin, writes injected context on stdout.

Two dispatch paths, and nothing else:

  slash path   the prompt starts with "/" -> exact slug lookup
  learned path a learned rule matches the prompt -> inject

Fuzzy catalog matching is deliberately absent. The agent already holds every
skill description in its context and does that matching better than a regex
could. This hook adds only what the agent cannot know: exact slash resolution,
and what the user corrected before.

Context cost: zero permanent. One line, only on a firing turn.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

ROUTING_DIR = Path(os.environ.get("ROUTING_HOME", str(Path.home() / ".routing")))
CATALOG_PATH = ROUTING_DIR / "catalog.json"
STATIC_PATH = ROUTING_DIR / "routes.static.json"
LEARNED_PATH = ROUTING_DIR / "routes.learned.json"
USAGE_PATH = ROUTING_DIR / "usage.jsonl"
QUARANTINE_PATH = ROUTING_DIR / "quarantine.json"

# --------------------------------------------------------------------------
# Tuning
# --------------------------------------------------------------------------

# Built-in mcode slash commands. Never shadowed.
RESERVED_SLUGS = {
    "help", "new", "model", "status", "doctor", "context",
    "skills", "mcp", "usage", "compact", "export",
}

FIRE_THRESHOLD = 0.50       # learned rule must reach this confidence
MATCH_THRESHOLD = 0.60       # pattern coverage needed to count as a match
REPHRASE_THRESHOLD = 0.70    # similarity above this means the user rephrased
IDENTICAL_THRESHOLD = 0.98   # above this the request is the same, not a rephrase
MAX_USAGE_LINES = 2000

CONFIDENCE_START = 0.60
CONFIDENCE_CONFIRM = 0.15
CONFIDENCE_MISS = 0.20
CONFIDENCE_DECAY_PER_DAY = 0.01
CONFIDENCE_MIN = 0.25
CONFIDENCE_MAX = 0.95

# Words that carry no routing signal.
STOPWORDS = {
    "the", "and", "for", "you", "your", "with", "that", "this", "but", "not",
    "are", "was", "were", "has", "have", "had", "can", "could", "would",
    "should", "will", "shall", "its", "it", "in", "on", "at", "to", "of",
    "or", "if", "so", "my", "me", "we", "us", "our", "a", "an", "be", "do",
    "does", "did", "done", "please", "just", "like", "want", "need", "make",
    "get", "give", "use", "using", "used", "then", "than", "them", "they",
    "his", "her", "him", "she", "all", "any", "some", "more", "most", "up",
    "out", "about", "into", "from", "how", "what", "when", "where", "which",
    "who", "why", "is", "am", "as", "by", "also", "too", "very", "can",
    # Generic action verbs. They appear in every request, so they say nothing
    # about which capability fits.
    "search", "find", "show", "list", "open", "read", "write", "create",
    "run", "check", "tell", "update", "fix", "build", "start", "stop",
    "instead", "rather", "okay", "hey", "thanks", "thank", "let", "lets",
    "now", "new", "old", "way", "thing", "stuff", "something", "anything",
}

# Correction phrasings. Group 1 of each pattern is the capability phrase.
# Only explicit corrections count. A bare "use X" is not a correction, it is
# an instruction, and treating it as one would train the router on noise.
CORRECTION_MARKERS = [
    r"\b(?:no|nope|not|wrong|incorrect)\s*[,.]?\s*(?:please\s+)?(?:use|try|go with|open|load|switch to)\s+([^\n.!?;]+)",
    r"\binstead(?:\s+of)?\s+(?:use|try|go with|open|load|switch to)\s+([^\n.!?;]+)",
    r"\brather\s+(?:use|go with|switch to)\s+([^\n.!?;]+)",
    r"\bi\s+meant\s+([^\n.!?;]+)",
    r"\buse\s+([^\n.!?;]{1,60}?)\s+instead\b",
]

# Positive confirmation of the previous route.
CONFIRMATION_PATTERNS = [
    r"\bthat\s+(?:worked|works|is\s+right|is\s+correct)\b",
    r"\bperfect\b",
    r"\bexactly\s+right\b",
    r"\bthat'?s\s+right\b",
    r"\byes\s+that\s+(?:worked|is\s+right|works)\b",
]

WORD_RE = re.compile(r"[a-z0-9_]+")
UNIT_RE = re.compile(r"[a-z0-9][a-z0-9_\-]*")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, payload) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def tokenize(text: str) -> set:
    """Lowercase content words. Stopwords and 1-2 letter noise removed."""
    words = WORD_RE.findall(text.lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def slugify(name: str) -> str:
    """wa_read_messages -> wa-read-messages. Keeps dots and dashes."""
    return re.sub(r"_+", "-", name.strip().lower()).replace(" ", "-")


def slug_for_tool(name: str) -> str:
    """connector__a__b -> connector--a--b. Double underscore becomes a double dash."""
    parts = []
    for chunk in name.strip().lower().split("__"):
        part = re.sub(r"[^a-z0-9]+", "-", chunk).strip("-")
        if part:
            parts.append(part)
    return "--".join(parts)


def slug_candidates(text: str) -> list:
    """Every slug form a free-text phrase could be.

    A double dash is a real separator in this catalog, so it is preserved
    instead of being collapsed into one.
    """
    forms = []
    low = text.strip().lower()
    flat = "--".join(
        re.sub(r"[^a-z0-9]+", "-", part).strip("-") for part in low.split("--")
    ).strip("-")
    if flat:
        forms.append(flat)
    tool = slug_for_tool(low)
    if tool and tool not in forms:
        forms.append(tool)
    return forms


def now() -> int:
    return int(time.time())


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------

def load_catalog() -> dict:
    data = load_json(CATALOG_PATH, {})
    if not isinstance(data, dict):
        return {"version": "0", "records": {}, "build": {}}
    data.setdefault("records", {})
    return data


def catalog_slugs(catalog: dict) -> dict:
    return catalog.get("records", {})


def resolve_capability(text: str, catalog: dict) -> dict | None:
    """Resolve free text to a catalog slug and say where the match landed.

    Returns {"slug", "unit", "start", "end"} or None. The offsets let the
    caller keep the words that follow the capability name, which is where the
    actual request usually lives.
    """
    records = catalog_slugs(catalog)
    if not records or not text:
        return None

    units = [(m.group(0), m.start(), m.end()) for m in UNIT_RE.finditer(text.lower())]
    if not units:
        return None

    count = len(units)
    for size in range(min(4, count), 0, -1):
        for start in range(0, count - size + 1):
            chunk = units[start:start + size]
            phrase = " ".join(part[0] for part in chunk)
            for form in slug_candidates(phrase):
                if form in records:
                    return {
                        "slug": form,
                        "unit": phrase,
                        "start": chunk[0][1],
                        "end": chunk[-1][2],
                    }
    return None


# --------------------------------------------------------------------------
# Injected lines
# --------------------------------------------------------------------------

def inject_line(record: dict, argument: str, invoked: bool, lead: str = None) -> str:
    kind = record.get("kind", "skill")
    title = record.get("title") or record.get("slug", "")
    if lead is None:
        lead = "The user invoked the command." if invoked else "Routing hint."

    if kind == "skill":
        line = f"{lead} Load the `{title}` skill and follow it."
    elif kind == "mcp_tool":
        line = f"{lead} Call the `{title}` tool."
    elif kind == "connector":
        line = f"{lead} Call the `{title}` connector tool."
    elif kind == "cli":
        command = record.get("command") or title
        line = f"{lead} Run: `{command}`"
    else:
        line = f"{lead} Use the `{title}` capability."

    if argument:
        line += f" Argument: {argument}."

    hint = record.get("argument_hint") or ""
    if hint:
        options = [option for option in re.findall(r"[a-z0-9]+", hint.lower())]
        if options:
            line += f" Valid argument values: {', '.join(options)}."
    return line


# --------------------------------------------------------------------------
# Static rules
# --------------------------------------------------------------------------

def load_static() -> dict:
    """Pinned rules the user writes by hand. The router never edits this file."""
    data = load_json(STATIC_PATH, {})
    if not isinstance(data, dict):
        return {"version": 1, "rules": []}
    data.setdefault("rules", [])
    return data


def match_static(prompt: str, static: dict, catalog: dict) -> dict | None:
    """Best pinned rule for this prompt.

    A pinned rule has no confidence and no decay. The user wrote it down, so it
    fires when its keywords are present. Pinned rules win over learned ones.
    """
    records = catalog_slugs(catalog)
    tokens = tokenize(prompt)
    if not tokens:
        return None

    best = None
    best_score = 0.0
    for rule in static.get("rules", []):
        slug = rule.get("slug")
        record = records.get(slug)
        if record is None:
            continue
        keywords = set(rule.get("keywords") or [])
        if not keywords:
            continue
        hits = len(keywords & tokens)
        required = int(rule.get("require", 1) or 1)
        if hits < required:
            continue
        score = hits / len(keywords)
        if score > best_score:
            best_score = score
            best = record
    return best


# --------------------------------------------------------------------------
# Learned rules
# --------------------------------------------------------------------------

def load_learned() -> dict:
    data = load_json(LEARNED_PATH, {})
    if not isinstance(data, dict):
        return {"version": 1, "rules": []}
    data.setdefault("rules", [])
    return data


def apply_decay(rule: dict, stamp: int) -> bool:
    """Unused rules fade. Clamped so a rule never dies completely."""
    last = rule.get("last_confirmed", rule.get("created", stamp))
    days = max(0, (stamp - int(last)) // 86400)
    if not days:
        return False
    before = float(rule.get("confidence", 0))
    rule["confidence"] = max(CONFIDENCE_MIN, before - CONFIDENCE_DECAY_PER_DAY * days)
    return rule["confidence"] != before


def apply_decay_all(learned: dict, stamp: int) -> bool:
    """Decay every rule once per turn. Returns True when something changed."""
    changed = False
    for rule in learned.get("rules", []):
        if apply_decay(rule, stamp):
            changed = True
    return changed


def match_learned(prompt: str, learned: dict, catalog: dict, stamp: int) -> dict | None:
    """Best learned rule for this prompt, if any."""
    records = catalog_slugs(catalog)
    tokens = tokenize(prompt)
    if not tokens:
        return None

    best = None
    best_score = 0.0
    for rule in learned.get("rules", []):
        slug = rule.get("slug")
        record = records.get(slug)
        if record is None:
            continue
        # Slash-only skills never fire automatically. The user must type them.
        if not record.get("auto_routable", True):
            continue
        if float(rule.get("confidence", 0)) < FIRE_THRESHOLD:
            continue
        pattern = set(rule.get("pattern", []))
        if not pattern:
            continue
        coverage = len(pattern & tokens) / len(pattern)
        if coverage < MATCH_THRESHOLD:
            continue
        score = coverage * float(rule.get("confidence", 0))
        if score > best_score:
            best_score = score
            best = rule
    return best


def detect_correction(prompt: str) -> dict | None:
    """Find an explicit correction. Returns the marker span and the phrase."""
    for marker in CORRECTION_MARKERS:
        match = re.search(marker, prompt, flags=re.IGNORECASE)
        if not match:
            continue
        phrase = (match.group(1) or "").strip()
        if 1 < len(phrase) <= 120:
            return {
                "phrase": phrase,
                "marker_start": match.start(),
                "marker_end": match.end(),
            }
    return None


def looks_like_confirmation(prompt: str) -> bool:
    for pattern in CONFIRMATION_PATTERNS:
        if re.search(pattern, prompt, flags=re.IGNORECASE):
            return True
    return False


def last_prompt_tokens(limit: int = 40) -> list:
    """Tokens of the previous prompt.

    A correction usually names the capability but not the task. The task is in
    the prompt before it, so the rule is built from that.
    """
    try:
        lines = USAGE_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("path") in ("none", "learned", "rephrase", "static"):
            tokens = entry.get("tokens") or []
            if tokens:
                return list(tokens)
    return []


def request_pattern(prompt: str, correction: dict, match: dict) -> list:
    """Content words that describe the request, without the capability name."""
    after = correction["phrase"][match["end"]:]
    before = prompt[:correction["marker_start"]]
    tokens = tokenize(before + " " + after)
    if not tokens:
        tokens = last_prompt_tokens()
    return sorted(tokens)[:8]


def learn(prompt: str, correction: dict, match: dict, learned: dict, stamp: int) -> str | None:
    slug = match.get("slug")
    if not slug:
        return None

    pattern = request_pattern(prompt, correction, match)
    if not pattern:
        return None

    rules = learned.setdefault("rules", [])
    for rule in rules:
        if rule.get("slug") == slug and set(rule.get("pattern", [])) == set(pattern):
            rule["confidence"] = min(
                CONFIDENCE_MAX,
                float(rule.get("confidence", 0)) + CONFIDENCE_CONFIRM,
            )
            rule["last_confirmed"] = stamp
            rule["hits"] = int(rule.get("hits", 0)) + 1
            return slug

    rules.append({
        "id": f"r-{abs(hash(tuple(pattern))):x}",
        "slug": slug,
        "pattern": pattern,
        "pattern_raw": " ".join(pattern),
        "confidence": CONFIDENCE_START,
        "hits": 1,
        "confirms": 0,
        "misses": 0,
        "created": stamp,
        "last_confirmed": stamp,
        "source": "correction",
    })
    return slug


# --------------------------------------------------------------------------
# Usage log
# --------------------------------------------------------------------------

def log_usage(entry: dict) -> None:
    try:
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        lines = USAGE_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_USAGE_LINES:
            trimmed = lines[-MAX_USAGE_LINES:]
            USAGE_PATH.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
    except OSError:
        pass


def last_fired(limit: int = 12) -> list:
    try:
        lines = USAGE_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def similarity(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------
# Quarantine
# --------------------------------------------------------------------------

def quarantine_stale(learned: dict, catalog: dict, stamp: int) -> int:
    """Rules whose slug vanished move to quarantine instead of being used."""
    records = catalog_slugs(catalog)
    keep = []
    stale = []
    for rule in learned.get("rules", []):
        if rule.get("slug") in records:
            keep.append(rule)
        else:
            rule["quarantined_at"] = stamp
            rule["quarantine_reason"] = "slug not in catalog"
            stale.append(rule)
    if stale:
        learned["rules"] = keep
        quarantine = load_json(QUARANTINE_PATH, {"rules": []})
        quarantine.setdefault("rules", []).extend(stale)
        save_json(QUARANTINE_PATH, quarantine)
    return len(stale)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def read_stdin() -> str:
    """Read the hook payload as UTF-8 bytes.

    Text mode on Windows decodes stdin with the console code page, which turns
    a UTF-8 byte order mark into three odd characters and mangles any
    non-ASCII prompt. The payload is bytes, so read bytes.
    """
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return sys.stdin.read()
    try:
        data = stream.read()
    except (OSError, ValueError):
        return ""
    return data.decode("utf-8", errors="replace")


def main() -> int:
    raw = read_stdin()
    if not raw.strip():
        return 0
    raw = raw.lstrip("\ufeff")

    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}

    prompt = str(payload.get("prompt") or "")
    if not prompt.strip():
        return 0

    stamp = now()
    catalog = load_catalog()
    learned = load_learned()

    # Guard 3: rules nobody confirms lose confidence. Applied once per turn
    # and persisted, otherwise the fade would be lost on a silent turn.
    if apply_decay_all(learned, stamp):
        save_json(LEARNED_PATH, learned)

    # Guard 4: rules pointing at a slug that no longer exists are quarantined.
    stale = quarantine_stale(learned, catalog, stamp)
    if stale:
        save_json(LEARNED_PATH, learned)

    # ---- slash path -------------------------------------------------------
    stripped = prompt.strip()
    if stripped.startswith("/"):
        body = stripped[1:]
        parts = body.split(None, 1)
        name = parts[0] if parts else ""
        argument = parts[1].strip() if len(parts) > 1 else ""
        name = name.strip().strip(".,:;")

        if name.lower() in RESERVED_SLUGS:
            return 0

        record = None
        for form in slug_candidates(name):
            record = catalog_slugs(catalog).get(form)
            if record is not None:
                break
        if record is None:
            log_usage({
                "ts": stamp, "path": "slash", "slug": None,
                "requested": name, "fired": False, "reason": "unknown slug",
            })
            return 0

        log_usage({
            "ts": stamp, "path": "slash", "slug": record.get("slug"),
            "requested": name, "argument": argument, "fired": True,
        })
        print(inject_line(record, argument, invoked=True))
        return 0

    tokens = tokenize(prompt)

    # ---- correction capture ------------------------------------------------
    correction = detect_correction(prompt)
    if correction:
        match = resolve_capability(correction["phrase"], catalog)
        slug = learn(prompt, correction, match, learned, stamp) if match else None

        # The previous route was wrong. Lower it.
        history = last_fired()
        if history:
            previous = history[-1]
            if previous.get("fired") and previous.get("path") == "learned":
                for rule in learned.get("rules", []):
                    if rule.get("slug") == previous.get("slug"):
                        rule["confidence"] = max(
                            CONFIDENCE_MIN,
                            float(rule.get("confidence", 0)) - CONFIDENCE_MISS,
                        )
                        rule["misses"] = int(rule.get("misses", 0)) + 1
        save_json(LEARNED_PATH, learned)
        log_usage({
            "ts": stamp, "path": "correction", "slug": slug,
            "capability": correction["phrase"], "fired": False,
            "tokens": sorted(tokens),
        })
        return 0

    # ---- confirmation of the previous route --------------------------------
    if looks_like_confirmation(prompt):
        history = last_fired()
        if history and history[-1].get("fired"):
            previous = history[-1]
            for rule in learned.get("rules", []):
                if rule.get("slug") == previous.get("slug"):
                    rule["confidence"] = min(
                        CONFIDENCE_MAX,
                        float(rule.get("confidence", 0)) + CONFIDENCE_CONFIRM,
                    )
                    rule["confirms"] = int(rule.get("confirms", 0)) + 1
                    rule["last_confirmed"] = stamp
            save_json(LEARNED_PATH, learned)
            log_usage({
                "ts": stamp, "path": "confirmation",
                "slug": previous.get("slug"), "fired": False,
            })
            return 0

    # ---- rephrase detection: the last route was wrong ----------------------
    # A repeated identical request is the router working, not a mistake. Only a
    # similar but different request counts as the user trying again.
    history = last_fired()
    if history:
        previous = history[-1]
        if previous.get("fired") and previous.get("path") == "learned":
            prior = set(previous.get("tokens") or [])
            if prior:
                score = similarity(prior, tokens)
                if REPHRASE_THRESHOLD <= score < IDENTICAL_THRESHOLD:
                    for rule in learned.get("rules", []):
                        if rule.get("slug") == previous.get("slug"):
                            rule["confidence"] = max(
                                CONFIDENCE_MIN,
                                float(rule.get("confidence", 0)) - CONFIDENCE_MISS,
                            )
                            rule["misses"] = int(rule.get("misses", 0)) + 1
                    save_json(LEARNED_PATH, learned)
                    log_usage({
                        "ts": stamp, "path": "rephrase", "slug": previous.get("slug"),
                        "fired": False, "reason": "user rephrased",
                    })
                    return 0

    # ---- static path: rules the user pinned by hand ------------------------
    # Pinned rules outrank learned ones. They do not decay and they are never
    # rewritten by the router.
    static = load_static()
    if static.get("rules"):
        record = match_static(prompt, static, catalog)
        if record:
            log_usage({
                "ts": stamp, "path": "static", "slug": record.get("slug"),
                "fired": True, "tokens": sorted(tokens),
            })
            print(inject_line(record, "", invoked=False, lead="Pinned rule."))
            return 0

    # ---- learned path ------------------------------------------------------
    rule = match_learned(prompt, learned, catalog, stamp)
    if rule:
        rule["hits"] = int(rule.get("hits", 0)) + 1
        save_json(LEARNED_PATH, learned)
        record = catalog_slugs(catalog)[rule["slug"]]
        log_usage({
            "ts": stamp, "path": "learned", "slug": rule["slug"],
            "confidence": rule.get("confidence"), "fired": True,
            "tokens": sorted(tokens),
        })
        print(inject_line(record, "", invoked=False))
        return 0

    log_usage({
        "ts": stamp, "path": "none", "slug": None, "fired": False,
        "tokens": sorted(tokens),
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # A broken router must never break the turn.
        raise SystemExit(0)
