#!/bin/bash
# version-sync.sh — PostToolUse hook for Edit|Write
# Ensures pyproject.toml and __init__.py versions stay in sync.
# If one is edited, the other is automatically updated to match.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only trigger on version-related files
case "$FILE_PATH" in
  *pyproject.toml|*__init__.py) ;;
  *) exit 0 ;;
esac

# Derive project dir from the edited file path
case "$FILE_PATH" in
  *pyproject.toml)
    PROJECT_DIR=$(dirname "$FILE_PATH")
    ;;
  *__init__.py)
    # src/rawtowise/__init__.py → go up 3 levels
    PROJECT_DIR=$(cd "$(dirname "$FILE_PATH")/../../.." && pwd)
    ;;
esac

PYPROJECT="$PROJECT_DIR/pyproject.toml"
INIT_PY="$PROJECT_DIR/src/rawtowise/__init__.py"

# Sanity check
[ -f "$PYPROJECT" ] || exit 0
[ -f "$INIT_PY" ] || exit 0

# Extract versions
TOML_VER=$(grep -m1 '^version' "$PYPROJECT" | sed 's/.*"\(.*\)".*/\1/' 2>/dev/null || echo "")
INIT_VER=$(grep -m1 '__version__' "$INIT_PY" | sed 's/.*"\(.*\)".*/\1/' 2>/dev/null || echo "")

if [ -z "$TOML_VER" ] || [ -z "$INIT_VER" ]; then
  exit 0
fi

if [ "$TOML_VER" != "$INIT_VER" ]; then
  case "$FILE_PATH" in
    *pyproject.toml)
      sed -i '' "s/__version__ = \".*\"/__version__ = \"$TOML_VER\"/" "$INIT_PY"
      echo "Version synced: __init__.py → $TOML_VER (from pyproject.toml)"
      ;;
    *__init__.py)
      sed -i '' "s/^version = \".*\"/version = \"$INIT_VER\"/" "$PYPROJECT"
      echo "Version synced: pyproject.toml → $INIT_VER (from __init__.py)"
      ;;
  esac
fi

exit 0
