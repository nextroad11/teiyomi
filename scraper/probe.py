"""公式の結果ページの形式（決まり手・人気・スタートタイミング）を確かめる一回きりの下見。"""
import sys, time
from pathlib import Path
import requests
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
for jcd, rno in [("09", 9), ("16", 4), ("23", 8)]:
    u = f"https://www.boatrace.jp/owpc/pc/race/raceresult?rno={rno}&jcd={jcd}&hd=20261114"
    r = requests.get(u, headers=H, timeout=20)
    (out / f"raceresult_{jcd}_{rno}.html").write_bytes(r.content)
    print(r.status_code, len(r.content), u)
    time.sleep(1)
