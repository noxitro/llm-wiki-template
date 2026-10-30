"""wiki_lint.py(機械の点検)のテスト。"""
from __future__ import annotations

import importlib.util
import sys
import unittest

from helpers import PAGE, TEMPLATE, VaultCase, git

spec = importlib.util.spec_from_file_location("wiki_lint", TEMPLATE / "scripts" / "wiki_lint.py")
wiki_lint = importlib.util.module_from_spec(spec)
sys.modules["wiki_lint"] = wiki_lint  # dataclass が自分のモジュールを引けるように
spec.loader.exec_module(wiki_lint)


class ParseYamlTest(unittest.TestCase):
    def parse(self, text: str):
        return wiki_lint.parse_yaml(text.split("\n"))

    def test_forms_used_by_the_schema(self):
        fm = self.parse(
            "type: Finding\n"
            "title: \"題名: コロン入り\"\n"
            "tags: [a, b]\n"
            "generated: { by: claude-code/opus, at: 2026-10-26T14:30:00+09:00 }\n"
            "verified:\n"
            "  - { by: human:alice, at: 2026-10-27T09:00:00Z }\n"
            "sources:\n"
            "  - id: x\n"
            "    resource: /raw/a.md\n"
            "watch:\n"
            "- repo@abc123:src/a.cpp  # コメント\n"
            "nested:\n"
            "  k: v\n"
        )
        self.assertEqual(fm["title"], "題名: コロン入り")
        self.assertEqual(fm["tags"], ["a", "b"])
        self.assertEqual(fm["generated"], {"by": "claude-code/opus", "at": "2026-10-26T14:30:00+09:00"})
        self.assertEqual(fm["verified"], [{"by": "human:alice", "at": "2026-10-27T09:00:00Z"}])
        self.assertEqual(fm["sources"], [{"id": "x", "resource": "/raw/a.md"}])
        self.assertEqual(fm["watch"], ["repo@abc123:src/a.cpp"])
        self.assertEqual(fm["nested"], {"k": "v"})

    def test_rejects_unsupported_forms(self):
        for text in ("a: |\n  x", "a: [b", "a: { b }", "  a: b", "a: b\na: c", "a: b\n    c: d"):
            with self.subTest(text=text), self.assertRaises(wiki_lint.YamlError):
                self.parse(text)


