#!/usr/bin/env bash
# Install engram as a Claude Code plugin.
#
# This is a thin wrapper around the two commands in the README:
#
#   claude plugin marketplace add NoobAIDeveloper/engram
#   claude plugin install engram@engram
#
# It also removes the symlinks that older versions of this script created
# (~/.claude/skills/engram and ~/.claude/commands/kb-*.md), which no longer
# work and would shadow the plugin.
#
# Python dependencies are NOT installed here: the plugin bootstraps its own
# virtualenv the first time a command runs. The only requirement is
# Python 3.10+.
#
# Usage: ./install.sh            install / update
#        ./install.sh --uninstall

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_LINK="$HOME/.claude/skills/engram"
COMMANDS_DIR="$HOME/.claude/commands"

remove_legacy_links() {
  if [ -L "$SKILL_LINK" ]; then
    rm "$SKILL_LINK"
    echo "  removed legacy link $SKILL_LINK"
  fi
  for cmd in "$REPO_DIR"/commands/kb-*.md; do
    target="$COMMANDS_DIR/$(basename "$cmd")"
    # Only remove symlinks — never a real file the user wrote.
    if [ -L "$target" ]; then
      rm "$target"
      echo "  removed legacy link $target"
    fi
  done
}

if ! command -v claude >/dev/null 2>&1; then
  echo "error: the 'claude' CLI was not found. Install Claude Code first:" >&2
  echo "  https://claude.com/claude-code" >&2
  exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
  echo "Removing engram..."
  remove_legacy_links
  claude plugin uninstall engram@engram || true
  echo "Done. Your knowledge bases are untouched."
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1 ||
   ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  cat >&2 <<'EOF'
warning: Python 3.10+ was not found. engram will install, but its commands
need it. Get it with:
  macOS:  xcode-select --install   (or https://www.python.org/downloads/)
  Linux:  sudo apt install python3 python3-venv   (Debian/Ubuntu)
EOF
fi

echo "Installing engram..."
remove_legacy_links
claude plugin marketplace add NoobAIDeveloper/engram || true   # ok if already added
claude plugin marketplace update engram || true
claude plugin install engram@engram || claude plugin update engram@engram

cat <<'EOF'

---------------------------------------------------------------
engram installed.

Next steps:

  1. Open Claude Code in any directory:  claude
  2. Scaffold a KB:                      /engram:kb-init ~/my-kb
  3. Open Claude Code inside it:         cd ~/my-kb && claude
  4. Pull your bookmarks:                /engram:kb-sync
  5. Build the wiki:                     /engram:kb-ingest

Working on engram itself? Run it straight from this checkout:
  claude --plugin-dir .

Uninstall: ./install.sh --uninstall
---------------------------------------------------------------
EOF
