#!/usr/bin/env python3
"""LLM Wiki の機械の点検。

AGENTS.md の規約に沿っているかを、LLM の判断を挟まずに検査する。
標準ライブラリだけで動く(Python 3.9 以上)。

    python scripts/wiki_lint.py                     # 手元で点検する
    python scripts/wiki_lint.py --base origin/main  # raw/ と log.md の履歴の点検も、この ref と比べて行う

終了コード: 0 = エラーなし / 1 = エラーあり / 2 = 使い方の誤り
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOG_HEADING_RE = re.compile(r"^## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] (ingest|lint|schema) \| \S.*$")
INDEX_LINE_RE = re.compile(r"^- \[\[[^\]]+\]\] — \S.*$")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
CONFIDENCE_LINE_RE = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*)?確度(?:\*\*)?\s*[::]")
CONFIDENCE_RE = re.compile(r"確度(?:\*\*)?\s*[::]\s*(?:\*\*)?([◎○])")
FORBIDDEN_LABELS = ("△", "▲")
WATCH_RE = re.compile(r"^([^@\s]+)@([0-9a-fA-F]{4,40}):(.+)$")
RAW_KINDS = {"command", "file", "doc"}
ZERO_SHA_RE = re.compile(r"^0+$")

SECRET_PATTERNS = [
    ("AWS アクセスキー", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub トークン", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("GitLab トークン", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}")),
    ("API キー(sk-)", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("Slack トークン", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("Google API キー", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("秘密鍵", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def add(self, level: str, where: str, message: str) -> None:
        self.items.append((level, where, message))

    def count(self, level: str) -> int:
        return sum(1 for lv, _, _ in self.items if lv == level)

    def print(self) -> None:
        order = {ERROR: 0, WARN: 1, INFO: 2}
        for level, where, message in sorted(self.items, key=lambda i: (order[i[0]], i[1])):
            print(f"{level:<5}  {where}  {message}" if where else f"{level:<5}  {message}")
        print(f"\nエラー {self.count(ERROR)} 件 / 警告 {self.count(WARN)} 件 / 情報 {self.count(INFO)} 件")


def read_text(path: Path) -> str:
    # UTF-8 でないファイルは check_encoding が報告するので、ここでは止まらずに読む
    return path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")


def parse_list(value: str) -> list[str]:
    value = value.strip()
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
    except json.JSONDecodeError:
        pass
    inner = value[1:-1] if value.startswith("[") and value.endswith("]") else value
    return [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]


def parse_frontmatter(text: str) -> tuple[dict | None, str, int]:
    """(frontmatter, 本文, 本文の開始行番号) を返す。frontmatter が無ければ None。

    規約で使う形だけを読む: `key: value` / `key: [..]` / `key:` の下の `- item`(字下げは有っても無くてもよい)。
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text, 1
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None, text, 1
    fm: dict = {}
    list_key = None  # 値が空の `key:` の直後だけ、`- item` をその key のリストとして読む
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and list_key is not None:
            fm[list_key].append(item.group(1).strip().strip("'\""))
            continue
        list_key = None
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not kv:
            continue
        key, value = kv.group(1), kv.group(2).strip()
        if value.startswith("["):
            fm[key] = parse_list(value)
        elif value == "":
            fm[key] = []
            list_key = key
        else:
            fm[key] = value.strip("'\"")
    return fm, "\n".join(lines[end + 1:]), end + 2


def strip_code(text: str) -> str:
    """フェンスとインラインのコードを空白に置き換える(行番号は保つ)。"""
    out, in_fence = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else re.sub(r"`[^`]*`", "", line))
    return "\n".join(out)


