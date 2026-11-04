"""Collect every Instagram MCP log into one folder, with secrets scrubbed.

Run:  python collect_logs.py <outdir>

What goes in:
  audit.log              engine audit trail (publish attempts, blocked paths, confirm codes)
  host.log               shared daemon log (engine start, licence, session state)
  login_failure.txt      a real, reproducible run of the broken login path
  status_after.json      /ig/status snapshot
  health_after.json      /health snapshot
  endpoint_probe.txt     Instagram's key endpoint: the 404 and the working one
  frozen_disasm.txt      the bytecode that actually runs inside ig_daemon.exe
  patched_password.py    the one-file fix
  versions.txt           versions, paths, machine facts
  README.md              written separately

Secrets are never written: the daemon token, the licence key, session cookies and
the password are all replaced or skipped.
"""

import json
import os
import platform
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROAMING = Path(os.environ["APPDATA"])
EVERYHAND = ROAMING / "everyhand"
IG_HOME = ROAMING / "instagram-mcp"
HUB = "http://127.0.0.1:19783"
PKG = Path(r"C:\Users\ADMIN\AppData\Local\Programs\Python\Python313\Lib\site-packages")
IG_PKG = PKG / "aichargelabs_instagram_mcp"
EXTRACT = Path(r"C:\Users\ADMIN\.commandcode\plans\igextract")

SECRET_PATTERNS = [
    (re.compile(r"\b[0-9a-fA-F]{64}\b"), "<REDACTED-64HEX>"),
    (re.compile(r"\bsessionid[\"'\s:=]+[A-Za-z0-9%_\-]{16,}"), "sessionid=<REDACTED>"),
    (re.compile(r"\bcsrftoken[\"'\s:=]+[A-Za-z0-9%_\-]{16,}"), "csrftoken=<REDACTED>"),
    (re.compile(r"(?i)(licenseKey|licenceKey|password)\"?\s*[:=]\s*\"[^\"]{6,}\""), r'"\1": "<REDACTED>"'),
    (re.compile(r"(?i)\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b"), "<REDACTED-KEY>"),
]


def scrub(text: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def write(path: Path, text: str) -> None:
    path.write_text(scrub(text), encoding="utf-8")
    print(f"  wrote {path.name} ({len(text)} chars)")


def hub_get(path: str, header: str = "x-ig-token"):
    token = (EVERYHAND / "store" / "daemon.token").read_text(encoding="utf-8").strip()
    request = urllib.request.Request(HUB + path)
    request.add_header(header, token)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read().decode("utf-8", "replace")
    except Exception as exc:
        return f"ERROR {type(exc).__name__}: {exc}"


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    print("copying log files")
    for source, name in (
        (IG_HOME / "store" / "audit.log", "audit.log"),
        (EVERYHAND / "store" / "host.log", "host.log"),
    ):
        if source.is_file():
            write(out / name, source.read_text(encoding="utf-8", errors="replace"))
        else:
            write(out / name, f"not found: {source}")

    print("running the login path with a throwaway password to capture the failure")
    env = dict(os.environ)
    env["IG_PASSWORD"] = "not-a-real-password-for-reproduction-only"
    exe = IG_PKG / "bin" / "instagram-mcp.exe"
    try:
        result = subprocess.run([str(exe), "login", "--username", "this_aswath",
                                 "--password-env", "IG_PASSWORD"],
                                env=env, capture_output=True, text=True, timeout=300)
        text = (f"command: instagram-mcp.exe login --username this_aswath --password-env IG_PASSWORD\n"
                f"note: IG_PASSWORD held a throwaway string, not the account password\n"
                f"exit code: {result.returncode}\n\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n")
    except Exception as exc:
        text = f"login reproduction failed to run: {type(exc).__name__}: {exc}\n"
    write(out / "login_failure.txt", text)

    print("capturing status snapshots")
    write(out / "status_after.json", hub_get("/ig/status"))
    write(out / "health_after.json", hub_get("/health", "x-everyhand-token"))

    print("probing the Instagram key endpoints")
    probe = []
    for url in ("https://i.instagram.com/api/v1/qe/sync/",
                "https://i.instagram.com/api/v1/accounts/login/"):
        request = urllib.request.Request(url, headers={
            "User-Agent": "Instagram 219.0.0.12.117 Android",
            "X-IG-App-ID": "936619743392459",
        })
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                code, headers = response.status, response.headers
        except urllib.error.HTTPError as exc:
            code, headers = exc.code, exc.headers
        except Exception as exc:
            probe.append(f"{url}\n  ERROR {type(exc).__name__}: {exc}\n")
            continue
        probe.append(f"{url}\n  status: {code}\n")
        for key, value in headers.items():
            if key.lower().startswith("ig-set-password"):
                probe.append(f"  {key}: {value}\n")
    write(out / "endpoint_probe.txt", "".join(probe))

    print("disassembling the frozen module that actually runs")
    frozen = EXTRACT / "ig-daemon.exe_extracted" / "PYZ.pyz_extracted" / "instagrapi" / "mixins" / "password.pyc"
    if frozen.is_file():
        import dis
        import marshal
        data = frozen.read_bytes()
        top = marshal.loads(data[16:])

        def find(target, code, depth=0):
            if code.co_name == target:
                return code
            for const in code.co_consts:
                if hasattr(const, "co_code"):
                    hit = find(target, const, depth + 1)
                    if hit is not None:
                        return hit
            return None

        found = find("password_publickeys", top)
        if found is not None:
            buffer = ["code object: PasswordMixin.password_publickeys\n",
                      dis.code_info(found), "\n",
                      dis.Bytecode(found).dis(), "\n",
                      "consts: %r\n" % (found.co_consts,)]
            write(out / "frozen_disasm.txt", "".join(buffer))
        else:
            write(out / "frozen_disasm.txt", "password_publickeys not found in the frozen module\n")
    else:
        write(out / "frozen_disasm.txt", f"not found: {frozen}\n")

    print("copying the patched source")
    patched = IG_PKG / "bin" / "ig-daemon" / "_internal" / "instagrapi" / "mixins" / "password.py"
    if patched.is_file():
        write(out / "patched_password.py", patched.read_text(encoding="utf-8", errors="replace"))

    print("writing versions.txt")
    versions = []
    versions.append(f"collected: {datetime.now().astimezone().isoformat(timespec='seconds')}")
    versions.append(f"os: {platform.platform()}")
    versions.append(f"python: {sys.version.split()[0]}")
    versions.append(f"product exe: {exe}")
    versions.append(f"product exe size: {exe.stat().st_size if exe.is_file() else 'n/a'}")
    versions.append(f"ig-daemon exe: {IG_PKG / 'bin' / 'ig-daemon' / 'ig-daemon.exe'}")
    versions.append(f"ig home: {IG_HOME}")
    versions.append(f"everyhand home: {EVERYHAND}")
    for dist in sorted(PKG.glob("aichargelabs_*.dist-info")):
        versions.append(f"installed package: {dist.name}")
    versions.append(f"hub version: {json.loads(hub_get('/health', 'x-everyhand-token') or '{}').get('version')}")
    write(out / "versions.txt", "\n".join(versions) + "\n")

    print(f"\nbundle at {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
