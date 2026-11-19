"""一回きり：各場トップの「直前情報」タブがどこからデータを読んでいるかを、サイト自身のJSから調べる（boatrace.jp には一切アクセスしない）。"""
import json, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
out = Path(sys.argv[1])
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
V = json.loads((out / "venues.json").read_text(encoding="utf-8"))
rep = {}
for j, x in V.items():
    top = x["top_final"]; host = urlparse(top).netloc
    t = (out / f"{int(j):02d}_top.html").read_text(encoding="utf-8")
    js = [urljoin(top, s) for s in re.findall(r'<script[^>]+src="([^"]+)"', t, re.I)]
    js = [u for u in js if urlparse(u).netloc == host and "jquery" not in u.lower()][:6]
    found = set()
    for src in [t] + js:
        if src.startswith("http"):
            try:
                r = requests.get(src, headers=H, timeout=20); body = r.text
            except Exception: continue
            time.sleep(1.5)
        else: body = src
        for m in re.finditer(r'["\']((?:https?:)?/[^"\'\s]*?(?:\.php|\.json|\.htm|\.html|/api/|ajax)[^"\'\s]*)["\']', body):
            u = m.group(1)
            if re.search(r"cyokuzen|chokuzen|tenji|before|kekka|result|race|odds|syusso|shusso|live|api|ajax|json", u, re.I): found.add(u[:160])
        for m in re.finditer(r'.{0,80}(cyokuzen|chokuzen|tenji).{0,120}', body):
            found.add("CTX " + m.group(0)[:200].replace("\n", " "))
    rep[j] = {"host": host, "js": js, "found": sorted(found)[:40]}
    print(j, host, len(found), flush=True)
(out / "p4.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
