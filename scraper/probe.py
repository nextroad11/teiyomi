"""BOATCAST のオリジナル展示データの取り方を調べるための一回きりの下見。
トップと、そこから読み込まれるスクリプトを保存し、データの取得先（API）を探す。"""
import re, sys, time
from pathlib import Path
import requests

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
log = []
def get(url, name):
    try:
        r = requests.get(url, headers=H, timeout=20)
        log.append(f"{r.status_code} {len(r.content)} {url}")
        if r.status_code == 200:
            (out / name).write_bytes(r.content)
            return r.text
    except Exception as e:
        log.append(f"ERR {url} {e}")
    time.sleep(1)
    return ""
top = get("https://boatcast.jp/", "top.html")
srcs = re.findall(r'(?:src|href)="([^"]+\.js[^"]*)"', top)
for i, s in enumerate(srcs[:12]):
    u = s if s.startswith("http") else "https://boatcast.jp" + ("" if s.startswith("/") else "/") + s
    js = get(u, f"js{i}.js")
    for m in sorted(set(re.findall(r'["\'`](/?[A-Za-z0-9_\-/.]*(?:tenji|exhibit|original|api)[A-Za-z0-9_\-/.{}$]*)["\'`]', js)))[:80]:
        log.append(f"  path {m}")
for u, n in [("https://boatcast.jp/race", "race.html"), ("https://boatcast.jp/api/", "api.txt")]:
    get(u, n)
(out / "log.txt").write_text("\n".join(log), encoding="utf-8")
print("\n".join(log))
