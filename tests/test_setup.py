"""setup.py(vault と作業ディレクトリの紐づけ)のテスト。"""
from __future__ import annotations

import json
import unittest

from helpers import VaultCase, git


class SetupTest(VaultCase):
    def setUp(self) -> None:
        super().setUp()
        self.work = self.tmp / "app"
        self.work.mkdir()
        git(self.work, "init", "-q")

    def config(self) -> dict:
        return json.loads(self.read(".llm-wiki.json", self.work))

    def test_link_writes_config_block_and_exclude(self):
        result = self.setup_script(str(self.work))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        config = self.config()
        self.assertEqual(config["default"], "my-wiki")
        self.assertEqual(config["vaults"]["my-wiki"]["path"], self.vault.as_posix())
        self.assertTrue(config["$schema"].startswith("file:///"))
        agents = self.read("AGENTS.md", self.work)
        self.assertIn("<!-- llm-wiki:begin -->", agents)
        self.assertIn("`my-wiki`(既定)", agents)
        self.assertNotIn(str(self.vault.as_posix()), agents, "AGENTS.md に PC 固有のパスを書かない")
        self.assertEqual(self.read("CLAUDE.md", self.work), "@AGENTS.md\n")
        self.assertFalse((self.work / ".github" / "copilot-instructions.md").exists())
        self.assertEqual(git(self.work, "check-ignore", "-q", ".llm-wiki.json").returncode, 0, "git の無視対象になっていない")
        self.assertEqual(git(self.work, "status", "--porcelain", "--", ".llm-wiki.json").stdout, "")

    def test_link_is_idempotent(self):
        self.setup_script(str(self.work))
        before = {p: self.read(p, self.work) for p in (".llm-wiki.json", "AGENTS.md", "CLAUDE.md")}
        exclude = (self.work / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        result = self.setup_script(str(self.work))
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("更新", result.stdout)
        self.assertEqual(before, {p: self.read(p, self.work) for p in before})
        self.assertEqual(exclude, (self.work / ".git" / "info" / "exclude").read_text(encoding="utf-8"))

    def test_existing_files_are_kept(self):
        (self.work / "AGENTS.md").write_bytes("# 既存の規約\r\n\r\n- 決まり\r\n".encode("utf-8"))
        self.write("CLAUDE.md", "# Claude 向け\n", self.work)
        self.write(".github/copilot-instructions.md", "# Copilot 向け\n", self.work)
        self.assertEqual(self.setup_script(str(self.work)).returncode, 0)
        agents = (self.work / "AGENTS.md").read_bytes()
        self.assertTrue(agents.startswith("# 既存の規約\r\n".encode("utf-8")))
        self.assertNotIn(b"\n", agents.replace(b"\r\n", b""), "CRLF が保たれていない")
        self.assertIn("llm-wiki:begin".encode(), agents)
        self.assertEqual(self.read("CLAUDE.md", self.work), "# Claude 向け\n\n@AGENTS.md\n")
        self.assertIn("llm-wiki:begin", self.read(".github/copilot-instructions.md", self.work))

    def test_copilot_instructions_on_request(self):
        self.setup_script(str(self.work), "--copilot-instructions")
        self.assertIn("llm-wiki:begin", self.read(".github/copilot-instructions.md", self.work))

    def test_second_vault_keeps_default(self):
        self.setup_script(str(self.work))
        result = self.setup_script(str(self.work), "--id", "team-wiki")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config()["default"], "my-wiki")
        self.assertIn("`team-wiki`", self.read("AGENTS.md", self.work))
        self.setup_script(str(self.work), "--id", "team-wiki", "--default")
        self.assertEqual(self.config()["default"], "team-wiki")

    def test_unlink_removes_what_setup_created(self):
        self.setup_script(str(self.work))
        result = self.setup_script(str(self.work), "--unlink")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in (".llm-wiki.json", "AGENTS.md", "CLAUDE.md"):
            self.assertFalse((self.work / name).exists(), name)

    def test_unlink_keeps_other_content(self):
        self.write("AGENTS.md", "# 既存の規約\n", self.work)
        self.setup_script(str(self.work))
        self.setup_script(str(self.work), "--unlink")
        self.assertEqual(self.read("AGENTS.md", self.work), "# 既存の規約\n")

    def test_dry_run_writes_nothing(self):
        result = self.setup_script(str(self.work), "--dry-run")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--dry-run", result.stdout)
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), [".git"])

    def test_enables_hooks_when_vault_is_a_repository(self):
        git(self.vault, "init", "-q")
        self.setup_script(str(self.work))
        self.assertEqual(git(self.vault, "config", "--get", "core.hooksPath").stdout.strip(), ".githooks")

    def test_prompts_for_path_when_missing(self):
        result = self.setup_script(stdin="")
        self.assertEqual(result.returncode, 2, "標準入力が端末でないときは使い方を出して止まる")

    def test_rejects_bad_input(self):
        self.assertEqual(self.setup_script(str(self.tmp / "none")).returncode, 2)
        self.assertEqual(self.setup_script(str(self.vault)).returncode, 2)
        self.assertEqual(self.setup_script(str(self.work), "--id", "Bad Name").returncode, 2)
        self.assertEqual(self.setup_script(str(self.work), "--unlink").returncode, 1)


if __name__ == "__main__":
    unittest.main()
