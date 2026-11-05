"""過去レースのオリジナル展示（一周・まわり足・直線など）を BOATCAST から少しずつ集める。

保存先: data/oriten/YYYYMMDD.json  {"races": {"12-01": {"items": [...], "boats": {"1": [...]}}, ...}}
history/ にある日を新しい順に埋める。1秒に1回まで。--minutes で区切る。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from teiyomi_scraper import BOATCAST, parse_oriten  # noqa: E402

H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--minutes", type=float, default=40)
    a = ap.parse_args()
    root = Path(a.data)
    out = root / "oriten"
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session(); s.headers.update(H)
    t0, got, days = time.time(), 0, 0
    files = sorted((f for f in (root / "history").glob("2*.json")), reverse=True)
    for f in files:
        dst = out / f.name
        races = json.loads(f.read_text(encoding="utf-8")).get("races", [])
        done = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {"races": {}, "missing": []}
        todo = [r for r in races if f'{r["jcd"]:02d}-{r["rno"]:02d}' not in done["races"]
                and f'{r["jcd"]:02d}-{r["rno"]:02d}' not in done["missing"]]
        if not todo:
            continue
        for r in todo:
            if time.time() - t0 > a.minutes * 60:
                break
            key = f'{r["jcd"]:02d}-{r["rno"]:02d}'
            url = f'{BOATCAST}/txt/{r["jcd"]:02d}/bc_oriten_{r["date"]}_{r["jcd"]:02d}_{r["rno"]:02d}.txt'
            try:
                resp = s.get(url, timeout=20)
                p = parse_oriten(resp.content.decode("utf-8", "replace")) if resp.status_code == 200 else None
            except requests.RequestException:
                p = None
            if p:
                done["races"][key] = p; got += 1
            else:
                done["missing"].append(key)
            time.sleep(1)
        dst.write_text(json.dumps(done, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        days += 1
        if time.time() - t0 > a.minutes * 60:
            print("時間切れ。続きは次回", flush=True)
            break
    print(f"オリジナル展示 {got}レース（{days}日分を更新）", flush=True)
    Path("/tmp/oriten_new").write_text(str(got))


if __name__ == "__main__":
    main()
