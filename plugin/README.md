# llm-wiki プラグイン

LLM Wiki を読み書きするスキル 3 本を入れるプラグイン。Claude Code と GitHub Copilot CLI の両方で、同じフォルダのまま使える(どちらも `.claude-plugin/plugin.json` と `skills/<名前>/SKILL.md` を読む)。

| スキル | 頼み方 | vault に書くか |
| --- | --- | --- |
| `wiki-query` | 「wiki に聞いて: 〜」 | 書かない |
| `wiki-ingest` | 「格納する知見はある?」「wiki に取り込んで」 | 書く(人の承認の後だけ) |
| `wiki-lint` | 「wiki を点検して」 | 書く(人の承認の後だけ) |

どのスキルも、先頭に `--vault <名前>` を付けると既定以外の vault を対象にする。

スキルは vault の場所を、作業フォルダ(またはその親)の `.llm-wiki.json` から読む。このファイルは vault の `setup` が作る。規約の中身はスキルに書いておらず、vault の `AGENTS.md` を読んで従う。

導入の手順はリポジトリの [README](../README.md) の「2. プラグインを入れる」にある。
