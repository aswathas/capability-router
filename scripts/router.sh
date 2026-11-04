#!/usr/bin/env bash
# Capability router launcher (POSIX).
#
# Reads the hook payload from stdin, hands it to router.py untouched.
# The router logic lives in router.py. This file is a launcher only, so the
# Windows path and the POSIX path cannot drift apart.

set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROUTER="$DIR/router.py"

if [ -n "${ROUTING_PYTHON:-}" ] && [ -x "${ROUTING_PYTHON}" ]; then
    PY="${ROUTING_PYTHON}"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
else
    exit 0
fi

exec "$PY" "$ROUTER"
