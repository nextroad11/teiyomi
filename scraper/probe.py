"""一回きり：11/24 尼崎10Rの出走表（bc_j_str3）が取れない理由の確認。9Rと比べる。"""
import sys, requests
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
for rno in (9, 10):
    t = requests.get(f"https://race.boatcast.jp/hp_txt/13/bc_j_str3_20261124_13_{rno:02d}.txt", headers=H, timeout=20); t.encoding = "utf-8"
    print("=====", rno, t.status_code, len(t.text))
    for l in t.text.splitlines():
        c = l.split("\t"); print(len(c), repr(l[:160]))