class LintTest(VaultCase):
    def test_empty_template_is_clean(self):
        self.assertClean(self.lint())

    def test_valid_page_is_clean(self):
        self.add_valid_page()
        result = self.lint()
        self.assertClean(result)
        self.assertIn("ページ 1 件", result.stdout)

    def test_every_md_needs_type(self):
        self.write("notes.md", "# 型の無いメモ\n")
        self.assertFinding(self.lint(), "ERROR", "frontmatter が無い")
        self.write("notes.md", "---\ntitle: x\n---\n# x\n")
        self.assertFinding(self.lint(), "ERROR", "type が無いか空")

    def test_dot_folders_are_outside_the_bundle(self):
        self.write(".obsidian/notes.md", "# 型の無いメモ\n")
        self.assertClean(self.lint())

    def test_page_frontmatter_errors(self):
        self.add_valid_page()
        cases = [
            ("confidence: ◎", "confidence: △", "confidence が ◎ か ○ でない"),
            ("resource: /raw/2026-10-26-sdk-link.md", "resource: https://example.com", "/raw/ で始まっていない"),
            ("resource: /raw/2026-10-26-sdk-link.md", "resource: /raw/none.md", "根拠ファイルが無い"),
            ("at: 2026-10-26T14:30:00+09:00 }\nverified", "at: 2026-10-26 }\nverified", "generated.at が時差つき"),
            ("by: claude-code/claude-opus-5-5, at: 2026-10-26T14:30:00+09:00 }\nconfidence", "by: alice, at: 2026-10-26T14:30:00+09:00 }\nconfidence", "verified.by が"),
            ("created: 2026-10-26", "created: 2026-10-27", "generated.at が created より前"),
            ("type: Finding", "type: Evidence", "type: Evidence は使わない"),
            ("tags: [build]\n", "tags: [build]\nstatus: old\n", "status が draft"),
        ]
        for old, new, message in cases:
            with self.subTest(message=message):
                self.assertIn(old, PAGE)
                self.write("wiki/build/sdk-link.md", PAGE.replace(old, new, 1))
                result = self.lint()
                self.assertEqual(result.returncode, 1)
                self.assertFinding(result, "ERROR", message)

    def test_body_errors(self):
        self.add_valid_page()
        cases = [
            ("[^sdk-link]\n", "[^other]\n", "脚注 [^other]"),
            ("- 確かめた日と環境: 2026-10-26", "- 関係: [[別のページ]]", "[[別のページ]] の形は使わない"),
            ("- 確かめた日と環境: 2026-10-26", "- 関係: [無い](missing.md)", "リンク先が無い"),
            ("- 確かめた日と環境: 2026-10-26", "- 関係: [外](../../../outside.md)", "バンドルの外"),
            ("- 確かめた日と環境: 2026-10-26", "- 推定: ▲ たぶん速い", "推定のラベル「▲」"),
            ("**要点**:", "要点:", "**要点** の行が無い"),
        ]
        for old, new, message in cases:
            with self.subTest(message=message):
                self.write("wiki/build/sdk-link.md", PAGE.replace(old, new, 1))
                self.assertFinding(self.lint(), "ERROR", message)

    def test_links_resolve_relative_and_absolute_and_count_inbound(self):
        self.add_valid_page()
        other = PAGE.replace("SDK のリンクに要るライブラリ", "SDK の入れ方").replace(
            "- 確かめた日と環境: 2026-10-26",
            "- 関係: [リンク](sdk-link.md) と [ルートから](/wiki/build/sdk-link.md) と [空白入り](<sdk-link.md>)")
        self.write("wiki/build/sdk-install.md", other)
        self.write("index.md", self.read("index.md") + "* [SDK の入れ方](wiki/build/sdk-install.md) - SDK 3.2 の静的リンクには foo.lib と bar.lib が要る。\n")
        result = self.lint()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFinding(result, "WARN", "wiki/build/sdk-install.md  孤立ページ")
        self.assertNotIn("sdk-link.md  孤立ページ", result.stdout)

    def test_index_must_list_every_page_once(self):
        self.add_valid_page()
        self.write("index.md", self.read("index.md").replace("* [SDK", "* [別名", 1))
        self.assertFinding(self.lint(), "WARN", "題名がページの title")
        self.write("index.md", '---\nokf_version: "0.2"\n---\n# Wiki\n')
        self.assertFinding(self.lint(), "ERROR", "index.md に載っていない")

    def test_sub_index_must_not_have_frontmatter(self):
        self.write("wiki/index.md", "---\nokf_version: \"0.2\"\n---\n# x\n")
        self.assertFinding(self.lint(), "ERROR", "ルート以外の index.md に frontmatter")

    def test_log_format(self):
        good = "# Log\n\n## 2026-10-28\n* **Ingest** 14:05 二つ目\n  * 作成: x\n* **Schema** 10:00 一つ目\n\n## 2026-10-27\n* **Lint** 09:00 前日\n"
        self.write("log.md", good)
        self.assertClean(self.lint())
        cases = [
            (good.replace("## 2026-10-27", "## 2026-10-29"), "ERROR", "新しい順になっていない"),
            (good.replace("## 2026-10-27", "## 2026-10-28"), "ERROR", "同じ日付が 2 回"),
            (good.replace("## 2026-10-27", "## [2026-10-27 09:00] lint | 古い形"), "ERROR", "## YYYY-MM-DD"),
            (good.replace("* **Lint** 09:00 前日", "* 前日に点検した"), "ERROR", "Ingest|Lint|Schema"),
            (good.replace("10:00 一つ目", "15:00 一つ目"), "WARN", "時刻が新しい順"),
        ]
        for text, level, message in cases:
            with self.subTest(message=message):
                self.write("log.md", text)
                self.assertFinding(self.lint(), level, message)

    def test_raw_errors(self):
        self.add_valid_page()
        self.write("raw/2026-10-26-sdk-link.md", self.read("raw/2026-10-26-sdk-link.md").replace("type: Evidence", "type: Finding"))
        self.assertFinding(self.lint(), "ERROR", "type が Evidence でない")
        self.write("raw/2026-10-26-sdk-link.md", self.read("raw/2026-10-26-sdk-link.md").replace("type: Finding", "type: Evidence").replace("kind: command", "kind: chat"))
        self.assertFinding(self.lint(), "ERROR", "kind が command")
        self.write("raw/2026-10-27-orphan.md", "---\ntype: Evidence\ndate: 2026-10-27\nkind: doc\n---\n# x\n")
        self.assertFinding(self.lint(), "WARN", "どのページの sources にも挙がっていない")

    def test_stale_after(self):
        self.add_valid_page()
        self.write("wiki/build/sdk-link.md", PAGE.replace("confidence: ◎", "confidence: ◎\nstale_after: 2026-10-01T00:00:00Z"))
        self.assertFinding(self.lint(), "WARN", "要再確認: stale_after")
        self.assertFinding(self.lint("--fail-on-stale"), "ERROR", "要再確認: stale_after")

    def test_secrets(self):
        self.add_valid_page()
        self.write("raw/2026-10-26-sdk-link.md", self.read("raw/2026-10-26-sdk-link.md") + "token ghp_" + "a" * 36 + "\n")
        self.assertFinding(self.lint(), "ERROR", "GitHub トークン")


