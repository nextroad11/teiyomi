"""一回きり：競技情報ページ（平和島）のメニューで「直前情報」がどこへ飛ぶかと、JSの中身（boatrace.jp には一切アクセスしない）。"""
import json, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
out = Path(sys.argv[1])
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
rep = {}
for u in ["https://www.heiwajima.gr.jp/asp/kyogi/04/pc/syusso0101.htm", "https://www.heiwajima.gr.jp/asp/kyogi/04/pc/kekka0101.htm"]:
    r = requests.get(u, headers=H, timeout=20); r.encoding = r.apparent_encoding; t = r.text
    ctx = [m.group(0) for m in re.finditer(r".{0,300}(直前|展示|kekka|syusso0).{0,200}", t)][:30]
    js = [urljoin(u, s) for s in re.findall(r'<script[^>]+src="([^"]+)"', t, re.I)]
    jsctx = {}
    for s in js:
        if urlparse(s).netloc != urlparse(u).netloc: continue
        try:
            b = requests.get(s, headers=H, timeout=20).text
            jsctx[s] = [m.group(0) for m in re.finditer(r".{0,160}(\.htm|\.php|\.json|chokuzen|tenji|before|kyogi).{0,120}", b)][:25]
        except Exception as e: jsctx[s] = [str(e)]
        time.sleep(1.5)
    rep[u] = {"ctx": ctx, "js": js, "jsctx": jsctx}
    time.sleep(2)
(out / "p8.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
