#!/usr/bin/env python3
from __future__ import annotations

import os
import re

from hook_utils import (
    INIT_VERSION_RE,
    PYPROJECT_VERSION_RE,
    bump_patch,
    deny,
    json_message,
    load_hook_input,
    read_version,
    repo_root,
    stage_version_files,
    tool_command,
    version_paths,
    write_version,
)


def is_git_commit(command: str) -> bool:
    return bool(re.search(r"(^|[;&|()\s])git(?:\s+-[^\s]+(?:\s+\S+)*)?\s+commit(\s|$)", command))


def destructive_reason(command: str) -> str | None:
    if os.environ.get("RAWTOWISE_ALLOW_DESTRUCTIVE") == "1":
        return None

    checks = [
        (
            r"\bgit\s+reset\s+--hard\b",
            "Blocked git reset --hard. Set RAWTOWISE_ALLOW_DESTRUCTIVE=1 to bypass.",
        ),
        (
            r"\bgit\s+clean\b(?=[^\n]*-[^\s]*f)(?=[^\n]*-[^\s]*d)",
            "Blocked git clean with force+directory flags. Set RAWTOWISE_ALLOW_DESTRUCTIVE=1 to bypass.",
        ),
        (
            r"\bgit\s+checkout\s+--\s+\.",
            "Blocked git checkout -- . because it can discard user changes.",
        ),
        (
            r"\brm\s+-[^\n;&|]*[rf][^\n;&|]*[rf][^\n;&|]*\s+(/|\.|raw/?|wiki/?|\.rtw/?|output/?|\.env)\b",
            "Blocked destructive rm over repository/generated data. Set RAWTOWISE_ALLOW_DESTRUCTIVE=1 to bypass.",
        ),
    ]
    for pattern, reason in checks:
        if re.search(pattern, command):
            return reason
    return None


def auto_bump_patch(root) -> str | None:
    pyproject, init_py = version_paths(root)
    current = read_version(pyproject, PYPROJECT_VERSION_RE)
    if not current or not init_py.exists():
        return None

    next_version = bump_patch(current)
    if not next_version:
        return None

    write_version(pyproject, PYPROJECT_VERSION_RE, next_version)
    write_version(init_py, INIT_VERSION_RE, next_version)
    stage_version_files(root)
    return f"Version auto-bumped: {current} -> {next_version}"


def main() -> int:
    data = load_hook_input()
    command = tool_command(data)
    if not command:
        return 0

    reason = destructive_reason(command)
    if reason:
        deny(reason)
        return 0

    if is_git_commit(command):
        message = auto_bump_patch(repo_root(data))
        if message:
            json_message(message)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
