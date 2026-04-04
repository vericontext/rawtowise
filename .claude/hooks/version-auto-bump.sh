#!/bin/bash
# version-auto-bump.sh — PreToolUse hook for Bash
# Auto-bumps patch version on every git commit.
# e.g., 0.2.0 → 0.2.1

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only trigger on git commit
case "$COMMAND" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

PROJECT_DIR=$(echo "$INPUT" | jq -r '.cwd // empty')
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"

PYPROJECT="$PROJECT_DIR/pyproject.toml"
INIT_PY="$PROJECT_DIR/src/rawtowise/__init__.py"

[ -f "$PYPROJECT" ] || exit 0
[ -f "$INIT_PY" ] || exit 0

# Get current version
CURRENT=$(grep -m1 '^version' "$PYPROJECT" | sed 's/.*"\(.*\)".*/\1/')
[ -z "$CURRENT" ] && exit 0

# Bump patch: 0.2.0 → 0.2.1
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
PATCH=$((PATCH + 1))
NEW="$MAJOR.$MINOR.$PATCH"

# Update both files
sed -i '' "s/^version = \".*\"/version = \"$NEW\"/" "$PYPROJECT"
sed -i '' "s/__version__ = \".*\"/__version__ = \"$NEW\"/" "$INIT_PY"

# Stage the bumped files so they're included in the commit
cd "$PROJECT_DIR"
git add "$PYPROJECT" "$INIT_PY"

echo "Version auto-bumped: $CURRENT → $NEW"
exit 0
