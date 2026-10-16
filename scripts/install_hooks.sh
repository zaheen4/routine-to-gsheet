#!/usr/bin/env bash
# Install (or remove) a pre-commit hook that runs scripts/verify.sh.
#
#   ./scripts/install_hooks.sh            # install
#   ./scripts/install_hooks.sh --uninstall
#
# Why a local hook instead of CI: the scrape only works from a residential IP
# (Cloudflare blocks GitHub's datacenter IPs), so the pipeline is never run on
# a runner. The hook is the local safety net for the checks that do not need
# the live portal: ruff and the python test suite.
set -euo pipefail

cd "$(dirname "$0")/.."

HOOK=".git/hooks/pre-commit"

if [ "${1:-}" = "--uninstall" ]; then
    if [ -f "$HOOK" ] && grep -q "scripts/verify.sh" "$HOOK"; then
        rm "$HOOK"
        echo "removed $HOOK"
    else
        echo "nothing to remove (no verify.sh hook in $HOOK)"
    fi
    exit 0
fi

if [ ! -d .git ]; then
    echo "error: .git not found - run this from a git checkout" >&2
    exit 1
fi

if [ -f "$HOOK" ] && ! grep -q "scripts/verify.sh" "$HOOK"; then
    echo "error: $HOOK already exists and is not ours; not overwriting it." >&2
    echo "Review it, then remove the file (or run with --uninstall) and retry." >&2
    exit 1
fi

cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
# Installed by scripts/install_hooks.sh - remove with that script's --uninstall.
exec "$(git rev-parse --show-toplevel)/scripts/verify.sh"
EOF
chmod +x "$HOOK"
echo "installed $HOOK"
echo "Commits now run ruff + pytest. Bypass once with: git commit --no-verify"
