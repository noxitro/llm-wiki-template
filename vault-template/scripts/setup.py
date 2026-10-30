#!/usr/bin/env python3
"""この vault を作業ディレクトリに紐づける(LLM Wiki の setup)。

作業ディレクトリに次を書く。

- `.llm-wiki.json`: vault の名前 → この PC での場所。人ごとに違うので git では管理しない(.git/info/exclude に足す)
- `AGENTS.md` の llm-wiki の節: この作業ディレクトリが使う vault の名前と、参照・書き込みの決まり(パスは含まない)
- `CLAUDE.md`: 無ければ `@AGENTS.md` の 1 行で作る。あって AGENTS.md を読み込んでいなければ、その行を足す
- `.github/copilot-instructions.md`: すでにあるときだけ、同じ節を書く(`--copilot-instructions` で新しく作る)

あわせて、vault が git のリポジトリなら push 前の点検(.githooks)を有効にする。

    python scripts/setup.py <作業ディレクトリ>            # 紐づける
    python scripts/setup.py <作業ディレクトリ> --unlink   # 紐づけを外す

標準ライブラリだけで動く(Python 3.9 以上)。終了コード: 0 = 成功 / 1 = 失敗 / 2 = 使い方の誤り
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

CONFIG_NAME = ".llm-wiki.json"
SCHEMA_NAME = "llm-wiki.schema.json"
BEGIN = "<!-- llm-wiki:begin -->"
END = "<!-- llm-wiki:end -->"
BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.S)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CLAUDE_IMPORT = "@AGENTS.md"

VAULT_ROOT = Path(__file__).resolve().parents[1]


class SetupError(Exception):
    pass


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n") if path.is_file() else ""


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def slug(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", name.lower())).strip("-")


def is_vault(path: Path) -> bool:
    return all((path / name).is_file() for name in ("AGENTS.md", "index.md", "log.md"))


def posix(path: Path) -> str:
    return path.resolve().as_posix()


def render_block(config: dict) -> str:
    vaults = config.get("vaults", {})
    default = config.get("default")
    names = ", ".join(f"`{name}`" + ("(既定)" if name == default else "") for name in sorted(vaults))
    return f"""{BEGIN}
## LLM Wiki

<!-- この節は LLM Wiki の setup が書く。手で直さない(外すときは vault で setup --unlink)。 -->

この作業ディレクトリは LLM Wiki の vault {names} を使う。