class HistoryTest(VaultCase):
    def commit_all(self, repo):
        git(repo, "add", "-A")
        result = git(repo, "commit", "-qm", "snapshot")
        self.assertEqual(result.returncode, 0, result.stderr)

    def check_history(self, repo, vault):
        self.add_valid_page()
        self.write("log.md", "# Log\n\n## 2026-10-27\n* **Ingest** 09:00 一つ目\n")
        self.commit_all(repo)
        self.assertClean(self.lint("--base", "HEAD", root=vault))

        self.write("log.md", "# Log\n\n## 2026-10-28\n* **Lint** 10:00 二つ目\n\n## 2026-10-27\n* **Ingest** 09:00 一つ目\n")
        self.assertClean(self.lint("--base", "HEAD", root=vault))

        self.write("log.md", "# Log\n\n## 2026-10-27\n* **Ingest** 09:00 書き換えた\n")
        self.assertFinding(self.lint("--base", "HEAD", root=vault), "ERROR", "log.md は足すだけ")

        self.write("log.md", "# Log\n\n## 2026-10-27\n* **Ingest** 09:00 一つ目\n")
        self.write("raw/2026-10-26-sdk-link.md", self.read("raw/2026-10-26-sdk-link.md") + "追記\n")
        self.assertFinding(self.lint("--base", "HEAD", root=vault), "ERROR", "raw/2026-10-26-sdk-link.md  既存の根拠ファイルが変えられている")

        git(repo, "checkout", "-q", "--", ".")
        self.write("AGENTS.md", self.read("AGENTS.md") + "\n追記\n")
        self.assertFinding(self.lint("--base", "HEAD", root=vault), "WARN", "**Schema** の項目が足されていない")

    def test_vault_at_repository_root(self):
        git(self.vault, "init", "-q")
        self.check_history(self.vault, self.vault)

    def test_vault_in_a_subfolder(self):
        git(self.tmp, "init", "-q")
        self.check_history(self.tmp, self.vault)


if __name__ == "__main__":
    unittest.main()
