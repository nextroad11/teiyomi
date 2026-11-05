"""BOATCAST のオリジナル展示データ（一周・まわり足・直線）の形式を確かめる一回きりの下見。"""
import sys, time
from pathlib import Path
import requests
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
log = []
# 過去のどこまで残っているか（学習に使えるか）
for day, jo in [("20261001", "12"), ("20260801", "12"), ("20260501", "12"), ("20260101", "12"), ("20251106", "12"), ("20250601", "12"), ("20240601", "12")]:
    for kind, d in [("bc_oriten", "txt")]:
        rno = "01"
        u = f"https://race.boatcast.jp/{d}/{jo}/{kind}_{day}_{jo}_{rno}.txt"
        try:
            r = requests.get(u, headers=H, timeout=20)
            log.append(f"{r.status_code} {len(r.content)} {u}")
            if r.status_code == 200:
                (out / f"{kind}_{day}_{jo}.txt").write_bytes(r.content)
        except Exception as e:
            log.append(f"ERR {u} {e}")
        time.sleep(1)
(out / "log.txt").write_text("\n".join(log), encoding="utf-8")
print("\n".join(log))
