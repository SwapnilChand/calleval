#!/usr/bin/env bash
# Install calleval for Claude Code: links the skill so it works from any folder, and puts a `calleval` command on your PATH.
#   ./install.sh            install (symlinks, so `git pull` updates them)
#   ./install.sh --copy     copy the skill instead of linking
#   ./install.sh --uninstall
set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
SKILLS="${CLAUDE_SKILLS_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills}"
BIN="${CALLEVAL_BIN_DIR:-$HOME/.local/bin}"
say() { printf '  %s %s\n' "$1" "$2"; }

if [ "${1:-}" = "--uninstall" ]; then
  rm -rf "$SKILLS/calleval"; rm -f "$BIN/calleval"
  say "✓" "removed $SKILLS/calleval and $BIN/calleval (your agents, cases and runs in $HERE are untouched)"
  exit 0
fi

echo "calleval install"
command -v python3 >/dev/null || { echo "  ✗ python3 is required (3.11+)"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "  ✗ Python 3.11+ is required"; exit 1; }
say "…" "linking the Claude Code skill into $SKILLS"
mkdir -p "$SKILLS" "$BIN"
rm -rf "$SKILLS/calleval"
if [ "${1:-}" = "--copy" ]; then cp -r "$HERE/.claude/skills/calleval" "$SKILLS/calleval"; else ln -s "$HERE/.claude/skills/calleval" "$SKILLS/calleval"; fi
say "✓" "skill installed: $SKILLS/calleval  (in Claude Code, say: \"test my voice agent with calleval\")"
ln -sf "$HERE/calleval.sh" "$BIN/calleval"
say "✓" "command installed: $BIN/calleval  (works from any folder; your work stays in $HERE)"
case ":$PATH:" in *":$BIN:"*) ;; *) say "!" "$BIN is not on your PATH; add it to your shell profile to use \`calleval\` directly" ;; esac
echo; "$HERE/calleval.sh" doctor || true
echo; echo "  next: calleval setup   (pick a stack), then open Claude Code and ask it to test your agent"
