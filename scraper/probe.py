"""一回きり：11/17 の結果ページを読み直して、決まり手・本番のSTを入れる（払戻だけ先に取れていたため）。"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import teiyomi_scraper as t
root = Path(sys.argv[1]).parent.parent          # data/debug/probe → data
hd = "20261117"
path = root / f"{hd}.json"
day = json.loads(path.read_text(encoding="utf-8"))
n = 0
for r in day["races"]:
    res = r.get("result") or {}
    if res and not t.result_incomplete(res):
        continue
    html = t.get(f"{t.BASE}/raceresult?rno={r['rno']}&jcd={r['jcd']:02d}&hd={hd}")
    p = t.parse_result(html) if html else None
    if p:
        p["redoneY"] = True
        r["result"] = p
        n += 1
t.write_json(path, day)
left = sum(1 for r in day["races"] if not r.get("result") or t.result_incomplete(r["result"]))
msg = f"{hd}: 読み直し {n}レース・まだ欠け {left}レース"
(Path(sys.argv[1])).mkdir(parents=True, exist_ok=True)
(Path(sys.argv[1]) / "redo.txt").write_text(msg, encoding="utf-8")
print(msg)
