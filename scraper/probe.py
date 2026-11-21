"""一回きり：BOATCASTのオッズのファイル（3連単・確定と締切前）の形を確認。"""
import sys, requests
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
for kind in ("kakutei_od3", "smt_od3"):
    t = requests.get(f"https://race.boatcast.jp/txt/01/bc_{kind}_20261121_01_01.txt", headers=H, timeout=20); t.encoding = "utf-8"
    print("=====", kind, t.status_code, len(t.text)); print(repr(t.text[:900]))
