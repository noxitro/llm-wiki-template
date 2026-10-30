"""テストの共通部品: vault-template を一時フォルダに写して、スクリプトを実行する。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "vault-template"
NOW = "2026-10-28T12:00:00+09:00"

PAGE = textwrap.dedent("""\
    ---
    type: Finding
    title: SDK のリンクに要るライブラリ
    description: SDK 3.2 の静的リンクには foo.lib と bar.lib が要る。
    tags: [build]
    created: 2026-10-26
    generated: { by: claude-code/claude-opus-5-5, at: 2026-10-26T14:30:00+09:00 }
    verified:
      - { by: claude-code/claude-opus-5-5, at: 2026-10-26T14:30:00+09:00 }
    confidence: ◎
    sources:
      - { id: sdk-link, resource: /raw/2026-10-26-sdk-link.md }
    ---
    # SDK のリンクに要るライブラリ

    **要点**: SDK 3.2 の静的リンクには foo.lib と bar.lib が要る。[^sdk-link]

    - 確かめた日と環境: 2026-10-26

    [^sdk-link]: raw/2026-10-26-sdk-link.md
    """)

RAW = textwrap.dedent("""\
    ---
    type: Evidence
    title: bar.lib 無しでリンクした出力
    date: 2026-10-26
    kind: command
    ---
    # bar.lib 無しでリンクした出力

    ```text
    error LNK2019
    ```
    """)

INDEX_LINE = "* [SDK のリンクに要るライブラリ](wiki/build/sdk-link.md) - SDK 3.2 の静的リンクには foo.lib と bar.lib が要る。\n"


def run(*args: str, cwd: Path | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", input=stdin, env=env)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return run("git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
               "-c", "core.autocrlf=false", *args, cwd=cwd)


class VaultCase(unittest.TestCase):
    """一時フォルダに vault を作るテストの土台。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="llm-wiki-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = self.tmp / "my-wiki"
        shutil.copytree(TEMPLATE, self.vault)

    def write(self, rel: str, text: str, root: Path | None = None) -> Path:
        path = (root or self.vault) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as f:  # write_text(newline=) は 3.10 以降
            f.write(text)
        return path

    def read(self, rel: str, root: Path | None = None) -> str:
        return ((root or self.vault) / rel).read_text(encoding="utf-8")

    def add_valid_page(self) -> None:
        self.write("wiki/build/sdk-link.md", PAGE)
        self.write("raw/2026-10-26-sdk-link.md", RAW)
        self.write("index.md", self.read("index.md") + "\n" + INDEX_LINE)

    def lint(self, *args: str, root: Path | None = None) -> subprocess.CompletedProcess:
        vault = root or self.vault
        return run(sys.executable, str(vault / "scripts" / "wiki_lint.py"), "--root", str(vault), "--now", NOW, *args)

    def setup_script(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        return run(sys.executable, str(self.vault / "scripts" / "setup.py"), *args, stdin=stdin)

    def assertFinding(self, result: subprocess.CompletedProcess, level: str, fragment: str) -> None:
        lines = [line for line in result.stdout.splitlines() if line.startswith(level) and fragment in line]
        self.assertTrue(lines, f"{level} に「{fragment}」が無い:\n{result.stdout}{result.stderr}")

    def assertClean(self, result: subprocess.CompletedProcess) -> None:
        bad = [line for line in result.stdout.splitlines() if line.startswith(("ERROR", "WARN"))]
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(bad, [], result.stdout)
