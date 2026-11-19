"""一回きり：有望な各場ページ（予想サイト・競技情報）の中身を確認（boatrace.jp には一切アクセスしない）。"""
import json, re, sys, time, html as H_
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
out = Path(sys.argv[1]); (out / "p5").mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
U = [
 "https://www.kiryu-kyotei.com/modules/yosou/?mode=cyokuzen",
 "https://www.kiryu-kyotei.com/modules/yosou/",
 "https://www.boatrace-tsu.com/modules/yosou/",
 "https://www.boatrace-fukuoka.com/modules/yosou/simple_syussouhyo.php",
 "https://www.boatrace-tokuyama.jp/modules/yosou/",
 "https://www.gamagori-kyotei.com/asp/gamagori/kyogi/kyogihtml/index.htm?page=start&racenum=1",
 "https://www.heiwajima.gr.jp/asp/heiwajima/kyogi/kyogihtml/index.htm?racenum=1",
 "https://www.marugameboat.jp/asp/marugame/02kekka/kekka_list.php",
 "https://www.marugameboat.jp/asp/kyogi/15/pc/syusso0101.htm",
 "https://www.omurakyotei.jp/yosou/chokuzen.php",
 "https://www.omurakyotei.jp/yosou/start.php",
]
def text(t):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S | re.I)
    return re.sub(r"\s+", " ", H_.unescape(re.sub(r"<[^>]+>", " ", t)))
rep = []
for i, u in enumerate(U):
    try:
        r = requests.get(u, headers=H, timeout=20); r.encoding = r.apparent_encoding
    except Exception as e:
        rep.append({"url": u, "err": str(e)[:100]}); continue
    t = r.text; host = urlparse(r.url).netloc
    urls = sorted({m.group(1)[:160] for m in re.finditer(r'["\']((?:https?:)?/?[A-Za-z0-9_./-]*\.(?:php|json|htm|html)(?:\?[^"\'\s]*)?)["\']', t)
                   if re.search(r"yosou|kyogi|cyokuzen|chokuzen|tenji|start|kekka|race|ajax|json", m.group(1), re.I)})[:60]
    js = [urljoin(r.url, s) for s in re.findall(r'<script[^>]+src="([^"]+)"', t, re.I) if "jquery" not in s.lower()][:8]
    jsurls = []
    for s in js:
        if urlparse(s).netloc != host: continue
        try:
            b = requests.get(s, headers=H, timeout=20).text
            jsurls += [m.group(1)[:160] for m in re.finditer(r'["\']([^"\'\s]*\.(?:php|json|htm)(?:\?[^"\'\s]*)?)["\']', b) if re.search(r"yosou|kyogi|cyokuzen|chokuzen|tenji|start|kekka|race|ajax|json", m.group(1), re.I)]
        except Exception: pass
        time.sleep(1.5)
    tx = text(t)
    (out / "p5" / f"{i:02d}.txt").write_text(tx[:80000], encoding="utf-8")
    rep.append({"url": u, "status": r.status_code, "final": r.url, "len": len(t), "urls": urls, "jsurls": sorted(set(jsurls))[:40],
                "cnt": {k: tx.count(k) for k in ["展示タイム", "展示", "チルト", "進入", "スタート展示", "決まり手", "風速", "部品", "周回", "まわり足"]}})
    print(i, r.status_code, u, rep[-1]["cnt"], flush=True)
    time.sleep(2)
(out / "p5.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
