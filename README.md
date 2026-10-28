# llm-wiki

LLM エージェントが維持するナレッジ wiki(vault)のテンプレートと、それを読み書きするプラグイン。
作業の中で**裏取りできた知見だけ**を、次のセッションでそのまま前提にできる形で残す。

- vault は [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)(OKF)v0.2 に沿った、Markdown と git だけのフォルダ。ベクトル DB・埋め込み・MCP は要らない
- スキルは Claude Code と GitHub Copilot CLI の両方で動く(同じプラグインのフォルダをそのまま入れる)
- 根拠(`raw/`)とページ(`wiki/`)を分ける。根拠は足すだけで、変えない・消さない
- 規約に沿っているかは、スクリプト(`wiki_lint.py`)が LLM を使わずに検査する
- vault の場所は人ごとに違うので、作業ディレクトリのローカルな設定ファイル(`.llm-wiki.json`)で解決する。git で共有されるファイルにはパスを書かない

## 入っているもの

| 場所 | 中身 | 使い方 |
| --- | --- | --- |
| `plugin/` | スキル 3 本(`wiki-query` / `wiki-ingest` / `wiki-lint`)のプラグイン | 自分の marketplace にコピーして登録する |
| `vault-template/` | vault の雛形(規約・空の `wiki/` と `raw/`・点検・setup) | 丸ごと別の場所にコピーして、vault として使う |
| `tests/` | `setup.py` と `wiki_lint.py` のテスト | このテンプレートを直すときに使う |

`vault-template/` の中身:

| 場所 | 中身 |
| --- | --- |
| `AGENTS.md` | 規約(ページと根拠の形、格納の条件、Query / Ingest / Lint の手順、git) |
| `CLAUDE.md` | Claude Code 向けに `AGENTS.md` を読み込むだけのファイル |
| `index.md` / `log.md` | 空の一覧と空の操作ログ(OKF の予約ファイル) |
| `wiki/` / `raw/` | 空(ページと根拠はここに増えていく) |
| `setup.bat` / `setup.sh` | 作業ディレクトリと紐づける(下記)。`setup.bat` はダブルクリックで動く |
| `wiki-lint.bat` | 機械の点検をダブルクリックで実行する |
| `scripts/setup.py` / `scripts/wiki_lint.py` | 上の 2 つの本体 |
| `scripts/llm-wiki.schema.json` | `.llm-wiki.json` の JSON Schema(エディタの補完と検査に使われる) |
| `.githooks/pre-push` | push の前に機械の点検を走らせる |
| `.gitlab-ci.yml` | GitLab の MR と既定ブランチへの push で機械の点検を走らせる |

必要なもの: git と Python 3.9 以上(標準ライブラリだけで動く)。

## 使い始める

### 1. clone する

```bash
git clone https://github.com/noxitro/llm-wiki-template.git
```

### 2. プラグインを入れる

`plugin/` を、自分の marketplace(個人用のリポジトリ)の `plugins/llm-wiki/` にフォルダごとコピーし、marketplace の `.claude-plugin/marketplace.json` の `plugins` に 1 件足す。

```json
{
  "name": "llm-wiki",
  "source": "./plugins/llm-wiki",
  "description": "LLM Wiki skills: query, ingest and lint an OKF vault that keeps only verified findings."
}
```

Copilot CLI も `.claude-plugin/marketplace.json` を読むので、1 つの marketplace で両方に入る。marketplace を登録していなければ、まず登録する(`<marketplace>` は GitHub の `owner/repo` か、手元のフォルダ)。

Claude Code:

```bash
claude plugin marketplace add <marketplace>
```

```bash
claude plugin install llm-wiki@<marketplace の名前>
```

GitHub Copilot CLI:

```bash
copilot plugin marketplace add <marketplace>
```

```bash
copilot plugin install llm-wiki@<marketplace の名前>
```

marketplace を作らずに 1 回だけ試すなら、`claude --plugin-dir ./plugin` か `copilot --plugin-dir ./plugin` で起動する。

### 3. vault を作る

`vault-template/` を、vault にしたい場所へフォルダごとコピーする(例: `D:\wiki\my-wiki`)。フォルダ名が vault の名前の既定になる。ドットで始まるファイル(`.githooks` など)も一緒にコピーする。

