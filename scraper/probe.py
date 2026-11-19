"""一回きり：直前情報ページ（yoso05）の数値をどこから読んでいるか（boatrace.jp には一切アクセスしない）。"""
import json, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
out = Path(sys.argv[1])
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
rep = {}
for u in ["https://www.heiwajima.gr.jp/asp/kyogi/04/pc/yoso0512.htm", "https://www.marugameboat.jp/asp/kyogi/15/pc/yoso0512.htm"]:
    r = requests.get(u, headers=H, timeout=20); r.encoding = r.apparent_encoding; t = r.text
    i = t.find("展示タイム")
    snippet = re.sub(r"\s+", " ", t[max(0, i - 500): i + 3500])
    inline = [m.group(0)[:300] for m in re.finditer(r"<script(?![^>]*src)[^>]*>.*?</script>", t, re.S) if re.search(r"tenji|json|ajax|\.php|\.csv|\.txt|getJSON|fetch", m.group(0), re.I)][:10]
    js = [urljoin(u, s) for s in re.findall(r'<script[^>]+src="([^"]+)"', t, re.I)]
    jsctx = {}
    for s in js:
        if urlparse(s).netloc != urlparse(u).netloc or "jquery" in s.lower(): continue
        try:
            b = requests.get(s, headers=H, timeout=20).text
            jsctx[s] = [re.sub(r"\s+", " ", m.group(0)) for m in re.finditer(r".{0,160}(json|ajax|getJSON|\.php|\.csv|\.txt|tenji|orig).{0,160}", b, re.I)][:25]
        except Exception as e: jsctx[s] = [str(e)]
        time.sleep(1.5)
    rep[u] = {"snippet": snippet, "inline": inline, "js": js, "jsctx": jsctx}
    time.sleep(2)
(out / "p10.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
