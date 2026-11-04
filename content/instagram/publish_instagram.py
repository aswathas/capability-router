#!/usr/bin/env python3
"""Publish the carousel to Instagram through the everyhand Instagram MCP.

The engine is the aichargelabs Instagram MCP, served by the everyhand hub on
127.0.0.1. Auth is the product token from the hub store, sent as `x-ig-token`.

    python publish_instagram.py                 # publish the album
    python publish_instagram.py --status        # just show the connection state
    python publish_instagram.py --caption-only  # check the caption without posting

Upload paths must live inside an allowed folder: the hub's store/media, temp,
Pictures, Videos, Downloads, Desktop, Music, or whatever IG_UPLOAD_DIRS names.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HUB = "http://127.0.0.1:19783"
TOKEN_FILE = Path.home() / "AppData" / "Roaming" / "everyhand" / "store" / "daemon.token"
SLIDES = Path.home() / "Pictures" / "capability-router-carousel"
CAPTION = SLIDES / "caption.md"


def token() -> str:
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def call(path: str, payload=None, method=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        HUB + path,
        data=data,
        method=method or ("POST" if data is not None else "GET"),
        headers={"x-ig-token": token(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"ok": False, "error": raw[:400]}
    except Exception as exc:
        return 0, {"ok": False, "error": str(exc)}


def show_status() -> dict:
    status, data = call("/ig/status")
    print(f"HTTP {status}")
    for key in ("connection", "username", "user_id", "version", "last_error", "session_file"):
        if key in data:
            print(f"  {key:14} {data[key]}")
    for key in ("publishes", "sends", "reads"):
        if key in data:
            print(f"  {key:14} {json.dumps(data[key])}")
    license_data = data.get("license") or {}
    if license_data:
        print(f"  license         {json.dumps(license_data)}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--caption-only", action="store_true")
    parser.add_argument("--confirm", default="", help="the 6-digit code the account owner sees")
    parser.add_argument("--caption", default="")
    parser.add_argument("--slides-dir", default=str(SLIDES))
    args = parser.parse_args()

    if args.status:
        show_status()
        return 0

    slides = sorted(Path(args.slides_dir).glob("slide-*.png"))
    if not slides:
        print(f"no slides in {args.slides_dir}", file=sys.stderr)
        return 2
    if len(slides) < 2 or len(slides) > 10:
        print(f"album needs 2 to 10 paths, found {len(slides)}", file=sys.stderr)
        return 2

    if args.caption:
        caption = args.caption
    elif CAPTION.is_file():
        caption = CAPTION.read_text(encoding="utf-8").strip()
    else:
        caption = ""

    print(f"slides   {len(slides)}")
    for slide in slides:
        print(f"         {slide}")
    print(f"caption  {len(caption)} chars")

    if args.caption_only:
        print("\n--- caption ---")
        print(caption)
        return 0

    payload = {
        "kind": "album",
        "caption": caption,
        "paths": [str(slide) for slide in slides],
    }
    if args.confirm:
        payload["confirm"] = args.confirm

    status, data = call("/ig/publish", payload)
    print(f"\nPOST /ig/publish -> HTTP {status}")
    trimmed = dict(data)
    preview = trimmed.pop("preview", None)
    if preview:
        trimmed["preview"] = {
            "action": preview.get("action"),
            "files": preview.get("files"),
            "caption_chars": len(preview.get("caption") or ""),
        }
    print(json.dumps(trimmed, indent=2)[:1600])

    if data.get("ok"):
        print("\nPublished.")
        print(json.dumps(data, indent=2)[:800])
        return 0

    if data.get("needs_confirm"):
        preview = data.get("preview") or {}
        print("\n--- preview ---")
        print(f"  action : {preview.get('action')}")
        for name in preview.get("files", []):
            print(f"  file   : {name}")
        print(f"  caption: {len(preview.get('caption') or '')} chars")
        print(
            "\nThe account owner already has this request's 6-digit code on their screen.\n"
            "It is in no reply and no file. Never guess it.\n"
            "Read it from the screen, then run:\n"
            "  python publish_instagram.py --confirm <code>"
        )
        return 3

    error = str(data.get("error", ""))
    if "logged_out" in error or "not connected" in error or "no session" in error:
        print(
            "\nThe engine has no Instagram session.\n"
            "Log in once, then re-run this command:\n"
            "  instagram-mcp.exe login --username <your-handle>\n"
            "The publish route is confirmed working; only the session is missing.",
            file=sys.stderr,
        )
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