コピーした vault を git のリポジトリにする。リモートを付けるなら、必ず非公開のものにする。

```bash
git init
```

### 4. 作業ディレクトリと紐づける(setup)

vault の `setup.bat` をダブルクリックし、紐づける作業ディレクトリ(普段エージェントを起動するリポジトリのフォルダ)のパスを入力する。コマンドで行うなら、vault で次を実行する。

```bash
./setup.sh ~/src/myapp
```

setup が作業ディレクトリに書くもの:

| ファイル | 中身 | git |
| --- | --- | --- |
| `.llm-wiki.json` | vault の名前 → この PC での場所(`{"default": "my-wiki", "vaults": {"my-wiki": {"path": "D:/wiki/my-wiki"}}}`) | 管理しない。作業ディレクトリが git の中なら `.git/info/exclude` に足す(`.gitignore` は触らない) |
| `AGENTS.md` の llm-wiki の節 | この作業ディレクトリが使う vault の名前と、参照・書き込みの決まり。パスは書かない | 管理する(チームで共有してよい) |
| `CLAUDE.md` | 無ければ `@AGENTS.md` の 1 行で作る。あって `AGENTS.md` を読み込んでいなければ、その行を足す | 管理する |
| `.github/copilot-instructions.md` | すでにあるときだけ、同じ節を書く | 管理する |

あわせて、vault が git のリポジトリなら、vault で push 前の点検を有効にする(`git config --local core.hooksPath .githooks`)。

- 何度実行しても同じ結果になる。節はマーカー(`<!-- llm-wiki:begin -->` 〜 `<!-- llm-wiki:end -->`)の間だけを書き換える。既存のファイルの残りの部分・改行コード・BOM は変えない。
- Copilot CLI と Copilot のクラウドエージェントは `AGENTS.md` を直接読む。Claude Code は `CLAUDE.md` 経由で読む。`.github/copilot-instructions.md` は Copilot のどの面(VS Code・Visual Studio を含む)でも読まれる最も互換の高い場所なので、`AGENTS.md` の読み方が面によって違うのが気になるときは `--copilot-instructions` を付けて、そちらにも書く。
- vault が作業ディレクトリの外にあるので、エージェントが vault を読むときに許可を求められることがある。止められるときは、vault を追加のディレクトリとして許可して起動する(Claude Code と Copilot CLI は `--add-dir <vault>`)。

| オプション | 意味 |
| --- | --- |
| `--id <名前>` | vault の名前(既定: vault のフォルダ名)。英小文字・数字・`-` だけ |
| `--default` | この vault を作業ディレクトリの既定にする(最初に紐づけた vault は自動で既定になる) |
| `--copilot-instructions` | `.github/copilot-instructions.md` が無くても作って節を書く |
| `--unlink` | 紐づけを外す。setup が作っただけのファイルは消し、ほかの内容は残す(`.git/info/exclude` の行は残る) |
| `--dry-run` | 書き込まずに、何をするかだけを見せる |

1 つの作業ディレクトリに複数の vault を紐づけられる(別の vault の setup を実行する)。スキルは既定の vault を使い、`--vault <名前>` で切り替える。

どの作業ディレクトリからでも同じ vault を使いたいときは、同じ形の `.llm-wiki.json` をホームフォルダ(`~/.llm-wiki.json`)に手で置く。スキルは、作業ディレクトリとその親に `.llm-wiki.json` が無いときにだけ、それを読む。

## 使い方

エージェントには次のように頼む。

| 頼み方 | 動作 |
| --- | --- |
| 「wiki に聞いて: 〜」 | wiki を読み、出典つきで答える。書き込まない |
| 「格納する知見はある?」 | このセッションの作業から候補を 0〜3 件挙げて裏取りし、表で見せる。承認されたものだけを書いてコミットする |
| 「wiki を点検して」 | 機械の点検と意味の点検を行い、表で報告する。承認された項目だけを直す |

push は人が行う。

## OKF との関係

OKF は、Markdown と YAML の frontmatter だけでナレッジを持ち運ぶための公開仕様(Google Cloud、Apache 2.0)。この vault は OKF の適合条件を満たすので、OKF を読めるほかのツールにもそのまま渡せる。

