"""一回きり：芦屋のスタート展示ファイルの形を確認（BOATCASTのみ）。"""
import sys, requests
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
for j in ("21", "14"):
    t = requests.get(f"https://race.boatcast.jp/hp_txt/{j}/bc_j_stt_20261120_{j}_01.txt", headers=H, timeout=20); t.encoding = "utf-8"
    print("=====", j, t.status_code); print(repr(t.text[:600]))
