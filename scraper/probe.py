"""一回きり：開催一覧（レース名入り）が、前日の夜・当日の深夜にもう出ているかの確認。"""
import json, requests
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
for D in ("20261125", "20261126"):
    t = requests.get(f"https://race.boatcast.jp/api_txt/getHoldingList2_{D}.json", headers=H, timeout=20); t.encoding = "utf-8"
    print("=====", D, t.status_code, len(t.text))
    try:
        for h in json.loads(t.text).get("return_info", [])[:3]:
            print(h.get("RaceStudiumNo"), h.get("RaceGrade"), h.get("DailyTitle"), [x.strip() for x in h.get("RaceTitleAll") or []])
    except Exception as e:
        print("not json", repr(t.text[:200]))