- 予約ファイル(`index.md`・`log.md`)以外のすべての `.md` が、`type` を持つ frontmatter を持つ。ページは `Finding`、根拠は `Evidence`、規約は `Schema`。
- `index.md` は `* [題名](パス) - 説明` の一覧、`log.md` は `## YYYY-MM-DD` の見出しで新しいものを上に積む。
- ページの `sources`(根拠)、`generated`(誰がいつ書いたか)、`verified`(誰がいつ確かめたか)、`status`、`stale_after` は OKF の項目をそのまま使う。人が根拠と突き合わせたページには `verified` に `human:<名前>` が入り、OKF の「人がレビュー済み」になる。
- この規約が足しているのは、確度(`confidence: ◎ / ○`)、最初に書いた日(`created`)、根拠ファイルの `date`・`kind`・`watch`。OKF は知らないキーを無視してよいと決めているので、ほかのツールでも読める。
- ページ同士は `[[ページ名]]` でなく、Markdown のリンク(相対パス)でつなぐ。

形の細部は [vault-template/AGENTS.md](vault-template/AGENTS.md) にある。

## チームで使う

個人の vault と同じ規約のまま、数人のチームで 1 つの vault を育てるときの形。Web 公開(Pages)は作らない。閲覧は clone した Markdown を直接開く(Obsidian か、エディタの Markdown プレビュー)。

1. `vault-template/` から非公開のリポジトリを作る。各自は好きな場所に clone してよい。
2. 各自が自分の clone で setup を実行し、作業リポジトリと紐づける。**vault の名前は全員で揃える**(`--id <名前>`)。作業リポジトリの `AGENTS.md` の節には名前だけが入るので、それをコミットして共有できる。`.llm-wiki.json` は各自の手元にだけ置かれる。
3. vault の `AGENTS.md` の「git」の「書き込むブランチ」の行を、`ingest/<YYYY-MM-DD>-<短い名前>` のブランチを切る形に書き換える(規約の変更として `log.md` に `**Schema**` の項目で残す)。エージェントはそのブランチにコミットし、push と MR は本人が行う。マージは決めた人(リーダー)だけが行う。未マージのブランチは他の人のエージェントに読まれないので、確認前の知見が次の回答の根拠になることはない。
4. 話題の範囲が複数あるなら、`wiki/` と `raw/` をドメインのサブフォルダで分ける(例: `wiki/common/`、`wiki/plan-a/`)。
5. 題材のリポジトリのファイルを根拠にしたページは、`watch` で「要再確認」が出る。移植や改修の途中は題材が毎日変わるので、**CI では `--fail-on-stale` を付けず警告のままにし**、週 1 回の見直しで取り直す。`wiki-lint.repos.json` は各自の手元にだけ置く(CI には題材リポジトリが無いので、`watch` は手元でだけ確かめられる)。
6. 題材が Shift-JIS(CP932)のソースなら、`raw/` に抜粋を写すときに UTF-8 へ変換する。機械の点検は UTF-8 で読めないファイルをエラーにする。
7. 確度は規約どおり ◎ と ○ の 2 段階だけにし、推定のラベルを足さない。

## 機械の点検(wiki_lint.py)

vault の `wiki-lint.bat` をダブルクリックするか、vault で次を実行する。

```bash
python scripts/wiki_lint.py
```

エラーが 1 件でもあれば終了コード 1 を返す。CI と pre-push はこれで止まる。

