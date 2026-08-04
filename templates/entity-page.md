---
type: entity
domain: tech
tags: [framework, example]
created: 2026-08-04
updated: 2026-08-04
sources: ["https://github.com/example-org/example-framework", "実プロジェクト構成の観察(2026-08)"]
---

<!--
entityページの雛形: ツール・ライブラリ・リポジトリ等の「対象」を1ページにし、
関連知見のハブとして育てる。URLは属性、価値は下部の「知見」リンク集積にある。
このファイルはテンプレートなので wiki/ にコピーして書き換えること。
-->

# ExampleFramework

## 基本情報

- 公式リポジトリ: https://github.com/example-org/example-framework — 本体
- 使用バージョン: v4.2(2026-08時点。更新したらここと`updated`を直す)
- 用途: ◯◯プロジェクトの基盤フレームワーク

## 関連リポジトリと相関

- example-plugin-auth: https://github.com/example-org/example-plugin-auth — 認証プラグイン。本体のマイナーバージョンに追従が必要 ○
- example-framework-fork: (社内リポジトリ) — 本家のフォーク。差分は◯◯対応のパッチのみ。本家vUpのたびにrebase運用 ○

## ファイル形式の知識

- `.exf` — 本フレームワーク独自の設定バンドル形式。実体はzip(拡張子を変えると展開できる)△。公式仕様: <ドキュメントURL> ◎
- `.exf.lock` — 依存解決のロックファイル。手動編集禁止 ◎

## 知見

<!-- ingestや実作業で得た知見ページへのリンクがここに集まる -->
- [[ExampleFrameworkのビルドの罠]]
- [[ExampleFrameworkのアップグレード手順]]
