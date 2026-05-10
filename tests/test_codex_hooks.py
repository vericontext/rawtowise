from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK_DIR = Path(__file__).resolve().parents[1] / ".codex" / "hooks"


def run_hook(script: str, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK_DIR / script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def write_version_files(project: Path, py_version: str, init_version: str) -> None:
    (project / "src" / "rawtowise").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "rawtowise"\nversion = "{py_version}"\n',
        encoding="utf-8",
    )
    (project / "src" / "rawtowise" / "__init__.py").write_text(
        f'"""RawToWise."""\n\n__version__ = "{init_version}"\n',
        encoding="utf-8",
    )


class CodexHookTests(unittest.TestCase):
    def test_pre_tool_use_blocks_destructive_git_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "cwd": tmp,
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git reset --hard"},
            }

            result = run_hook("pre_tool_use.py", payload)

            self.assertEqual(result.returncode, 0)
            output = json.loads(result.stdout)
            specific = output["hookSpecificOutput"]
            self.assertEqual(specific["permissionDecision"], "deny")
            self.assertIn("git reset --hard", specific["permissionDecisionReason"])

    def test_pre_tool_use_auto_bumps_patch_before_git_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
            write_version_files(project, "0.2.10", "0.2.10")

            payload = {
                "cwd": str(project),
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m release"},
            }

            result = run_hook("pre_tool_use.py", payload)

            self.assertEqual(result.returncode, 0)
            self.assertIn("0.2.11", (project / "pyproject.toml").read_text(encoding="utf-8"))
            self.assertIn(
                "0.2.11",
                (project / "src" / "rawtowise" / "__init__.py").read_text(encoding="utf-8"),
            )
            self.assertIn("Version auto-bumped", json.loads(result.stdout)["systemMessage"])

    def test_post_tool_use_syncs_version_from_pyproject_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write_version_files(project, "0.2.11", "0.2.10")

            payload = {
                "cwd": str(project),
                "hook_event_name": "PostToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Update File: pyproject.toml\n"},
            }

            result = run_hook("post_tool_use.py", payload)

            self.assertEqual(result.returncode, 0)
            init_text = (project / "src" / "rawtowise" / "__init__.py").read_text(
                encoding="utf-8"
            )
            self.assertIn('__version__ = "0.2.11"', init_text)
            self.assertIn("Version synced", json.loads(result.stdout)["systemMessage"])

    def test_post_tool_use_syncs_version_from_init_when_only_init_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write_version_files(project, "0.2.10", "0.2.11")

            payload = {
                "cwd": str(project),
                "hook_event_name": "PostToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Update File: src/rawtowise/__init__.py\n",
                },
            }

            result = run_hook("post_tool_use.py", payload)

            self.assertEqual(result.returncode, 0)
            pyproject_text = (project / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn('version = "0.2.11"', pyproject_text)
            self.assertIn("Version synced", json.loads(result.stdout)["systemMessage"])


if __name__ == "__main__":
    unittest.main()
