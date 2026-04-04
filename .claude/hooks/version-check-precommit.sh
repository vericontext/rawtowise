#!/bin/bash
# version-check-precommit.sh — PreToolUse hook for Bash
# Blocks git commit if pyproject.toml and __init__.py versions are out of sync.

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only check on git commit commands
case "$COMMAND" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

# Use cwd from hook input, fall back to CLAUDE_PROJECT_DIR or .
PROJECT_DIR=$(echo "$INPUT" | jq -r '.cwd // empty')
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"

PYPROJECT="$PROJECT_DIR/pyproject.toml"
INIT_PY="$PROJECT_DIR/src/rawtowise/__init__.py"

[ -f "$PYPROJECT" ] || exit 0
[ -f "$INIT_PY" ] || exit 0

TOML_VER=$(grep -m1 '^version' "$PYPROJECT" | sed 's/.*"\(.*\)".*/\1/' 2>/dev/null || echo "")
INIT_VER=$(grep -m1 '__version__' "$INIT_PY" | sed 's/.*"\(.*\)".*/\1/' 2>/dev/null || echo "")

if [ -z "$TOML_VER" ] || [ -z "$INIT_VER" ]; then
  exit 0
fi

if [ "$TOML_VER" != "$INIT_VER" ]; then
  echo "Version mismatch! pyproject.toml=$TOML_VER, __init__.py=$INIT_VER. Sync them before committing." >&2
  exit 2  # Block the action
fi

exit 0