def as_list(value) -> list[str]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def check_pages(root: Path, report: Report) -> tuple[dict[str, Path], dict[str, set[str]], dict[str, list[str]]]:
    """ページを点検し、(ページ名 → パス, ページ名 → 張っているリンク先, raw パス → 引用しているページ) を返す。"""
    wiki = root / "wiki"
    pages: dict[str, Path] = {}
    for path in sorted(wiki.rglob("*.md")) if wiki.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        if path.stem in pages:
            report.add(ERROR, rel, f"ページ名「{path.stem}」が {pages[path.stem].relative_to(root).as_posix()} と重複している([[リンク]] が解決できない)")
            continue
        pages[path.stem] = path

    links: dict[str, set[str]] = {}
    cited: dict[str, list[str]] = defaultdict(list)
    for name, path in pages.items():
        rel = path.relative_to(root).as_posix()
        text = read_text(path)
        fm, body, body_line = parse_frontmatter(text)
        if fm is None:
            report.add(ERROR, rel, "frontmatter(--- で囲んだ created / updated / sources)が無い")
            fm = {}
        else:
            dates = {}
            for key in ("created", "updated"):
                value = fm.get(key)
                if not isinstance(value, str) or not DATE_RE.match(value):
                    report.add(ERROR, rel, f"{key} が YYYY-MM-DD の日付でない")
                    continue
                try:
                    dates[key] = dt.date.fromisoformat(value)
                except ValueError:
                    report.add(ERROR, rel, f"{key} が実在しない日付({value})")
            if len(dates) == 2 and dates["updated"] < dates["created"]:
                report.add(ERROR, rel, "updated が created より前になっている")
            sources = as_list(fm.get("sources"))
            if not sources:
                report.add(ERROR, rel, "sources が空(根拠の raw/ ファイルを 1 つ以上挙げる)")
            for src in sources:
                if not src.startswith("raw/"):
                    report.add(ERROR, rel, f"sources に raw/ の外を挙げている: {src}(URL は raw/ の根拠ファイルに書く)")
                elif not (root / src).is_file():
                    report.add(ERROR, rel, f"sources の根拠ファイルが無い: {src}")
                else:
                    cited[src].append(name)

        if not re.search(r"^# \S", body, re.M):
            report.add(ERROR, rel, "見出し(# ページ名)が無い")
        if "**要点**" not in body:
            report.add(ERROR, rel, "**要点** の行が無い")
        prose = strip_code(body)
        confidence_lines = [(i, line) for i, line in enumerate(prose.split("\n")) if CONFIDENCE_LINE_RE.search(line)]
        if not confidence_lines:
            report.add(ERROR, rel, "確度の行(「確度: ◎」か「確度: ○」)が無い")
        for offset, line in confidence_lines:
            if not CONFIDENCE_RE.search(line):
                report.add(ERROR, f"{rel}:{body_line + offset}", "確度が ◎ か ○ で始まっていない(確度は 2 段階だけ)")
        for offset, line in enumerate(prose.split("\n")):
            for label in FORBIDDEN_LABELS:
                if label in line:
                    report.add(ERROR, f"{rel}:{body_line + offset}", f"推定のラベル「{label}」がある(確度は ◎ と ○ だけ。裏取りの無い推定は書かない)")
            if line.startswith("> ⚠️ 矛盾"):
                report.add(INFO, f"{rel}:{body_line + offset}", "未解決の矛盾がある")

        targets = set()
        for offset, line in enumerate(prose.split("\n")):
            for match in WIKILINK_RE.finditer(line):
                target = match.group(1).strip()
                if target not in pages:
                    report.add(ERROR, f"{rel}:{body_line + offset}", f"リンク先のページが無い: [[{target}]]")
                elif target != name:
                    targets.add(target)
        links[name] = targets

    inbound = {name: 0 for name in pages}
    for targets in links.values():
        for target in targets:
            inbound[target] += 1
    for name, count in inbound.items():
        if count == 0 and len(pages) > 1:
            report.add(WARN, pages[name].relative_to(root).as_posix(), "孤立ページ(ほかのページから [[リンク]] されていない)")
    return pages, links, cited


def check_index(root: Path, pages: dict[str, Path], report: Report) -> None:
    path = root / "index.md"
    if not path.is_file():
        report.add(ERROR, "index.md", "index.md が無い")
        return
    seen: dict[str, int] = defaultdict(int)
    for number, line in enumerate(strip_code(read_text(path)).split("\n"), start=1):
        found = [m.group(1).strip() for m in WIKILINK_RE.finditer(line)]
        if not found:
            continue
        if not INDEX_LINE_RE.match(line):
            report.add(WARN, f"index.md:{number}", "行の形が「- [[ページ名]] — 要点」になっていない")
        for target in found:
            seen[target] += 1
            if target not in pages:
                report.add(ERROR, f"index.md:{number}", f"載っているページが無い: [[{target}]]")
    for name, page in pages.items():
        if seen[name] == 0:
            report.add(ERROR, page.relative_to(root).as_posix(), "index.md に載っていない")
        elif seen[name] > 1:
            report.add(ERROR, "index.md", f"[[{name}]] が {seen[name]} 回載っている(1 回だけにする)")


