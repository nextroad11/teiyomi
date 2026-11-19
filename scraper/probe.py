"""一回きり：各場の公式サイトのレース情報ページを下見（boatrace.jp には一切アクセスしない）。
トップから見つけた同じサイト内のレース情報らしいページを読み、展示タイム・進入・結果の有無と、
中身を別サイト（iframe など）から読んでいないかを調べる。"""
import json, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
V = json.loads((out / "venues.json").read_text(encoding="utf-8"))
KW = re.compile(r"raceinfo|yosou|kekka|result|Race/|chokuzen|tenji|before|syusso|shusso|race\.php|racelist|01race|02kekka|timedata|konsetsu|直前|展示|結果|出走", re.I)
BAD = re.compile(r"boatrace\.jp|\.pdf$|access|news|event|beginner|gourmet", re.I)
def fetch(u):
    r = requests.get(u, headers=H, timeout=20); r.encoding = r.apparent_encoding; return r
rep = {}
for j, x in V.items():
    host = urlparse(x["top_final"]).netloc
    cands = []
    for h, t in x.get("links", []):
        if urlparse(h).netloc == host and KW.search(h + t) and not BAD.search(h) and h not in cands: cands.append(h)
    res = []
    seen = set()
    queue = cands[:10]
    while queue and len(res) < 16:
        u = queue.pop(0)
        if u in seen: continue
        seen.add(u)
        try:
            r = fetch(u)
        except Exception as e:
            res.append({"url": u, "err": str(e)[:100]}); continue
        t = r.text
        txt = re.sub(r"<[^>]+>", " ", t)
        info = {"url": u, "status": r.status_code, "final": r.url, "len": len(t),
                "展示": txt.count("展示"), "展示タイム": txt.count("展示タイム"), "進入": txt.count("進入"), "チルト": txt.count("チルト"),
                "着順": txt.count("着順"), "決まり手": txt.count("決まり手"), "風速": txt.count("風速"), "部品": txt.count("部品"),
                "iframe": re.findall(r'<iframe[^>]+src="([^"]+)"', t, re.I)[:5],
                "ext_js": sorted({urlparse(s).netloc for s in re.findall(r'<script[^>]+src="(https?://[^"]+)"', t, re.I)})[:8],
                "ajax": sorted(set(re.findall(r'["\'](https?://[^"\']*(?:json|api|ajax)[^"\']*)["\']', t, re.I)))[:5]}
        res.append(info)
        fn = out / "pages" / f"{int(j):02d}_{len(res):02d}.html"; fn.parent.mkdir(exist_ok=True); fn.write_text(t, encoding="utf-8")
        info["file"] = fn.name
        # 1段だけ深く：同じサイト内で、展示・直前・結果・レース番号らしいリンク
        if r.ok and len(res) < 16:
            for m in re.finditer(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', t, re.S | re.I):
                h = urljoin(r.url, m.group(1)); tt = re.sub(r"<[^>]+>|\s+", "", m.group(2))[:20]
                if urlparse(h).netloc == host and not BAD.search(h) and re.search(r"直前|展示|結果|[0-9]+R|chokuzen|tenji|kekka|race_?no|rno=", h + tt, re.I) and h not in seen and h not in queue:
                    queue.append(h)
        time.sleep(2)
    rep[j] = res
    print(j, host, [(p.get("status"), p.get("展示タイム"), p.get("進入"), p.get("決まり手")) for p in res], flush=True)
(out / "pages.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
