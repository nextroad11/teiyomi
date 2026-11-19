"""一回きり：各ボートレース場の公式サイトを下見する（boatrace.jp には一切アクセスしない）。
トップページと robots.txt を1回ずつ読み、レース情報（出走表・直前情報・結果）へのリンクを書き出す。"""
import json, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
V = {1:"https://www.kiryu-kyotei.com/",2:"https://www.boatrace-toda.jp/",3:"https://www.boatrace-edogawa.com/",4:"https://www.heiwajima.gr.jp/",
5:"https://www.boatrace-tamagawa.com/",6:"https://www.boatrace-hamanako.jp/",7:"https://www.gamagori-kyotei.com/",8:"https://www.boatrace-tokoname.jp/",
9:"https://www.boatrace-tsu.com/",10:"https://www.boatrace-mikuni.jp/",11:"https://www.boatrace-biwako.jp/",12:"https://www.boatrace-suminoe.jp/",
13:"https://www.boatrace-amagasaki.jp/",14:"https://www.n14.jp/",15:"https://www.marugameboat.jp/",16:"https://www.kojimaboat.jp/",
17:"https://www.boatrace-miyajima.com/",18:"https://www.boatrace-tokuyama.jp/",19:"https://www.boatrace-shimonoseki.jp/",20:"https://www.wmb.jp/",
21:"https://www.boatrace-ashiya.com/",22:"https://www.boatrace-fukuoka.com/",23:"https://www.boatrace-karatsu.jp/",24:"https://www.omurakyotei.jp/"}
KW = re.compile(r"直前|展示|結果|出走|番組|race|before|result|syusso|tenji|chokuzen|kekka|odds|オッズ", re.I)
rep = {}
for j, u in V.items():
    x = {"url": u}
    for kind, url in (("robots", urljoin(u, "/robots.txt")), ("top", u)):
        try:
            r = requests.get(url, headers=H, timeout=20)
            r.encoding = r.apparent_encoding
            x[kind + "_status"] = r.status_code; x[kind + "_final"] = r.url
            if kind == "robots": x["robots"] = r.text[:1500] if r.ok else ""
            else:
                (out / f"{j:02d}_top.html").write_text(r.text, encoding="utf-8")
                links = set()
                for m in re.finditer(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', r.text, re.S | re.I):
                    href = urljoin(r.url, m.group(1)); txt = re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()[:30]
                    if KW.search(href) or KW.search(txt): links.add((href, txt))
                x["links"] = sorted(links)[:80]
        except Exception as e:
            x[kind + "_err"] = str(e)[:200]
        time.sleep(2)
    rep[j] = x
    print(j, x.get("top_status"), x.get("robots_status"), len(x.get("links", [])), flush=True)
(out / "venues.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
