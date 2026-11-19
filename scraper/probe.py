"""一回きり：各場の公式サイトを詳しく下見（boatrace.jp には一切アクセスしない）。
1) サイトポリシー・利用規約に自動取得の禁止がないか
2) 直前情報（展示タイム・進入・展示ST・チルト・風）と結果（着順・決まり手・ST）がどのページにあるか"""
import json, re, sys, time, html as H_
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
out = Path(sys.argv[1]); (out / "p3").mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
V = json.loads((out / "venues.json").read_text(encoding="utf-8"))
BAD = re.compile(r"boatrace\.jp|\.pdf|\.jpg|\.png|access|news|event|beginner|gourmet|facility|bts_|camp|mailto|javascript|twitter|instagram|line\.me|youtube", re.I)
POL = re.compile(r"policy|kiyaku|rule|terms|privacy|sitemap|about|ポリシー|規約|免責|著作|このサイト|サイトについて|ご利用", re.I)
DATA = re.compile(r"直前|展示|スタート|結果|kekka|chokuzen|tenji|before|start|race|yosou|R\b|[0-9]{1,2}R|rno|raceno|jyo=|hd=|yd=", re.I)
def text(t):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S | re.I)
    return re.sub(r"\s+", " ", H_.unescape(re.sub(r"<[^>]+>", " ", t)))
def get(u):
    r = requests.get(u, headers=H, timeout=20); r.encoding = r.apparent_encoding; return r
rep = {}
for j, x in V.items():
    top = x["top_final"]; host = urlparse(top).netloc
    try:
        t0 = get(top).text
    except Exception as e:
        rep[j] = {"err": str(e)}; continue
    links = [(urljoin(top, m.group(1)), text(m.group(2))[:30]) for m in re.finditer(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', t0, re.S | re.I)]
    # 1) ポリシー
    pol = []
    for u, tt in links:
        if urlparse(u).netloc == host and POL.search(u + tt) and u not in [p["url"] for p in pol] and len(pol) < 3:
            try:
                tx = text(get(u).text)
                hits = sorted({m.group(0) for m in re.finditer(r".{0,60}(自動|プログラム|クロール|クローラ|スクレイピング|機械的|大量|負荷|ロボット).{0,60}", tx)})[:6]
                pol.append({"url": u, "title": tt, "hits": hits})
            except Exception as e:
                pol.append({"url": u, "err": str(e)[:80]})
            time.sleep(1.5)
    # 2) データページ（2段まで、30ページまで）
    seen, pages = set(), []
    q = [(u, tt, 1) for u, tt in links if urlparse(u).netloc == host and DATA.search(u + tt) and not BAD.search(u)]
    while q and len(pages) < 30:
        u, tt, d = q.pop(0)
        if u in seen: continue
        seen.add(u)
        try:
            r = get(u)
        except Exception as e:
            continue
        tx = text(r.text)
        c = {k: tx.count(k) for k in ["展示タイム", "展示", "チルト", "進入", "スタート展示", "決まり手", "風速", "波高", "着順", "ST"]}
        js = re.findall(r'(?:url|src|fetch|load|get|ajax)\s*[:(=]\s*["\']([^"\']+\.(?:php|json|htm|html)[^"\']*)["\']', r.text, re.I)[:6]
        fn = f"{int(j):02d}_{len(pages)+1:02d}.txt"; (out / "p3" / fn).write_text(tx[:60000], encoding="utf-8")
        anchors = [(urljoin(r.url, m.group(1)), text(m.group(2))[:24]) for m in re.finditer(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', r.text, re.S | re.I)]
        anchors = [(h, t3) for h, t3 in anchors if re.search(r"直前|展示|スタート|結果|オッズ|出走", t3)][:40]
        pages.append({"url": u, "title": tt, "status": r.status_code, "file": fn, "cnt": c, "js": js,
                      "anchors": anchors, "iframe": [s for s in re.findall(r'<iframe[^>]+src="([^"]+)"', r.text, re.I) if "googletag" not in s][:3]})
        if d < 3:
            for m in re.finditer(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', r.text, re.S | re.I):
                h = urljoin(r.url, m.group(1)); t2 = text(m.group(2))[:20]
                if urlparse(h).netloc == host and not BAD.search(h) and re.search(r"直前|展示|スタート|結果|kekka|chokuzen|tenji|before|start|[0-9]{1,2}R|rno|race_?no", h + t2, re.I) and h not in seen:
                    q.append((h, t2, d + 1))
        time.sleep(1.5)
    best = lambda k: max([p["cnt"][k] for p in pages] or [0])
    rep[j] = {"host": host, "policy": pol, "pages": pages}
    print(j, host, "ポリシー", [(p.get("title"), len(p.get("hits", []))) for p in pol], "展示T", best("展示タイム"), "チルト", best("チルト"), "S展示", best("スタート展示"), "決まり手", best("決まり手"), "風速", best("風速"), flush=True)
(out / "p3.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
