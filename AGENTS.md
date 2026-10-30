# llm-wiki テンプレートの開発

このリポジトリは、LLM Wiki のテンプレートそのものを作る場所。ここ自体は vault ではない。

| 場所 | 中身 |
| --- | --- |
| `plugin/` | Claude Code と GitHub Copilot CLI のプラグイン(スキル 3 本)。使う人が自分の marketplace にコピーする |
| `vault-template/` | vault の雛形。使う人が丸ごと別の場所にコピーする。**vault の規約はその中の `AGENTS.md`** |
| `tests/` | `vault-template/scripts/` の `wiki_lint.py` と `setup.py` のテスト |

- vault の規約(`vault-template/AGENTS.md`)を変えたら、点検(`wiki_lint.py`)・スキル(`plugin/skills/`)・README が同じ変更で揃っているかを確かめる。規約の中身はスキルに写さない(スキルは「vault の AGENTS.md を読んで従う」だけにする)。
- `vault-template/log.md` と `index.md` は空のまま保つ(このリポジトリの開発の履歴を書かない)。
- テスト: `python -m unittest discover -s tests`。点検: `python vault-template/scripts/wiki_lint.py`。
- スクリプトは Python 3.9 以上の標準ライブラリだけで書く(使う人の PC に追加のインストールを求めない)。
- 機能を変えたら README.md(日本語)を同じ変更で直す。
