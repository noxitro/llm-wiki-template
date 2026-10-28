#!/usr/bin/env python3
"""LLM Wiki の機械の点検。

AGENTS.md の規約(Open Knowledge Format v0.2 に沿う)を守っているかを、LLM の判断を挟まずに検査する。
標準ライブラリだけで動く(Python 3.9 以上)。

    python scripts/wiki_lint.py                     # 手元で点検する
    python scripts/wiki_lint.py --base origin/main  # raw/ と log.md の履歴の点検も、この ref と比べて行う

終了コード: 0 = エラーなし / 1 = エラーあり / 2 = 使い方の誤り
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"

OKF_VERSION = "0.2"
RESERVED = {"index.md", "log.md"}
PAGE_FORBIDDEN_TYPES = {"Evidence", "Schema"}
CONFIDENCE_VALUES = {"◎", "○"}
STATUS_VALUES = {"draft", "stable", "deprecated"}
RAW_KINDS = {"command", "file", "doc"}
FORBIDDEN_LABELS = ("△", "▲")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$")
ACTOR_RE = re.compile(r"^(?:human|process):\S+$|^[^\s/:]+/\S+$")
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
KEY_RE = re.compile(r"^([A-Za-z_$][\w.$-]*)\s*:(?:[ ]+(.*))?$")
WATCH_RE = re.compile(r"^([^@\s]+)@([0-9a-fA-F]{4,40}):(.+)$")
ZERO_SHA_RE = re.compile(r"^0+$")

LINK_RE = re.compile(r"(?<!!)\[((?:[^\]\\]|\\.)*)\]\((<[^>]*>|[^)\s]*)(?:\s+\"[^\"]*\")?\)")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]\s]+)\](?!:)")
FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]\s]+)\]:")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
INDEX_ITEM_RE = re.compile(r"^[*-] \[([^\]]+)\]\(([^)]+)\) - (\S.*)$")
LIST_ITEM_RE = re.compile(r"^[*-] ")
LOG_DATE_RE = re.compile(r"^## (.*)$")
LOG_ITEM_RE = re.compile(r"^[*-] \*\*(Ingest|Lint|Schema)\*\* (\d{2}:\d{2}) \S")

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


# ---------------------------------------------------------------------------
# frontmatter(YAML の部分集合)
# ---------------------------------------------------------------------------

class YamlError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    """引用符の外にある ` #` 以降を落とす。"""
    out: list[str] = []
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"" and (not "".join(out).strip() or "".join(out).rstrip()[-1] in ":,[{-"):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _parse_flow(text: str):
    """`値` / `"値"` / `[a, b]` / `{ k: v }`(入れ子可)を読む。値は文字列のまま返す。"""
    pos = 0

    def skip() -> None:
        nonlocal pos
        while pos < len(text) and text[pos] in " \t":
            pos += 1

    def scalar(stop: str) -> str:
        nonlocal pos
        skip()
        if pos < len(text) and text[pos] in "'\"":
            quote = text[pos]
            pos += 1
            buf: list[str] = []
            while pos < len(text):
                ch = text[pos]
                if quote == "'" and ch == "'" and text[pos + 1:pos + 2] == "'":
                    buf.append("'")
                    pos += 2
                    continue
                if quote == '"' and ch == "\\" and pos + 1 < len(text):
                    buf.append(text[pos + 1])
                    pos += 2
                    continue
                if ch == quote:
                    pos += 1
                    return "".join(buf)
                buf.append(ch)
                pos += 1
            raise YamlError("引用符が閉じていない")
        start = pos
        while pos < len(text) and text[pos] not in stop:
            pos += 1
        return text[start:pos].strip()

    def value(stop: str):
        nonlocal pos
        skip()
        if pos < len(text) and text[pos] == "[":
            pos += 1
            items: list = []
            skip()
            if pos < len(text) and text[pos] == "]":
                pos += 1
                return items
            while True:
                items.append(value(",]"))
                skip()
                if pos >= len(text):
                    raise YamlError("[ が閉じていない")
                if text[pos] == ",":
                    pos += 1
                    continue
                if text[pos] == "]":
                    pos += 1
                    return items
                raise YamlError(f"[ ] の中を読めない: {text}")
        if pos < len(text) and text[pos] == "{":
            pos += 1
            obj: dict = {}
            skip()
            if pos < len(text) and text[pos] == "}":
                pos += 1
                return obj
            while True:
                key = scalar(":,}")
                skip()
                if not key or pos >= len(text) or text[pos] != ":":
                    raise YamlError(f"{{ }} の中に「キー: 値」でない項目がある: {text}")
                pos += 1
                if key in obj:
                    raise YamlError(f"キー {key} が 2 回ある")
                obj[key] = value(",}")
                skip()
                if pos >= len(text):
                    raise YamlError("{ が閉じていない")
                if text[pos] == ",":
                    pos += 1
                    continue
                if text[pos] == "}":
                    pos += 1
                    return obj
                raise YamlError(f"{{ }} の中を読めない: {text}")
        return scalar(stop)

    result = value("")
    skip()
    if pos != len(text):
        raise YamlError(f"余分な文字がある: {text[pos:]}")
    return result


def parse_yaml(lines: list[str]) -> dict:
    """規約で使う YAML の形だけを読む(AGENTS.md の「ページの形」)。読めなければ YamlError。"""
    items: list[tuple[int, str]] = []
    for raw in lines:
        lead = raw[:len(raw) - len(raw.lstrip())]
        if "\t" in lead:
            raise YamlError("字下げにタブがある(空白にする)")
        line = _strip_comment(raw)
        if line.strip():
            items.append((len(line) - len(line.lstrip(" ")), line.strip()))
    pos = 0

    def is_dash(text: str) -> bool:
        return text == "-" or text.startswith("- ")

    def block(indent: int):
        return sequence(indent) if is_dash(items[pos][1]) else mapping(indent)

    def mapping(indent: int) -> dict:
        nonlocal pos
        obj: dict = {}
        while pos < len(items) and items[pos][0] == indent and not is_dash(items[pos][1]):
            match = KEY_RE.match(items[pos][1])
            if not match:
                raise YamlError(f"「キー: 値」の形でない行: {items[pos][1]}")
            key, rest = match.group(1), (match.group(2) or "").strip()
            pos += 1
            if key in obj:
                raise YamlError(f"キー {key} が 2 回ある")
            if rest:
                if rest[0] in "|>":
                    raise YamlError(f"{key}: 複数行の文字列(| や >)は使えない")
                obj[key] = _parse_flow(rest)
            elif pos < len(items) and (items[pos][0] > indent or (items[pos][0] == indent and is_dash(items[pos][1]))):
                obj[key] = block(items[pos][0])
            else:
                obj[key] = None
        if pos < len(items) and items[pos][0] > indent:
            raise YamlError(f"字下げがずれている行: {items[pos][1]}")
        return obj

    def sequence(indent: int) -> list:
        nonlocal pos
        out: list = []
        while pos < len(items) and items[pos][0] == indent and is_dash(items[pos][1]):
            text = items[pos][1][1:].lstrip(" ")
            if not text:
                pos += 1
                out.append(block(items[pos][0]) if pos < len(items) and items[pos][0] > indent else None)
            elif KEY_RE.match(text) and text[0] not in "[{'\"":
                offset = indent + len(items[pos][1]) - len(text)
                items[pos] = (offset, text)
                out.append(mapping(offset))
            else:
                pos += 1
                out.append(_parse_flow(text))
        return out

    if not items:
        return {}
    if items[0][0] != 0:
        raise YamlError("1 行目が字下げされている")
    result = mapping(0)
    if pos != len(items):
        raise YamlError(f"読めない行: {items[pos][1]}")
    return result


@dataclass
class Doc:
    path: Path
    rel: str
    fm: dict | None = None
    fm_error: str | None = None
    body: str = ""
    body_line: int = 1


def read_text(path: Path) -> str:
    # UTF-8 でないファイルは check_encoding が報告するので、ここでは止まらずに読む
    return path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")


def load_doc(root: Path, path: Path) -> Doc:
    doc = Doc(path=path, rel=path.relative_to(root).as_posix())
    text = read_text(path)
    lines = text.split("\n")
    doc.body = text
    if not lines or lines[0].strip() != "---":
        return doc
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        doc.fm_error = "frontmatter の閉じの --- が無い"
        return doc
    try:
        parsed = parse_yaml(lines[1:end])
        doc.fm = parsed if isinstance(parsed, dict) else {}
    except YamlError as exc:
        doc.fm_error = str(exc)
        doc.fm = {}
    doc.body = "\n".join(lines[end + 1:])
    doc.body_line = end + 2
    return doc


def strip_code(text: str) -> str:
    """フェンスとインラインのコードを空白に置き換える(行番号は保つ)。"""
    out, fence = [], None
    for line in text.split("\n"):
        mark = re.match(r"^\s*(`{3,}|~{3,})", line)
        if mark and (fence is None or mark.group(1)[0] == fence[0] and len(mark.group(1)) >= len(fence)):
            fence = mark.group(1) if fence is None else None
            out.append("")
            continue
        out.append("" if fence else re.sub(r"`[^`]*`", "", line))
    return "\n".join(out)


def strip_comments(text: str) -> str:
    """HTML コメントを空白に置き換える(行番号は保つ)。"""
    return re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


def prose_lines(doc: Doc) -> list[tuple[int, str]]:
    return [(doc.body_line + i, line) for i, line in enumerate(strip_code(strip_comments(doc.body)).split("\n"))]


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_datetime(value) -> dt.datetime | None:
    if not isinstance(value, str) or not DATETIME_RE.match(value):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_date(value) -> dt.date | None:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def resolve_link(root: Path, source: Path, target: str) -> str | None:
    """リンク先をバンドルのルートからの相対パス(posix)にする。外部リンクとページ内リンクは None。

    バンドルの外を指すときは ValueError。
    """
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    if not target or target.startswith("#") or SCHEME_RE.match(target):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    base = root if target.startswith("/") else source.parent
    resolved = (base / target.lstrip("/")).resolve()
    try:
        rel = resolved.relative_to(root).as_posix()
    except ValueError:
        raise ValueError(target) from None
    return "" if rel == "." else rel


def links_in(doc: Doc) -> list[tuple[int, str, str]]:
    """(行番号, 表示, 生のリンク先) の一覧。"""
    return [(number, m.group(1), m.group(2)) for number, line in prose_lines(doc) for m in LINK_RE.finditer(line)]


# ---------------------------------------------------------------------------
# 点検
# ---------------------------------------------------------------------------

def bundle_files(root: Path) -> list[Path]:
    """バンドルに入る .md(ドットで始まるフォルダとファイルは外)。"""
    files = []
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return files


def check_encoding(root: Path, files: list[Path], report: Report) -> None:
    for path in files:
        try:
            path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError:
            report.add(ERROR, path.relative_to(root).as_posix(), "UTF-8 で読めない(UTF-8 で保存し直す)")


def check_conformance(docs: dict[str, Doc], report: Report) -> None:
    """OKF §11: 予約ファイル以外のすべての .md に、読める frontmatter と空でない type がある。"""
    for rel, doc in docs.items():
        if doc.path.name in RESERVED:
            continue
        if doc.fm_error:
            report.add(ERROR, rel, f"frontmatter を読めない: {doc.fm_error}(使える YAML の形は AGENTS.md の「ページの形」)")
        elif doc.fm is None:
            report.add(ERROR, rel, "frontmatter が無い(OKF: 予約ファイル以外の .md には type を持つ frontmatter が要る)")
        elif not isinstance(doc.fm.get("type"), str) or not doc.fm["type"].strip():
            report.add(ERROR, rel, "type が無いか空(OKF で必須)")


def check_actor_events(rel: str, key: str, value, report: Report, required: bool) -> list[dt.datetime]:
    """generated / verified の { by, at } を点検し、読めた at を返す。"""
    if value is None:
        if required:
            report.add(ERROR, rel, f"{key} が無い(書き方は AGENTS.md の「ページの形」)")
        return []
    events = as_list(value) if key == "verified" else [value]
    if key == "verified" and not events and required:
        report.add(ERROR, rel, "verified が空(根拠と突き合わせて確かめた記録を 1 件以上書く)")
    times = []
    for event in events:
        if not isinstance(event, dict):
            report.add(ERROR, rel, f"{key} の項目が {{ by: <書き手>, at: <日時> }} の形でない: {event}")
            continue
        by, at = event.get("by"), event.get("at")
        if not isinstance(by, str) or not ACTOR_RE.match(by):
            report.add(ERROR, rel, f"{key}.by が <ハーネス>/<モデル>・human:<名前>・process:<名前> のどれでもない: {by}")
        parsed = parse_datetime(at)
        if parsed is None:
            report.add(ERROR, rel, f"{key}.at が時差つきの ISO 8601 日時でない: {at}(例: 2026-10-26T14:30:00+09:00)")
        else:
            times.append(parsed)
    return times


def check_pages(root: Path, docs: dict[str, Doc], now: dt.datetime, fail_on_stale: bool, report: Report):
    """ページを点検し、(ページの rel → Doc, raw の rel → 引用しているページ) を返す。"""
    pages = {rel: doc for rel, doc in docs.items() if rel.startswith("wiki/") and doc.path.name not in RESERVED}
    stems: dict[str, str] = {}
    for rel, doc in pages.items():
        stem = doc.path.stem
        if stem in stems:
            report.add(WARN, rel, f"ファイル名「{stem}」が {stems[stem]} と同じ(リンクはパスで解決されるが、人が取り違えやすい)")
        else:
            stems[stem] = rel

    cited: dict[str, list[str]] = defaultdict(list)
    inbound: dict[str, int] = {rel: 0 for rel in pages}
    for rel, doc in pages.items():
        fm = doc.fm or {}
        if doc.fm is None or doc.fm_error:
            fm = {}  # check_conformance が報告済み
        else:
            page_type = fm.get("type")
            if page_type in PAGE_FORBIDDEN_TYPES:
                report.add(ERROR, rel, f"wiki/ のページに type: {page_type} は使わない(既定は Finding)")
            for key in ("title", "description"):
                if not isinstance(fm.get(key), str) or not fm[key].strip():
                    report.add(ERROR, rel, f"{key} が無いか空")
            created = parse_date(fm.get("created"))
            if created is None:
                report.add(ERROR, rel, f"created が YYYY-MM-DD の実在する日付でない: {fm.get('created')}")
            generated = check_actor_events(rel, "generated", fm.get("generated"), report, required=True)
            check_actor_events(rel, "verified", fm.get("verified"), report, required=True)
            if created and generated and generated[0].date() < created:
                report.add(ERROR, rel, "generated.at が created より前になっている")
            confidence = fm.get("confidence")
            if confidence not in CONFIDENCE_VALUES:
                hint = "(推定のラベルは使わない。裏取りの無い推定は書かない)" if confidence in FORBIDDEN_LABELS else ""
                report.add(ERROR, rel, f"confidence が ◎ か ○ でない: {confidence}{hint}")
            status = fm.get("status")
            if status is not None and status not in STATUS_VALUES:
                report.add(ERROR, rel, f"status が draft / stable / deprecated のどれでもない: {status}")
            if "stale_after" in fm:
                stale_after = parse_datetime(fm.get("stale_after"))
                if stale_after is None:
                    report.add(ERROR, rel, f"stale_after が時差つきの ISO 8601 日時でない: {fm.get('stale_after')}")
                elif now >= stale_after:
                    report.add(ERROR if fail_on_stale else WARN, rel, f"要再確認: stale_after({fm['stale_after']})を過ぎた。根拠を取り直す")
            if "tags" in fm and not (isinstance(fm["tags"], list) and all(isinstance(t, str) for t in fm["tags"])):
                report.add(ERROR, rel, "tags が [a, b] の形の一覧でない")

        source_ids = set()
        sources = fm.get("sources") if fm else None
        if fm and not as_list(sources):
            report.add(ERROR, rel, "sources が空(根拠の raw/ ファイルを 1 つ以上挙げる)")
        for entry in as_list(sources):
            if not isinstance(entry, dict):
                report.add(ERROR, rel, f"sources の項目が {{ id: <名前>, resource: /raw/<ファイル>.md }} の形でない: {entry}")
                continue
            source_id, resource = entry.get("id"), entry.get("resource")
            if not isinstance(source_id, str) or not SOURCE_ID_RE.match(source_id):
                report.add(ERROR, rel, f"sources の id が英数字・_・.・- の名前でない: {source_id}")
            elif source_id in source_ids:
                report.add(ERROR, rel, f"sources の id「{source_id}」が 2 回ある")
            else:
                source_ids.add(source_id)
            if not isinstance(resource, str) or not resource.startswith("/raw/"):
                report.add(ERROR, rel, f"sources の resource が /raw/ で始まっていない: {resource}(URL は raw/ の根拠ファイルに書く)")
            elif not (root / resource.lstrip("/")).is_file():
                report.add(ERROR, rel, f"sources の根拠ファイルが無い: {resource}")
            else:
                cited[resource.lstrip("/")].append(rel)

        lines = prose_lines(doc)
        heading = next((line[2:].strip() for _, line in lines if line.startswith("# ")), None)
        if heading is None:
            report.add(ERROR, rel, "見出し(# <title>)が無い")
        elif fm.get("title") and heading != fm["title"]:
            report.add(WARN, rel, f"見出し「{heading}」が title「{fm['title']}」と違う")
        if "**要点**" not in doc.body:
            report.add(ERROR, rel, "**要点** の行が無い")
        for number, line in lines:
            where = f"{rel}:{number}"
            for label in FORBIDDEN_LABELS:
                if label in line:
                    report.add(ERROR, where, f"推定のラベル「{label}」がある(確度は ◎ と ○ だけ。裏取りの無い推定は書かない)")
            if line.startswith("> ⚠️ 矛盾"):
                report.add(INFO, where, "未解決の矛盾がある")
            for match in WIKILINK_RE.finditer(line):
                report.add(ERROR, where, f"[[{match.group(1)}]] の形は使わない([表示](相対パス) の Markdown リンクにする)")
            definition = FOOTNOTE_DEF_RE.match(line)
            footnotes = [definition.group(1)] if definition else []
            footnotes += [m.group(1) for m in FOOTNOTE_REF_RE.finditer(line)]
            for footnote in footnotes:
                if fm and footnote not in source_ids:
                    report.add(ERROR, where, f"脚注 [^{footnote}] に対応する sources の id が無い")

        for number, _, target in links_in(doc):
            where = f"{rel}:{number}"
            try:
                resolved = resolve_link(root, doc.path, target)
            except ValueError:
                report.add(ERROR, where, f"リンク先がバンドルの外: {target}")
                continue
            if resolved is None:
                continue
            if not (root / resolved).exists():
                report.add(ERROR, where, f"リンク先が無い: {target}")
            elif resolved in pages and resolved != rel:
                inbound[resolved] += 1
                target_fm = pages[resolved].fm or {}
                if target_fm.get("status") == "deprecated" and (fm or {}).get("status") != "deprecated":
                    report.add(INFO, where, f"廃止(deprecated)のページへのリンク: {target}")

    if len(pages) > 1:
        for rel, count in inbound.items():
            if count == 0:
                report.add(WARN, rel, "孤立ページ(ほかのページからリンクされていない)")
    return pages, cited


def check_indexes(root: Path, docs: dict[str, Doc], pages: dict[str, Doc], report: Report) -> None:
    root_index = docs.get("index.md")
    if root_index is None:
        report.add(ERROR, "index.md", "index.md が無い")
    seen: dict[str, int] = defaultdict(int)
    for rel, doc in docs.items():
        if doc.path.name != "index.md":
            continue
        is_root = rel == "index.md"
        if doc.fm_error:
            report.add(ERROR, rel, f"frontmatter を読めない: {doc.fm_error}")
        elif is_root:
            if doc.fm is None:
                report.add(WARN, rel, f'frontmatter に okf_version: "{OKF_VERSION}" が無い')
            else:
                if doc.fm.get("okf_version") != OKF_VERSION:
                    report.add(WARN, rel, f'okf_version が "{OKF_VERSION}" でない: {doc.fm.get("okf_version")}')
                for key in sorted(set(doc.fm) - {"okf_version"}):
                    report.add(WARN, rel, f"index.md の frontmatter に okf_version 以外のキーがある: {key}(OKF §8)")
        elif doc.fm is not None:
            report.add(ERROR, rel, "ルート以外の index.md に frontmatter がある(OKF §8)")

        for number, line in prose_lines(doc):
            where = f"{rel}:{number}"
            found = list(LINK_RE.finditer(line))
            if not found:
                continue
            item = INDEX_ITEM_RE.match(line)
            if not item:
                report.add(WARN, where, "行の形が「* [題名](パス) - 説明」になっていない")
            for match in found:
                try:
                    resolved = resolve_link(root, doc.path, match.group(2))
                except ValueError:
                    report.add(ERROR, where, f"リンク先がバンドルの外: {match.group(2)}")
                    continue
                if resolved is None:
                    continue
                if not (root / resolved).exists():
                    report.add(ERROR, where, f"載っているファイルが無い: {match.group(2)}")
                    continue
                if resolved not in pages:
                    continue
                if is_root:
                    seen[resolved] += 1
                fm = pages[resolved].fm or {}
                if item and fm.get("title") and item.group(1) != fm["title"]:
                    report.add(WARN, where, f"題名がページの title「{fm['title']}」と違う")
                if item and fm.get("description") and item.group(3).strip() != fm["description"]:
                    report.add(WARN, where, "説明がページの description と違う")
    if root_index is not None:
        for rel in pages:
            if seen[rel] == 0:
                report.add(ERROR, rel, "index.md に載っていない")
            elif seen[rel] > 1:
                report.add(ERROR, "index.md", f"{rel} が {seen[rel]} 回載っている(1 回だけにする)")


def check_logs(docs: dict[str, Doc], report: Report) -> None:
    if "log.md" not in docs:
        report.add(ERROR, "log.md", "log.md が無い")
    for rel, doc in docs.items():
        if doc.path.name != "log.md":
            continue
        if doc.fm_error:
            report.add(ERROR, rel, f"frontmatter を読めない: {doc.fm_error}")
        previous: dt.date | None = None
        current: dt.date | None = None
        last_time: str | None = None
        for number, line in prose_lines(doc):
            where = f"{rel}:{number}"
            heading = LOG_DATE_RE.match(line)
            if heading:
                date = parse_date(heading.group(1).strip())
                if date is None:
                    report.add(ERROR, where, "日付の見出しが「## YYYY-MM-DD」の形でない(OKF §9)")
                    current = None
                    continue
                if previous is not None and date >= previous:
                    report.add(ERROR, where, f"日付の見出しが新しい順になっていない、または同じ日付が 2 回ある: {date}")
                previous, current, last_time = date, date, None
                continue
            if not LIST_ITEM_RE.match(line):
                continue
            item = LOG_ITEM_RE.match(line)
            if not item:
                report.add(ERROR, where, "項目が「* **Ingest|Lint|Schema** HH:MM 要旨」の形でない")
                continue
            if current is None:
                report.add(ERROR, where, "日付の見出し(## YYYY-MM-DD)の下にない項目")
                continue
            if last_time is not None and item.group(2) > last_time:
                report.add(WARN, where, "その日の中で時刻が新しい順になっていない")
            last_time = item.group(2)


def check_raw(docs: dict[str, Doc], cited: dict[str, list[str]], report: Report) -> list[tuple[str, str, str, str]]:
    """根拠ファイルを点検し、watch の一覧 (raw の rel, リポジトリ名, コミット, パス) を返す。"""
    watches = []
    for rel, doc in docs.items():
        if not rel.startswith("raw/") or doc.path.name in RESERVED:
            continue
        if doc.fm is not None and not doc.fm_error:
            fm = doc.fm
            if fm.get("type") != "Evidence":
                report.add(ERROR, rel, f"raw/ の根拠ファイルの type が Evidence でない: {fm.get('type')}")
            if parse_date(fm.get("date")) is None:
                report.add(ERROR, rel, f"date が YYYY-MM-DD の実在する日付でない: {fm.get('date')}")
            if fm.get("kind") not in RAW_KINDS:
                report.add(ERROR, rel, f"kind が command / file / doc のどれでもない: {fm.get('kind')}")
            for entry in as_list(fm.get("watch")):
                match = WATCH_RE.match(entry) if isinstance(entry, str) else None
                if not match:
                    report.add(ERROR, rel, f"watch の形が「<リポジトリ名>@<コミット>:<パス>」でない: {entry}")
                else:
                    watches.append((rel, match.group(1), match.group(2), match.group(3)))
        if rel not in cited:
            report.add(WARN, rel, "どのページの sources にも挙がっていない根拠ファイル")
    return watches


def check_watches(watches, cited, repos_path: Path, fail_on_stale: bool, report: Report) -> None:
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
            pages = ", ".join(cited.get(rel, [])) or "(引用しているページなし)"
            report.add(ERROR if fail_on_stale else WARN, where, f"要再確認: 根拠にしたファイルがこのコミット以降に変わった。対象 {pages}")
        elif diff.returncode != 0:
            report.add(WARN, where, f"差分を取れない: {diff.stderr.strip()}")


def check_history(root: Path, base: str | None, head: str | None, require: bool, report: Report) -> None:
    """raw/ が足すだけになっているか、log.md の既存の行が残っているかを、base と比べて確かめる。"""
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

    diff = git(root, "diff", "--name-status", "--no-renames", "--relative", "-z", merge_base, *target, "--", "raw/")
    fields = diff.stdout.split("\0")
    for status, path in zip(fields[0::2], fields[1::2]):
        if status and not status.startswith("A"):
            kind = "消されている" if status.startswith("D") else "変えられている"
            report.add(ERROR, path, f"既存の根拠ファイルが{kind}(raw/ は足すだけ。取り直した根拠は新しいファイルにする)")

    def log_at(ref: str | None) -> list[str] | None:
        if ref is None:
            path = root / "log.md"
            text = read_text(path) if path.is_file() else None
        else:
            # ./ を付けると、リポジトリのルートでなく -C の場所からのパスになる(vault がサブフォルダでも読める)
            shown = git(root, "show", f"{ref}:./log.md")
            text = shown.stdout.lstrip("﻿").replace("\r\n", "\n") if shown.returncode == 0 else None
        return None if text is None else [line.rstrip() for line in text.split("\n") if line.strip()]

    old_log, new_log = log_at(merge_base), log_at(head)
    added: list[str] = []
    if old_log is not None and new_log is not None:
        matcher = difflib.SequenceMatcher(None, old_log, new_log, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "delete"):
                report.add(ERROR, "log.md", f"既存の行が変わっているか消えている(log.md は足すだけ): {old_log[i1]}")
                break
            if tag == "insert":
                added += new_log[j1:j2]
    elif new_log is not None:
        added = new_log

    schema_changed = git(root, "diff", "--quiet", merge_base, *target, "--", "AGENTS.md").returncode == 1
    if schema_changed and new_log is not None:
        if not any((m := LOG_ITEM_RE.match(line)) and m.group(1) == "Schema" for line in added):
            report.add(WARN, "AGENTS.md", "規約が変わっているが、log.md に **Schema** の項目が足されていない")


def check_secrets(docs: dict[str, Doc], report: Report) -> None:
    for rel, doc in docs.items():
        for number, line in enumerate(read_text(doc.path).split("\n"), start=1):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    report.add(ERROR, f"{rel}:{number}", f"認証情報らしき文字列({label})がある。伏せ字にする(raw/ の場合は人に相談する)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Wiki の機械の点検(AGENTS.md の規約と OKF v0.2 に沿っているか)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="wiki のルート(既定: このスクリプトの 1 つ上)")
    parser.add_argument("--base", help="raw/ と log.md の履歴を比べる ref(既定: upstream。無ければ確かめない)")
    parser.add_argument("--head", help="履歴の点検で base と比べる側のコミット(既定: 作業ツリー。pre-push は push するコミットを渡す)")
    parser.add_argument("--repos", type=Path, help="watch のリポジトリ名 → 手元の場所の JSON(既定: <root>/wiki-lint.repos.json)")
    parser.add_argument("--fail-on-stale", action="store_true", help="「要再確認」をエラーにする(既定は警告)")
    parser.add_argument("--require-history", action="store_true", help="raw/ と log.md の履歴を確かめられないときをエラーにする(CI 向け)")
    parser.add_argument("--now", help=argparse.SUPPRESS)  # テスト用: stale_after と比べる現在時刻
    args = parser.parse_args(argv)

    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
    root = args.root.resolve()
    missing = [p for p in ("AGENTS.md", "index.md", "log.md") if not (root / p).is_file()]
    if missing:
        print(f"wiki のルートでない({root} に {', '.join(missing)} が無い)", file=sys.stderr)
        return 2
    now = parse_datetime(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
    if now is None:
        print(f"--now が時差つきの ISO 8601 日時でない: {args.now}", file=sys.stderr)
        return 2

    report = Report()
    files = bundle_files(root)
    check_encoding(root, files, report)
    docs = {doc.rel: doc for doc in (load_doc(root, path) for path in files)}
    check_conformance(docs, report)
    pages, cited = check_pages(root, docs, now, args.fail_on_stale, report)
    check_indexes(root, docs, pages, report)
    check_logs(docs, report)
    watches = check_raw(docs, cited, report)
    check_watches(watches, cited, args.repos or root / "wiki-lint.repos.json", args.fail_on_stale, report)
    check_history(root, args.base or None, args.head or None, args.require_history, report)
    check_secrets(docs, report)

    print(f"wiki: {root}  ページ {len(pages)} 件(OKF v{OKF_VERSION})")
    report.print()
    return 1 if report.count(ERROR) else 0


if __name__ == "__main__":
    sys.exit(main())
