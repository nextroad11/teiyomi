"""一回きり：大村の直前・スタート展示ページと、平和島などの競技情報ページ（/asp/kyogi/場番号/）の中身を確認（boatrace.jp には一切アクセスしない）。"""
import json, re, sys, time, html as H_
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
out = Path(sys.argv[1]); (out / "p6").mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
U = ["https://www.omurakyotei.jp/yosou/chokuzen.php?day=20261119&race=01",
     "https://www.omurakyotei.jp/yosou/start.php?day=20261119&race=01",
     "https://www.omurakyotei.jp/yosou/kekka.php?day=20261119&race=01",
     "https://www.heiwajima.gr.jp/asp/heiwajima/kyogi/kyogihtml/index.htm?racenum=1",
     "https://www.heiwajima.gr.jp/asp/kyogi/04/pc/syusso0801.htm",
     "https://www.heiwajima.gr.jp/asp/kyogi/04/pc/yoso0201.htm",
     "https://www.marugameboat.jp/asp/kyogi/15/pc/syusso0101.htm",
     "https://www.gamagori-kyotei.com/asp/gamagori/kyogi/kyogihtml/index.htm"]
def text(t):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S | re.I)
    return re.sub(r"\s+", " ", H_.unescape(re.sub(r"<[^>]+>", " ", t)))
rep = []
for i, u in enumerate(U):
    try:
        r = requests.get(u, headers=H, timeout=20); r.encoding = r.apparent_encoding
    except Exception as e:
        rep.append({"url": u, "err": str(e)[:100]}); continue
    t = r.text
    hrefs = sorted({m.group(1)[:140] for m in re.finditer(r'(?:href|src|data-[a-z]+)\s*=\s*["\']([^"\'#]+)["\']', t) if not re.search(r"\.(png|jpg|gif|css|svg)", m.group(1))})
    strs = sorted({m.group(1)[:140] for m in re.finditer(r'["\']([^"\'\s]*?/asp/kyogi/[^"\'\s]*|[^"\'\s]*\.htm[^"\'\s]*)["\']', t)})
    (out / "p6" / f"{i:02d}.txt").write_text(text(t)[:80000], encoding="utf-8")
    rep.append({"url": u, "status": r.status_code, "len": len(t), "hrefs": hrefs[:120], "strs": strs[:80]})
    print(i, r.status_code, len(t), u, flush=True)
    time.sleep(2)
(out / "p6.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