def check_log(root: Path, report: Report) -> None:
    path = root / "log.md"
    if not path.is_file():
        report.add(ERROR, "log.md", "log.md が無い")
        return
    for number, line in enumerate(strip_code(read_text(path)).split("\n"), start=1):
        if line.startswith("## ") and not LOG_HEADING_RE.match(line):
            report.add(ERROR, f"log.md:{number}", "見出しが「## [YYYY-MM-DD HH:MM] ingest|lint|schema | 要旨」の形でない")


def check_raw(root: Path, cited: dict[str, list[str]], report: Report) -> list[tuple[str, str, str, str]]:
    """根拠ファイルを点検し、watch の一覧 (raw パス, リポジトリ名, コミット, パス) を返す。"""
    raw = root / "raw"
    watches = []
    for path in sorted(raw.rglob("*.md")) if raw.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        fm, _, _ = parse_frontmatter(read_text(path))
        if fm is None:
            report.add(ERROR, rel, "frontmatter(--- で囲んだ date / kind)が無い")
        else:
            date = fm.get("date")
            if not isinstance(date, str) or not DATE_RE.match(date):
                report.add(ERROR, rel, "date が YYYY-MM-DD の日付でない")
            if fm.get("kind") not in RAW_KINDS:
                report.add(ERROR, rel, f"kind が command / file / doc のどれでもない: {fm.get('kind')}")
            for entry in as_list(fm.get("watch")):
                match = WATCH_RE.match(entry)
                if not match:
                    report.add(ERROR, rel, f"watch の形が「<リポジトリ名>@<コミット>:<パス>」でない: {entry}")
                else:
                    watches.append((rel, match.group(1), match.group(2), match.group(3)))
        if rel not in cited:
            report.add(WARN, rel, "どのページの sources にも挙がっていない根拠ファイル")
    return watches


