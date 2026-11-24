"""一回きり：11/24 尼崎10R の開催一覧（締切時刻・中止）の中身を確認。"""
import json, requests
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
t = requests.get("https://race.boatcast.jp/api_txt/getHoldingList2_20261124.json", headers=H, timeout=20); t.encoding = "utf-8"
print(t.status_code)
for h in json.loads(t.text).get("return_info", []):
    if str(h.get("RaceStudiumNo")).lstrip("0") == "13":
        for k, v in h.items(): print(k, json.dumps(v, ensure_ascii=False)[:400])
