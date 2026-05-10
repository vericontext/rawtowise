#!/usr/bin/env python3
from __future__ import annotations

from hook_utils import json_message, load_hook_input, repo_root, sync_versions, tool_command


def version_source_from_patch(command: str) -> str:
    touched_pyproject = "pyproject.toml" in command
    touched_init = "src/rawtowise/__init__.py" in command or "__init__.py" in command
    if touched_init and not touched_pyproject:
        return "init"
    return "pyproject"


def main() -> int:
    data = load_hook_input()
    root = repo_root(data)
    command = tool_command(data)
    message = sync_versions(root, version_source_from_patch(command))
    if message:
        json_message(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
