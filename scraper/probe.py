"""一回きり：共通の競技情報ページ（/asp/kyogi/場番号/pc/）が各場にあるかと、直前情報のページ名を確認（boatrace.jp には一切アクセスしない）。"""
import json, re, sys, time, html as H_
from pathlib import Path
from urllib.parse import urlparse
import requests
out = Path(sys.argv[1]); (out / "p7").mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
V = json.loads((out / "venues.json").read_text(encoding="utf-8"))
def text(t):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S | re.I)
    return re.sub(r"\s+", " ", H_.unescape(re.sub(r"<[^>]+>", " ", t)))
def get(u):
    r = requests.get(u, headers=H, timeout=20); r.encoding = r.apparent_encoding; return r
rep = {"venues": {}, "guess": []}
# 1) 各場に共通ページがあるか（1場1回）
for j, x in V.items():
    base = "https://" + urlparse(x["top_final"]).netloc
    u = f"{base}/asp/kyogi/{int(j):02d}/pc/syusso0101.htm"
    try:
        r = get(u); tx = text(r.text)
        rep["venues"][j] = {"url": u, "status": r.status_code, "len": len(r.text), "has": "枠番" in tx and "選手名" in tx}
    except Exception as e:
        rep["venues"][j] = {"url": u, "err": str(e)[:80]}
    print(j, rep["venues"][j], flush=True); time.sleep(1.5)
# 2) 平和島で直前情報のページ名を探す（syusso の番号違い・名前違い）
B = "https://www.heiwajima.gr.jp/asp/kyogi/04/pc/"
names = [f"syusso{n:02d}01.htm" for n in (3, 4, 7, 9, 10, 11, 12)] + ["chokuzen0101.htm", "tenji0101.htm", "before0101.htm", "kekka0101.htm", "kekka0201.htm", "yoso0301.htm", "yoso0401.htm"]
for n in names:
    try:
        r = get(B + n); tx = text(r.text)
        c = {k: tx.count(k) for k in ["展示タイム", "展示", "チルト", "進入", "スタート展示", "決まり手", "風速", "波高", "部品"]}
        rep["guess"].append({"name": n, "status": r.status_code, "len": len(r.text), "cnt": c})
        if r.ok: (out / "p7" / (n + ".txt")).write_text(tx[:60000], encoding="utf-8")
        print(n, r.status_code, c, flush=True)
    except Exception as e:
        print(n, e)
    time.sleep(1.5)
(out / "p7.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
