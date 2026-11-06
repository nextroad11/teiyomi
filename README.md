# ashi ブランチ：平和島・浜名湖・びわこ・大村・下関・多摩川の足スコア検証（一般戦）

BOATCASTのオリジナル展示（一周・まわり足・直線）と展示タイムを、枠ごとの補正後に6艇の相対値（z）にして重みづけした「足スコア」が、どれだけ足の良し悪しを見分けられているかを日々検証する。

- `data/heiwajima.txt` `data/hamanako.txt` `data/biwako.txt` `data/omura.txt` `data/shimonoseki.txt` `data/tamagawa.txt`：1レース1行のデータ（9月〜はBOATCAST画面から収集、以降は data ブランチの history/ と oriten/ から自動追記）
- `data/grades.json`：日付ごとのグレード（SG・G1・G2は分析から除外）
- `config.json`：採用式と比較する式、場ごとの対象期間（since＝新モーター導入後）
- `daily.py DATA_DIR`：追記＋分析、`reports/YYYYMMDD.md` を作成（採用式の検証＋場専用補正の検証）
- 補正値（枠別）：`lib/gama.py` の CORR
