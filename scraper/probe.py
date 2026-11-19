"""一回きり：BOATCASTの開催一覧（締切時刻）を確認（boatrace.jp・mbrace には一切アクセスしない）。"""
import sys, time, json, requests
from pathlib import Path
out = Path(sys.argv[1]); (out / "bc").mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
rep = {}
for p in ["/api_txt/getHoldingList2_20261120.json", "/api_txt/getHoldingList2_20261119.json", "/api_txt/getEndRaceList2_20261119_04.json", "/api/getServerDateTime.php"]:
    x = requests.get("https://race.boatcast.jp" + p, headers=H, timeout=20); x.encoding = "utf-8"
    rep[p] = {"status": x.status_code, "body": x.text[:6000]}; print(p, x.status_code, len(x.content)); time.sleep(2)
(out / "bc" / "hold.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
