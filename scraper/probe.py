"""一回きり：11/24 開催一覧の RaceGrade の値（常滑 SG＋G2 の併催が「一般」になる理由の確認）。"""
import json, requests
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
t = requests.get("https://race.boatcast.jp/api_txt/getHoldingList2_20261124.json", headers=H, timeout=20); t.encoding = "utf-8"
for h in json.loads(t.text).get("return_info", []):
    print(h.get("RaceStudiumNo"), repr(h.get("RaceGrade")), h.get("HoldingTitle"), {k: v for k, v in h.items() if "rade" in k or "Kbn" in k})