- vault の場所は、このフォルダの `{CONFIG_NAME}` の `vaults.<名前>.path` にある(各自の手元にだけある。git では管理しない)。ファイルが無い・名前が無いときは、推測で探さず、vault のフォルダで `setup` を実行して紐づけるよう人に伝える。
- 参照: 新しい課題・調査・設計判断に着手するとき、過去に扱った可能性があれば、まず vault の `index.md` を読む。該当するページがあれば精読して前提にし、ページの題名を出典として挙げる。該当が無ければ何も言わずに続ける。
- 書き込みは、人が「wiki に取り込んで」「格納する知見はある?」「wiki を点検して」と頼んだときだけ行う。規約は vault の `AGENTS.md` にある。push はしない。
{END}
"""


def upsert_block(text: str, block: str) -> str:
    if BLOCK_RE.search(text):
        return BLOCK_RE.sub(lambda _: block, text, count=1)
    if not text.strip():
        return block
    return text.rstrip("\n") + "\n\n" + block


def remove_block(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", BLOCK_RE.sub("", text)).strip("\n") + "\n" if text.strip() else ""


class Plan:
    """書き込みをためておき、--dry-run ならそれを見せるだけにする。"""

    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.lines: list[str] = []

    def write(self, path: Path, text: str, label: str) -> None:
        old = read(path) if path.is_file() else None
        if old == text:
            self.lines.append(f"変更なし  {path}({label})")
            return
        self.lines.append(f"{'作成' if old is None else '更新'}      {path}({label})")
        if not self.dry_run:
            # 既存のファイルの改行(CRLF)と BOM は保つ
            raw = path.read_bytes() if path.is_file() else b""
            path.parent.mkdir(parents=True, exist_ok=True)
            # Path.write_text の newline 引数は Python 3.10 以降なので、open で書く
            with path.open("w", encoding="utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8",
                           newline="\r\n" if b"\r\n" in raw else "\n") as f:
                f.write(text)

    def delete(self, path: Path, label: str) -> None:
        if path.is_file():
            self.lines.append(f"削除      {path}({label})")
            if not self.dry_run:
                path.unlink()

    def note(self, line: str) -> None:
        self.lines.append(line)


def load_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(read(path))
    except json.JSONDecodeError as exc:
        raise SetupError(f"{path} を JSON として読めない: {exc}(直すか消してから実行し直す)") from None
    if not isinstance(data, dict) or not isinstance(data.get("vaults", {}), dict):
        raise SetupError(f"{path} の形が違う(vaults が名前 → {{ path }} の対応になっていない)")
    return data


def dump_config(config: dict) -> str:
    ordered = {key: config[key] for key in ("$schema", "default", "vaults") if key in config}
    ordered.update({k: v for k, v in config.items() if k not in ordered})
    return json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"


def exclude_from_git(work: Path, plan: Plan) -> None:
    """作業ディレクトリが git の中なら、.llm-wiki.json を .git/info/exclude に足す(.gitignore は触らない)。"""
    top = git(work, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        plan.note(f"情報      {work} は git のリポジトリでないので、{CONFIG_NAME} の除外は設定していない")
        return
    config = work / CONFIG_NAME
    if git(work, "check-ignore", "-q", CONFIG_NAME).returncode == 0:
        plan.note(f"変更なし  {CONFIG_NAME} はすでに git の無視対象")
        return
    if git(work, "ls-files", "--error-unmatch", CONFIG_NAME).returncode == 0:
        plan.note(f"警告      {CONFIG_NAME} がすでに git で管理されている。PC 固有のパスが入るので、git rm --cached で外す")
        return
    exclude = Path(git(work, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude").stdout.strip())
    entry = "/" + config.resolve().relative_to(Path(top.stdout.strip()).resolve()).as_posix()
    text = read(exclude)
    if entry in text.split("\n"):
        return
    plan.write(exclude, text.rstrip("\n") + ("\n" if text.strip() else "") + f"# LLM Wiki の setup が足した(PC ごとの vault の場所)\n{entry}\n", "git の除外")


def ensure_claude_import(work: Path, plan: Plan) -> None:
    claude = work / "CLAUDE.md"
    text = read(claude)
    if not claude.is_file():
        plan.write(claude, CLAUDE_IMPORT + "\n", "Claude Code が AGENTS.md を読み込む")
    elif not re.search(r"^\s*@(\./)?AGENTS\.md\s*$", text, re.M):
        plan.write(claude, text.rstrip("\n") + "\n\n" + CLAUDE_IMPORT + "\n", "AGENTS.md の読み込みを足す")


def enable_hooks(plan: Plan) -> None:
    top = git(VAULT_ROOT, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != VAULT_ROOT:
        plan.note(f"情報      vault({VAULT_ROOT})が git のリポジトリのルートでないので、push 前の点検は設定していない(git init の後に setup をもう一度実行する)")
        return
    # 全体設定(--global)の hooksPath は、vault のリポジトリ単位の設定で上書きしてよい
    current = git(VAULT_ROOT, "config", "--local", "--get", "core.hooksPath").stdout.strip()
    if current == ".githooks":
        plan.note("変更なし  vault の push 前の点検(core.hooksPath)")
        return
    if current:
        plan.note(f"警告      vault の core.hooksPath が {current} になっているので変えていない(.githooks/pre-push を手で組み込む)")
        return
    plan.note("設定      vault の push 前の点検(git config --local core.hooksPath .githooks)")
    if not plan.dry_run:
        git(VAULT_ROOT, "config", "--local", "core.hooksPath", ".githooks")


def link(work: Path, vault_id: str, make_default: bool, copilot: bool, plan: Plan) -> None:
    config_path = work / CONFIG_NAME
    config = load_config(config_path)
    config["$schema"] = (VAULT_ROOT / "scripts" / SCHEMA_NAME).resolve().as_uri()
    vaults = config.setdefault("vaults", {})
    existing = vaults.get(vault_id)
    if isinstance(existing, dict) and existing.get("path") and Path(existing["path"]).resolve() != VAULT_ROOT:
        plan.note(f"更新      vault「{vault_id}」の場所を {existing['path']} から {posix(VAULT_ROOT)} に変える")
    vaults[vault_id] = {**(existing if isinstance(existing, dict) else {}), "path": posix(VAULT_ROOT)}
    if make_default or not config.get("default") or config["default"] not in vaults:
        config["default"] = vault_id
    elif config["default"] != vault_id:
        plan.note(f"情報      既定の vault は「{config['default']}」のまま(--default で「{vault_id}」に変えられる)")
    plan.write(config_path, dump_config(config), "vault の場所")
    exclude_from_git(work, plan)

    block = render_block(config)
    agents = work / "AGENTS.md"
    plan.write(agents, upsert_block(read(agents), block), "llm-wiki の節")
    ensure_claude_import(work, plan)
    copilot_path = work / ".github" / "copilot-instructions.md"
    if copilot_path.is_file() or copilot:
        plan.write(copilot_path, upsert_block(read(copilot_path), block), "llm-wiki の節")
    else:
        plan.note(f"情報      {copilot_path} が無いので作っていない(VS Code の Copilot にも読ませるなら --copilot-instructions)")
    enable_hooks(plan)


def unlink(work: Path, vault_id: str, plan: Plan) -> None:
    config_path = work / CONFIG_NAME
    config = load_config(config_path)
    vaults = config.get("vaults", {})
    if vault_id not in vaults:
        raise SetupError(f"{config_path} に vault「{vault_id}」が無い(紐づいている名前: {', '.join(sorted(vaults)) or 'なし'})")
    del vaults[vault_id]
    if config.get("default") == vault_id:
        config.pop("default")
        if len(vaults) == 1:
            config["default"] = next(iter(vaults))
    targets = [work / "AGENTS.md", work / ".github" / "copilot-instructions.md"]
    if vaults:
        plan.write(config_path, dump_config(config), "vault の場所")
        block = render_block(config)
        for path in targets:
            if path.is_file() and BLOCK_RE.search(read(path)):
                plan.write(path, upsert_block(read(path), block), "llm-wiki の節")
        return
    plan.delete(config_path, "vault の場所")
    for path in targets:
        text = read(path)
        if not BLOCK_RE.search(text):
            continue
        rest = remove_block(text)
        if rest.strip():
            plan.write(path, rest, "llm-wiki の節を外す")
        else:
            plan.delete(path, "llm-wiki の節だけだった")
            claude = work / "CLAUDE.md"
            if path.name == "AGENTS.md" and read(claude).strip() == CLAUDE_IMPORT:
                plan.delete(claude, "AGENTS.md の読み込みだけだった")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="この LLM Wiki の vault を作業ディレクトリに紐づける")
    parser.add_argument("work", nargs="?", type=Path, help="紐づける作業ディレクトリ(省略すると聞く)")
    parser.add_argument("--id", help=f"vault の名前(既定: vault のフォルダ名「{slug(VAULT_ROOT.name)}」)")
    parser.add_argument("--default", action="store_true", help="この vault を作業ディレクトリの既定にする(最初に紐づけた vault は自動で既定になる)")
    parser.add_argument("--copilot-instructions", action="store_true", help=".github/copilot-instructions.md が無くても作って節を書く")
    parser.add_argument("--unlink", action="store_true", help="紐づけを外す")
    parser.add_argument("--dry-run", action="store_true", help="書き込まずに、何をするかだけを見せる")
    args = parser.parse_args(argv)

    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
    if not is_vault(VAULT_ROOT):
        print(f"vault のルートでない({VAULT_ROOT} に AGENTS.md・index.md・log.md が揃っていない)", file=sys.stderr)
        return 2
    work = args.work
    if work is None:
        if not sys.stdin.isatty():
            parser.print_usage(sys.stderr)
            return 2
        answer = input("紐づける作業ディレクトリのパス: ").strip().strip('"').strip("'")
        if not answer:
            print("パスが空なので何もしない", file=sys.stderr)
            return 2
        work = Path(answer)
    work = work.expanduser().resolve()
    if not work.is_dir():
        print(f"作業ディレクトリが無い: {work}", file=sys.stderr)
        return 2
    if work == VAULT_ROOT:
        print("vault 自身は紐づけられない(作業するリポジトリのフォルダを指定する)", file=sys.stderr)
        return 2
    vault_id = args.id or slug(VAULT_ROOT.name)
    if not ID_RE.match(vault_id or ""):
        print(f"vault の名前は英小文字・数字・- だけにする: {vault_id or '(空)'}(--id で指定する)", file=sys.stderr)
        return 2

    plan = Plan(args.dry_run)
    try:
        if args.unlink:
            unlink(work, vault_id, plan)
        else:
            link(work, vault_id, args.default, args.copilot_instructions, plan)
    except SetupError as exc:
        print(exc, file=sys.stderr)
        return 1
    title = "(--dry-run: 書き込んでいない)" if args.dry_run else ""
    action = "外した" if args.unlink else "紐づけた"
    print(f"vault「{vault_id}」({posix(VAULT_ROOT)})を {work} から{action}{title}")
    for line in plan.lines:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
