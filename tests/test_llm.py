from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rawtowise.config import Config, LLMConfig
from rawtowise.llm import call_llm, resolve_provider


class LLMBackendTests(unittest.TestCase):
    def test_auto_provider_prefers_active_codex_session(self):
        config = Config(llm=LLMConfig(provider="auto"))
        env = {
            "CODEX_THREAD_ID": "thread",
            "CLAUDE_CODE_SSE_PORT": "1234",
        }

        with patch.dict(os.environ, env, clear=True), patch("shutil.which") as which:
            which.side_effect = lambda name: f"/usr/local/bin/{name}" if name in {"codex", "claude"} else None

            self.assertEqual(resolve_provider(config), "codex")

    def test_auto_provider_uses_anthropic_when_key_is_available(self):
        config = Config(llm=LLMConfig(provider="auto"))

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=True), patch(
            "shutil.which", return_value=None
        ):
            self.assertEqual(resolve_provider(config), "anthropic")

    def test_claude_code_backend_uses_cli_without_forwarding_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            bin_dir = project / "bin"
            bin_dir.mkdir()
            log_path = project / "env.log"
            fake_claude = bin_dir / "claude"
            fake_claude.write_text(
                "#!/bin/sh\n"
                f"printf '%s' \"$ANTHROPIC_API_KEY\" > {log_path}\n"
                "cat >/dev/null\n"
                "printf 'fake claude response\\n'\n",
                encoding="utf-8",
            )
            fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IXUSR)

            config = Config(
                llm=LLMConfig(provider="claude-code", claude_code_model=""),
                project_dir=project,
            )
            env = {
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "ANTHROPIC_API_KEY": "sk-should-not-leak",
            }

            with patch.dict(os.environ, env, clear=True):
                result = call_llm(
                    config,
                    system="Return a fixed response.",
                    user="hello",
                )

            self.assertEqual(result, "fake claude response")
            self.assertEqual(log_path.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