def check_watches(root: Path, watches, cited, repos_path: Path, fail_on_stale: bool, report: Report) -> None:
    if not watches:
        return
    repos: dict[str, str] = {}
    if repos_path.is_file():
        try:
            repos = json.loads(read_text(repos_path))
        except json.JSONDecodeError as exc:
            report.add(ERROR, repos_path.name, f"JSON として読めない: {exc}")
            return
    unknown = sorted({name for _, name, _, _ in watches if name not in repos})
    if unknown:
        report.add(INFO, "", f"手元の場所が分からないリポジトリの watch は確かめていない: {', '.join(unknown)}({repos_path.name} に書くと確かめる)")
    for rel, name, commit, target in watches:
        if name not in repos:
            continue
        repo = Path(repos[name]).expanduser()
        where = f"{rel}  watch {name}@{commit}:{target}"
        if git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
            report.add(WARN, where, f"{repo} が git のリポジトリとして読めない({repos_path.name} の場所を確かめる)")
            continue
        if git(repo, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
            report.add(WARN, where, f"コミットが {repo} に見つからない(fetch が要るか、コミットの書き誤り)")
            continue
        if git(repo, "cat-file", "-e", f"{commit}:{target}").returncode != 0:
            report.add(WARN, where, "このコミットにそのパスが無い(パスの書き誤り。変化を確かめられない)")
            continue
        diff = git(repo, "diff", "--quiet", commit, "HEAD", "--", target)
        if diff.returncode == 1:
            pages = ", ".join(f"[[{p}]]" for p in cited.get(rel, [])) or "(引用しているページなし)"
            report.add(ERROR if fail_on_stale else WARN, where, f"要再確認: 根拠にしたファイルがこのコミット以降に変わった。対象 {pages}")
        elif diff.returncode != 0:
            report.add(WARN, where, f"差分を取れない: {diff.stderr.strip()}")


def check_history(root: Path, base: str | None, head: str | None, require: bool, report: Report) -> None:
    """raw/ が足すだけになっているか、log.md が末尾に足すだけになっているかを、base と比べて確かめる。"""
    skipped = ERROR if require else INFO
    if git(root, "rev-parse", "--is-inside-work-tree").returncode != 0:
        report.add(skipped, "", "git の作業ツリーとして読めないので、raw/ と log.md の履歴は確かめていない")
        return
    if base is None:
        upstream = git(root, "rev-parse", "--verify", "--quiet", "@{upstream}")
        if upstream.returncode != 0:
            report.add(skipped, "", "比べる相手(--base か upstream)が無いので、raw/ と log.md の履歴は確かめていない")
            return
        base = upstream.stdout.strip()
    if ZERO_SHA_RE.match(base):
        report.add(INFO, "", "比べる相手が空のコミットなので、raw/ と log.md の履歴は確かめていない")
        return
    for ref, label in ((base, "--base"), (head, "--head")):
        if ref and git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
            report.add(ERROR, "", f"{label} のコミットが見つからない: {ref}(fetch が要るか、ref の書き誤り)")
            return
    merge_base = git(root, "merge-base", base, head or "HEAD").stdout.strip() or base
    # head があればそのコミットと、無ければ作業ツリー(未コミットの変更を含む)と比べる
    target = [head] if head else []

    diff = git(root, "diff", "--name-status", "--no-renames", "-z", merge_base, *target, "--", "raw/")
    fields = diff.stdout.split("\0")
    for status, path in zip(fields[0::2], fields[1::2]):
        if status and not status.startswith("A"):
            kind = "消されている" if status.startswith("D") else "変えられている"
            report.add(ERROR, path, f"既存の根拠ファイルが{kind}(raw/ は足すだけ。取り直した根拠は新しいファイルにする)")

    def log_at(ref: str | None) -> str | None:
        if ref is None:
            path = root / "log.md"
            return read_text(path) if path.is_file() else None
        shown = git(root, "show", f"{ref}:log.md")
        return shown.stdout.replace("\r\n", "\n") if shown.returncode == 0 else None

    old_log, new_log = log_at(merge_base), log_at(head)
    before = old_log.rstrip("\n") if old_log is not None else ""
    if old_log is not None and new_log is not None and not new_log.startswith(before):
        report.add(ERROR, "log.md", "既存の行が変わっている(log.md は末尾に足すだけ)")

    schema_changed = git(root, "diff", "--quiet", merge_base, *target, "--", "AGENTS.md").returncode == 1
    if schema_changed and new_log is not None:
        added = new_log[len(before):] if new_log.startswith(before) else new_log
        if not re.search(r"^## \[[^\]]+\] schema \|", added, re.M):
            report.add(WARN, "AGENTS.md", "規約が変わっているが、log.md に schema の記録が足されていない")


def check_encoding(root: Path, report: Report) -> None:
    files = [root / "index.md", root / "log.md"]
    for folder in ("wiki", "raw"):
        if (root / folder).is_dir():
            files += sorted((root / folder).rglob("*.md"))
    for path in files:
        if not path.is_file():
            continue
        try:
            path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError:
            report.add(ERROR, path.relative_to(root).as_posix(), "UTF-8 で読めない(UTF-8 で保存し直す)")


def check_secrets(root: Path, report: Report) -> None:
    files = [root / "index.md", root / "log.md"]
    for folder in ("wiki", "raw"):
        if (root / folder).is_dir():
            files += sorted((root / folder).rglob("*.md"))
    for path in files:
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(read_text(path).split("\n"), start=1):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    report.add(ERROR, f"{rel}:{number}", f"認証情報らしき文字列({label})がある。伏せ字にする(raw/ の場合は人に相談する)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Wiki の機械の点検(AGENTS.md の規約に沿っているか)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="wiki のルート(既定: このスクリプトの 1 つ上)")
    parser.add_argument("--base", help="raw/ と log.md の履歴を比べる ref(既定: upstream。無ければ確かめない)")
    parser.add_argument("--head", help="履歴の点検で base と比べる側のコミット(既定: 作業ツリー。pre-push は push するコミットを渡す)")
    parser.add_argument("--repos", type=Path, help="watch のリポジトリ名 → 手元の場所の JSON(既定: <root>/wiki-lint.repos.json)")
    parser.add_argument("--fail-on-stale", action="store_true", help="「要再確認」をエラーにする(既定は警告)")
    parser.add_argument("--require-history", action="store_true", help="raw/ と log.md の履歴を確かめられないときをエラーにする(CI 向け)")
    args = parser.parse_args(argv)

    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
    root = args.root.resolve()
    missing = [p for p in ("AGENTS.md", "index.md", "log.md") if not (root / p).is_file()]
    if missing:
        print(f"wiki のルートでない({root} に {', '.join(missing)} が無い)", file=sys.stderr)
        return 2

    report = Report()
    check_encoding(root, report)
    pages, _, cited = check_pages(root, report)
    check_index(root, pages, report)
    check_log(root, report)
    watches = check_raw(root, cited, report)
    check_watches(root, watches, cited, args.repos or root / "wiki-lint.repos.json", args.fail_on_stale, report)
    check_history(root, args.base or None, args.head or None, args.require_history, report)
    check_secrets(root, report)

    print(f"wiki: {root}  ページ {len(pages)} 件")
    report.print()
    return 1 if report.count(ERROR) else 0


if __name__ == "__main__":
    sys.exit(main())
