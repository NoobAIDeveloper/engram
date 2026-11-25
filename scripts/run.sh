#!/usr/bin/env bash
# Self-bootstrapping Python runner for the engram plugin.
# Creates a venv and installs dependencies on first use — the user never
# runs pip themselves.
#
# Usage: bash scripts/run.sh <script-path-relative-to-plugin-root> [args...]
# Example: bash scripts/run.sh scripts/sync.py --kb /path/to/kb
#
# Deliberately not in bin/ and not marked executable: it is only ever run
# explicitly through bash by the plugin's own commands, never as a bare
# command on PATH.
#
# The venv lives OUTSIDE the plugin directory. Claude Code installs each
# plugin version into its own cache directory and deletes old ones, so a
# venv kept next to the code would be rebuilt (or orphaned) on every update.
#   ENGRAM_VENV          explicit override
#   CLAUDE_PLUGIN_DATA   set by Claude Code for hooks; persistent per plugin
#   ~/.local/share/engram  default everywhere else

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: bash scripts/run.sh <script> [args...]" >&2
  exit 64
fi

# Resolve symlinks so this works when bin/ is reached through a link.
SELF="${BASH_SOURCE[0]}"
while [ -L "$SELF" ]; do
  LINK="$(readlink "$SELF")"
  case "$LINK" in
    /*) SELF="$LINK" ;;
    *) SELF="$(dirname "$SELF")/$LINK" ;;
  esac
done
PLUGIN_ROOT="$(cd "$(dirname "$SELF")/.." && pwd)"

VENV="${ENGRAM_VENV:-${CLAUDE_PLUGIN_DATA:-$HOME/.local/share/engram}/venv}"
SCRIPT="$1"
shift

venv_ok() {
  # A venv breaks when the interpreter it was built from disappears (e.g.
  # a Homebrew Python upgrade), so test that it actually runs.
  [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import cryptography' >/dev/null 2>&1
}

if ! venv_ok; then
  if ! command -v python3 >/dev/null 2>&1; then
    cat >&2 <<'EOF'
engram: python3 is not installed.
  macOS:  xcode-select --install   (or https://www.python.org/downloads/)
  Linux:  sudo apt install python3 python3-venv   (Debian/Ubuntu)
EOF
    exit 69
  fi
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "engram: Python 3.10+ is required (found $(python3 -V 2>&1))." >&2
    exit 69
  fi
  echo "engram: setting up Python environment (one-time, ~10s)..." >&2
  rm -rf "$VENV"
  mkdir -p "$(dirname "$VENV")"
  if ! python3 -m venv "$VENV" >&2; then
    echo "engram: could not create a virtualenv. On Debian/Ubuntu run: sudo apt install python3-venv" >&2
    exit 69
  fi
  if ! "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check "cryptography>=42" >&2; then
    echo "engram: failed to install the 'cryptography' package (network problem?). Re-run to retry." >&2
    rm -rf "$VENV"
    exit 69
  fi
  echo "engram: ready." >&2
fi

# Resolve script path relative to plugin root
if [[ "$SCRIPT" != /* ]]; then
  SCRIPT="$PLUGIN_ROOT/$SCRIPT"
fi

exec "$VENV/bin/python" "$SCRIPT" "$@"
