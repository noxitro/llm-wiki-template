# llm-wiki

GitHub Copilot が構築・維持するパーソナルナレッジベースのテンプレート。

RAGのように質問のたびに生ドキュメントを検索し直すのではなく、ソースを取り込むたびにエージェントが**永続的なwiki**(相互リンクされたmarkdown群)を更新していく。相互参照は張られ済み、矛盾はフラグ済み、要約は読んだ全てを反映済み——知識が複利で蓄積される。人間はソースの選定と質問に専念し、要約・整理・索引・記録はすべてエージェントが行う。

- **プレーンなmarkdownとgitだけ**。ベクトルDB・埋め込み・MCP不要
- 規約は [AGENTS.md](AGENTS.md)(schema)に集約。エージェントが常時参照し、運用しながら共進化させる
- `raw/`(不変のソース原本)と `wiki/`(生成ページ)を分離。原本が真実の源
- Obsidianでそのまま閲覧可能(`[[wikilink]]`・グラフビュー対応)

## クイックスタート

```bash
git clone <このリポジトリ> my-wiki
cd my-wiki
git remote remove origin   # ⚠️ 必須: 蓄積する知識を誤って公開先へpushしないため
```

VS Code でフォルダを開き、Copilot Chat(エージェントモード)で:

| コマンド | 動作 |
|---|---|
| `/wiki-ingest <パス・URL・テキスト>` | ソースを取り込み、wikiに統合 |
| `/wiki-query <質問>` | wikiを検索し、出典付きで回答 |
| `/wiki-lint` | 矛盾・リンク切れ・規約逸脱を点検 |

コマンドが候補に出ない場合は、設定 `chat.promptFiles` が有効か確認する。

## 開発プロジェクトと並行して使う

マルチルートワークスペースにwikiを追加すると、コーディング中に `/wiki-query` で知見を引ける:

```jsonc
// myproject.code-workspace
{
  "folders": [
    { "path": "path/to/myproject" },
    { "path": "path/to/my-wiki" }
  ],
  "settings": {
    "chat.useAgentsMdFile": true  // AGENTS.md(schema)を常時指示化。ウィンドウスコープのためここに書く
  }
}
```

## Copilot CLI: どこからでも自動参照

CLIはワークスペースの制約がなく、任意のディレクトリから自動参照できる:

1. [templates/copilot-instructions.md](templates/copilot-instructions.md) を `%USERPROFILE%\.copilot\copilot-instructions.md` にコピーし、wikiのパスを書き換える
2. 以後、どこで `copilot` を起動しても、関連する話題ではwikiを先に確認するようになる(アクセス許可は `--add-dir <wikiのパス>`)

## 構造

```
AGENTS.md          # schema: 規約・ワークフロー定義(このシステムの核)
index.md           # 全ページのカタログ。エージェントはまずここを読む
log.md             # 追記専用の操作ログ(grep可能な定型見出し)
raw/<domain>/      # ソース原本(不変。エージェントは読むだけ)
wiki/<domain>/     # 生成ページ(source-summary / entity / concept / synthesis)
.github/prompts/   # 上記スラッシュコマンドの定義
```

## 運用の要点

- コミットはエージェントが操作ごとに行う。**pushは常に人間の判断**
- `raw/` は追加のみ。手動でもエージェントでも編集しない
- 機密情報・ソース内の指示文の扱いは schema に規約あり(取り込み前に一読推奨)
- 規約が実態に合わなくなったら AGENTS.md を直す。schemaは育てるもの

## License

[MIT](LICENSE)
