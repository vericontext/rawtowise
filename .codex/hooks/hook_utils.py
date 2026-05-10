from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

PYPROJECT_VERSION_RE = re.compile(r'(?m)^version\s*=\s*"([^"]+)"')
INIT_VERSION_RE = re.compile(r'(?m)^__version__\s*=\s*"([^"]+)"')


def load_hook_input() -> dict[str, Any]:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def repo_root(data: dict[str, Any]) -> Path:
    cwd = Path(data.get("cwd") or os.getcwd()).resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=True,
        )
        return Path(result.stdout.strip()).resolve()
    except Exception:
        for candidate in (cwd, *cwd.parents):
            if (
                (candidate / "pyproject.toml").exists()
                and (candidate / "src" / "rawtowise" / "__init__.py").exists()
            ):
                return candidate
        return Path(__file__).resolve().parents[2]


def tool_command(data: dict[str, Any]) -> str:
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command") or tool_input.get("cmd")
    return command if isinstance(command, str) else ""


def read_version(path: Path, pattern: re.Pattern[str]) -> str | None:
    if not path.exists():
        return None
    match = pattern.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def write_version(path: Path, pattern: re.Pattern[str], version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(lambda match: match.group(0).replace(match.group(1), version), text, count=1)
    if count == 0 or updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def version_paths(root: Path) -> tuple[Path, Path]:
    return root / "pyproject.toml", root / "src" / "rawtowise" / "__init__.py"


def parse_semver(version: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump_patch(version: str) -> str | None:
    parsed = parse_semver(version)
    if not parsed:
        return None
    major, minor, patch = parsed
    return f"{major}.{minor}.{patch + 1}"


def sync_versions(root: Path, source: str = "pyproject") -> str | None:
    pyproject, init_py = version_paths(root)
    py_ver = read_version(pyproject, PYPROJECT_VERSION_RE)
    init_ver = read_version(init_py, INIT_VERSION_RE)
    if not py_ver or not init_ver or py_ver == init_ver:
        return None

    if source == "init":
        changed = write_version(pyproject, PYPROJECT_VERSION_RE, init_ver)
        return f"Version synced: pyproject.toml -> {init_ver}" if changed else None

    changed = write_version(init_py, INIT_VERSION_RE, py_ver)
    return f"Version synced: __init__.py -> {py_ver}" if changed else None


def stage_version_files(root: Path) -> None:
    pyproject, init_py = version_paths(root)
    subprocess.run(
        ["git", "-C", str(root), "add", str(pyproject), str(init_py)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def json_message(message: str) -> None:
    print(json.dumps({"systemMessage": message}))


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
