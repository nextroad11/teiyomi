"""BOATCAST のオリジナル展示データ（一周・まわり足・直線）の形式を確かめる一回きりの下見。"""
import sys, time
from pathlib import Path
import requests
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
log = []
for jo, rno in [("12", "01"), ("12", "1"), ("12", "11"), ("11", "01"), ("04", "01")]:
    for kind, d in [("bc_oriten", "txt"), ("bc_j_tkz", "hp_txt")]:
        u = f"https://race.boatcast.jp/{d}/{jo}/{kind}_20261105_{jo}_{rno}.txt"
        try:
            r = requests.get(u, headers=H, timeout=20)
            log.append(f"{r.status_code} {len(r.content)} {u}")
            if r.status_code == 200:
                (out / f"{kind}_{jo}_{rno}.txt").write_bytes(r.content)
        except Exception as e:
            log.append(f"ERR {u} {e}")
        time.sleep(1)
(out / "log.txt").write_text("\n".join(log), encoding="utf-8")
print("\n".join(log))