| 種類 | 点検すること |
| --- | --- |
| エラー | OKF の適合: 予約ファイル以外の `.md` に frontmatter が無い・読めない、`type` が無い(ドットで始まるフォルダは対象外) |
| エラー | ページの frontmatter: `title`・`description`・`created`・`generated`・`verified`・`confidence`・`sources` が揃っていない、日時が時差つきの ISO 8601 でない、書き手の形が違う、`confidence` が ◎ か ○ でない、`status` の値が違う |
| エラー | `sources` が空、`/raw/` の外を挙げている、挙げた根拠ファイルが無い、`id` が重なっている、脚注 `[^id]` に対応する `id` が無い |
| エラー | 見出しか **要点** が無い、推定のラベル(△ ▲)がある、`[[リンク]]` の形がある、リンク先が無い・バンドルの外 |
| エラー | `index.md` に載っていないページ・二重に載っているページ・無いファイルへの行がある、ルート以外の `index.md` に frontmatter がある |
| エラー | `log.md` の日付の見出しが `## YYYY-MM-DD` でない・新しい順でない・同じ日付が 2 回ある、項目が `* **Ingest\|Lint\|Schema** HH:MM 要旨` でない |
| エラー | 根拠ファイルの `type` が `Evidence` でない、`date`・`kind`・`watch` の形が違う |
| エラー | 既存の根拠ファイルが変わった・消えた、`log.md` の既存の行が変わった・消えた(比べる相手があるときだけ。下記) |
| エラー | 認証情報らしき文字列(API キー・トークン・秘密鍵)がある、UTF-8 で読めないファイルがある |
| 警告 | 要再確認: `watch` に書いた題材のファイルが記録したコミット以降に変わった、`stale_after` を過ぎた(`--fail-on-stale` でエラーにできる) |
| 警告 | `watch` を確かめられない: 題材の場所が git のリポジトリでない、コミットが無い、そのコミットにパスが無い |
| 警告 | 見出しが `title` と違う、`index.md` の題名・説明がページと違う・行の形が違う、`okf_version` が無い、ファイル名が別のフォルダと重なっている、孤立ページ、どのページにも引用されていない根拠ファイル、`log.md` のその日の時刻が新しい順でない、規約が変わったのに `log.md` に記録が無い |
| 情報 | 未解決の矛盾(`> ⚠️ 矛盾:`)があるページ、廃止(`deprecated`)のページへのリンク、確かめられなかった項目 |

**比べる相手**: 根拠が「足すだけ」、`log.md` が「既存の行を変えない」になっているかは、過去のコミットと比べて確かめる。

- 手元で実行したとき: upstream(push 先のブランチ)と、作業ツリー(未コミットの変更を含む)を比べる。upstream が無ければ確かめない。
- pre-push: 送り先にすでにあるコミットと、push するコミットを比べる。新しいブランチなら、送り先の既定ブランチ(`refs/remotes/<リモート>/HEAD`)と比べる。それも無いとき(空のリモートへの最初の push)は確かめない。
- CI: MR の起点(MR のとき)か、push 前の先端(既定ブランチのとき)と比べ、確かめられないときはエラーにする(`--require-history`)。ただし、既定ブランチへの最初の push は比べる相手が無いので確かめない。

| オプション | 意味 |
| --- | --- |
| `--base <ref>` | 履歴を比べる相手 |
| `--head <ref>` | 履歴の点検で base と比べる側(既定: 作業ツリー) |
| `--repos <path>` | `watch` のリポジトリ名と手元の場所の対応(既定: `wiki-lint.repos.json`) |
| `--fail-on-stale` | 要再確認をエラーにする |
| `--require-history` | 履歴を確かめられないときをエラーにする |

題材のリポジトリの変化を点検に使うなら、vault 直下に `wiki-lint.repos.json` を作る(git では管理しない。人ごとに場所が違うため)。

```json
{ "myapp": "D:/src/myapp" }
```

意味の点検(本文が根拠に沿っているか、重複、矛盾、要再確認の取り直し)はスクリプトではできないので、エージェントに「wiki を点検して」と頼む。手順は [vault-template/AGENTS.md](vault-template/AGENTS.md) の「Lint」にある。

## 前の形の vault から移る

`[[ページ名]]` のリンクや `created` / `updated` だけの frontmatter を使っていた前の形の vault は、この点検でエラーになる。移るときは、新しい `AGENTS.md` と `scripts/` を vault に写し、点検のエラーを 1 つずつ直す(ページに `type`・`title`・`description`・`generated`・`verified`・`confidence` を足す、`sources` を `{ id, resource: /raw/... }` の形にする、リンクを Markdown のリンクにする、`index.md` と `log.md` を新しい形にする)。`log.md` の書き換えは既存の行の変更になるので、移る操作のコミットだけは、点検の履歴の比較(pre-push)を通らない。そのコミットは人が確かめて push する。

## このテンプレートを直す

```bash
python -m unittest discover -s tests
```

GitHub Actions でも同じテストと、`vault-template/` の機械の点検が走る(`.github/workflows/test.yml`)。

## License

[MIT](LICENSE)
