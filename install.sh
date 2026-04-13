#!/usr/bin/env bash
# Install the twitter-wiki skill into ~/.claude so Claude Code can find it.
#
# Creates:
#   ~/.claude/skills/twitter-wiki     symlink to this repo
#   ~/.claude/commands/kb-*.md        symlinks to commands/kb-*.md
#
# Idempotent: safe to re-run. Use ./install.sh --uninstall to remove.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_LINK="$HOME/.claude/skills/twitter-wiki"
COMMANDS_DIR="$HOME/.claude/commands"

uninstall() {
  echo "Removing twitter-wiki skill..."
  [ -L "$SKILL_LINK" ] && rm "$SKILL_LINK" && echo "  removed $SKILL_LINK"
  for cmd in "$REPO_DIR"/commands/kb-*.md; do
    name="$(basename "$cmd")"
    target="$COMMANDS_DIR/$name"
    if [ -L "$target" ]; then
      rm "$target"
      echo "  removed $target"
    fi
  done
  echo "Done."
  exit 0
}

[ "${1:-}" = "--uninstall" ] && uninstall

# Preflight
command -v uv >/dev/null 2>&1 || {
  echo "error: 'uv' is required. Install it from https://docs.astral.sh/uv/" >&2
  exit 1
}

mkdir -p "$HOME/.claude/skills" "$COMMANDS_DIR"

# Skill symlink
if [ -e "$SKILL_LINK" ] || [ -L "$SKILL_LINK" ]; then
  if [ -L "$SKILL_LINK" ] && [ "$(readlink "$SKILL_LINK")" = "$REPO_DIR" ]; then
    echo "✓ skill already linked"
  else
    echo "error: $SKILL_LINK exists and does not point to $REPO_DIR" >&2
    echo "  run: rm $SKILL_LINK  (and re-run this script)" >&2
    exit 1
  fi
else
  ln -s "$REPO_DIR" "$SKILL_LINK"
  echo "✓ linked skill → $SKILL_LINK"
fi

# Command symlinks
for cmd in "$REPO_DIR"/commands/kb-*.md; do
  name="$(basename "$cmd")"
  target="$COMMANDS_DIR/$name"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$cmd" ]; then
    continue
  fi
  if [ -e "$target" ]; then
    echo "  skipping $name — $target exists and is not our symlink" >&2
    continue
  fi
  ln -s "$cmd" "$target"
  echo "✓ linked command → $target"
done

cat <<EOF

twitter-wiki installed. Next:

  claude
  > /kb-init ~/my-kb     # scaffold a KB
  > cd ~/my-kb && claude # start a fresh session inside it
  > /kb-sync             # pull bookmarks from your browser
  > /kb-ingest           # cluster + synthesize the wiki

To uninstall: ./install.sh --uninstall
EOF
