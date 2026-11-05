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
base = "https://race.boatcast.jp"
top = get(base + "/", "rtop.html")
for m in sorted(set(re.findall(r'(?:src|href)="([^"]+)"', top)))[:60]:
    log.append(f"  ref {m}")
srcs = [x for x in re.findall(r'(?:src|href)="([^"]+\.js[^"]*)"', top) if "googletag" not in x]
seen = set()
def scan(u, depth):
    if u in seen or len(seen) > 25: return
    seen.add(u)
    js = get(u, f"r{len(seen)}.js")
    for m in sorted(set(re.findall(r'["\'`]((?:https?://|/)[A-Za-z0-9_\-/.:${}?=&]+)["\'`]', js)))[:150]:
        log.append(f"  {u.rsplit('/',1)[-1][:30]} -> {m}")
    if depth < 2:
        for imp in re.findall(r'from\s*["\']([^"\']+\.js)[^"\']*["\']|import\(["\']([^"\']+)["\']\)', js):
            x = imp[0] or imp[1]
            scan(x if x.startswith("http") else base + (x if x.startswith("/") else "/" + u.split(base)[-1].rsplit("/",1)[0].lstrip("/") + "/" + x.lstrip("./")), depth + 1)
for s_ in srcs[:8]:
    scan(s_ if s_.startswith("http") else base + ("" if s_.startswith("/") else "/") + s_, 0)
(out / "log.txt").write_text("\n".join(log), encoding="utf-8")
print("\n".join(log))
