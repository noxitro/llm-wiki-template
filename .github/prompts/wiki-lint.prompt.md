---
mode: agent
description: LLM Wikiの健全性チェック(矛盾・リンク切れ・規約逸脱の点検)
---

# /wiki-lint

このワークスペース内の LLM Wiki リポジトリの健全性を点検し、レポートします。wikiルートは「`AGENTS.md`・`index.md`・`log.md`・`wiki/` を併せ持つフォルダ」で判別すること(AGENTS.md の有無だけで判別しない)。

## 手順

1. まず wiki ルートの `AGENTS.md`(schema)を読む。以降の操作はすべてその規約に従う。
2. schema の「Lint(健全性チェック)」ワークフローを実行する:
   - ページ間の矛盾、陳腐化した記述
   - 孤立ページ、リンク切れ
   - ページ化されていない重要概念
   - index.md との不整合
   - schema規約からの逸脱(frontmatter欠落、log形式違反)
3. 結果を一覧でレポートする。**修正はユーザーが承認した項目のみ**実施し、実施した場合は log 追記 → git commit。
