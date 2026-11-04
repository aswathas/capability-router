#!/usr/bin/env python3
"""Log the Instagram MCP in with a browser session cookie.

The packaged password path is broken: instagrapi 3.2.1 fetches the password
encryption key from https://i.instagram.com/api/v1/qe/sync/, Instagram removed
that endpoint, and the login dies with

    TypeError: int() argument must be a string, a bytes-like object or a
    real number, not 'NoneType'

before Instagram ever asks for a 2FA code. Editing the vendored source does not
help, because the running module is the bytecode inside the frozen archive in
ig_daemon.exe, not the source under _internal.

So use the other route the CLI ships:

    instagram-mcp.exe login --sessionid-env IG_SESSIONID

This script reads the `sessionid` cookie straight out of a browser profile,
unwraps it with Windows DPAPI, and hands it to the CLI. The cookie never
leaves this machine and is never printed.

Usage:
    python login_instagram.py                     # scan browsers, then log in
    python login_instagram.py --browser brave     # restrict to one browser
    python login_instagram.py --check             # only report what was found
"""

from __future__ import annotations

import argparse
import ctypes
import glob
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

INSTAGRAM_MCP = Path(
    r"C:\Users\ADMIN\AppData\Local\Programs\Python\Python313\Lib\site-packages"
    r"\aichargelabs_instagram_mcp\bin\instagram-mcp.exe"
)

BROWSERS = {
    "brave": r"C:\Users\ADMIN\AppData\Local\BraveSoftware\Brave-Browser\User Data",
    "chrome": r"C:\Users\ADMIN\AppData\Local\Google\Chrome\User Data",
    "edge": r"C:\Users\ADMIN\AppData\Local\Microsoft\Edge\User Data",
    "vivaldi": r"C:\Users\ADMIN\AppData\Local\Vivaldi\User Data",
    "chromium": r"C:\Users\ADMIN\AppData\Local\Chromium\User Data",
    "opera": r"C:\Users\ADMIN\AppData\Roaming\Opera Software\Opera Stable",
}


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi_decrypt(blob: bytes) -> bytes:
    """Unwrap a Chromium cookie value with Windows DPAPI for this user."""
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    buf_in = ctypes.create_string_buffer(blob, len(blob))
    in_blob = DATA_BLOB(len(blob), ctypes.cast(buf_in, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if not crypt.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None,
                                    0x01, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel.LocalFree(out_blob.pbData)


def cookie_databases(browser: str):
    root = BROWSERS.get(browser)
    if not root or not os.path.isdir(root):
        return
    for profile in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.isdir(profile):
            continue
        for relative in ("Network\\Cookies", "Cookies"):
            path = os.path.join(profile, relative)
            if os.path.isfile(path):
                yield path


def read_sessionid(path: str):
    """Return (sessionid, host) from a browser cookie database, or None."""
    temp = os.path.join(tempfile.gettempdir(), f"igck_{os.getpid()}.sqlite")
    try:
        shutil.copy2(path, temp)
        connection = sqlite3.connect(temp)
        rows = connection.execute(
            "SELECT host_key, name, value, encrypted_value FROM cookies "
            "WHERE name = 'sessionid' AND host_key LIKE '%instagram%'").fetchall()
        connection.close()
    except Exception:
        return None
    finally:
        try:
            os.remove(temp)
        except OSError:
            pass
    for host, _name, plain, encrypted in rows:
        if plain:
            return plain, host
        if encrypted:
            try:
                payload = encrypted[5:] if encrypted[:3] in (b"v10", b"v11") else encrypted
                return dpapi_decrypt(payload).decode("utf-8"), host
            except Exception:
                continue
    return None


def find_sessionid(browser: str):
    for path in cookie_databases(browser):
        hit = read_sessionid(path)
        if hit:
            return hit[0], hit[1], path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", default="", help="brave, chrome, edge, ...")
    parser.add_argument("--check", action="store_true", help="only report, do not log in")
    args = parser.parse_args()

    browsers = [args.browser] if args.browser else list(BROWSERS)
    found = None
    for name in browsers:
        hit = find_sessionid(name)
        if hit:
            found = hit
            print(f"sessionid for {hit[1]} found in {hit[2]}")
            break
        print(f"  {name}: no instagram sessionid")
    if not found:
        print("\nSign in to instagram.com in a browser first, then run this again.")
        return 2
    if args.check:
        return 0

    env = dict(os.environ)
    env["IG_SESSIONID"] = found[0]
    result = subprocess.run([str(INSTAGRAM_MCP), "login", "--sessionid-env", "IG_SESSIONID"],
                            env=env, capture_output=True, text=True, timeout=240)
    print(f"--- exit {result.returncode} ---")
    if result.stdout:
        print(result.stdout[-2500:])
    if result.stderr:
        print("ERR:", result.stderr[-1500:])
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
