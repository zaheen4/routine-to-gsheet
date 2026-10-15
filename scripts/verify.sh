#!/usr/bin/env bash
# One command to answer "did I break anything?" - run before committing.
#
#   ./scripts/verify.sh
#
# Runs, in order: ruff lint, the Apps Script node test suite, the python test
# suite. Exits non-zero if any step fails. The same script backs the optional
# pre-commit hook (scripts/install_hooks.sh); GitHub Actions stays off because
# Cloudflare blocks the logged-in scrape from datacenter IPs.
set -uo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    echo "error: '$PYTHON' not found. Set up the environment first:" >&2
    echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
    exit 1
fi

failures=0

step() {
    echo
    echo "== $1 =="
}

run() {
    if "$@"; then
        return 0
    fi
    failures=$((failures + 1))
    return 1
}

step "ruff check"
run "$PYTHON" -m ruff check .

step "apps script tests (node)"
if command -v node >/dev/null 2>&1; then
    run node --test "apps_script/tests/**/*.test.js"
else
    echo "SKIPPED: node is not installed (needed for the Apps Script tests)"
fi

step "python tests (pytest)"
run "$PYTHON" -m pytest tests/ -q

echo
if [ "$failures" -eq 0 ]; then
    echo "All checks passed."
else
    echo "$failures check(s) failed."
fi
exit "$failures"
