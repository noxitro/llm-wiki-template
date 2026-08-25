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

`origin` が削除されたことを確認してから、wiki の内容を追加してください。

```powershell
git remote -v  # 出力が空であること
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

次の PowerShell スクリプトは、グローバル指示を作成し、必要なら wiki へのリンクも作成する。既存の `%USERPROFILE%\.copilot\copilot-instructions.md` は `-Force` を明示しない限り上書きしない。

### 推奨: Junction を作成する

Windows では管理者権限や Developer Mode を必要としない Junction を既定にする。以下は、クローン済みのリポジトリ直下で実行する例。

```powershell
.\scripts\setup-copilot-wiki.ps1 `
  -LinkPath "$env:USERPROFILE\llm-wiki"
```

Junction は Git で管理しないローカル専用のリンクである。別のマシンでは clone 後にこのコマンドを再実行する。

### Symbolic Link を使う場合

Symbolic Link は管理者権限または Windows の Developer Mode が必要であり、通常権限では作成に失敗する。その環境要件を満たす場合だけ、次のように明示する。

```powershell
.\scripts\setup-copilot-wiki.ps1 `
  -LinkPath "$env:USERPROFILE\llm-wiki" `
  -UseSymbolicLink
```

リンクが不要な場合は、クローン直下で `.\scripts\setup-copilot-wiki.ps1` を実行する。作成後は、設定したパスを CLI に許可する。

```powershell
copilot --add-dir "$env:USERPROFILE\llm-wiki"
```

セットアップの確認:

```powershell
Test-Path "$env:USERPROFILE\llm-wiki\index.md"  # True
Get-Content "$env:USERPROFILE\.copilot\copilot-instructions.md"
```

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
