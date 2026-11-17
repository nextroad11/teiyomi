"""公式ページの風向き・場の向きの画像（is-wind・is-direction）が何を表すかを確かめる一回きりの下見。"""
import re, sys, time
from pathlib import Path
from urllib.parse import urljoin
import requests
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
base = "https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=4&jcd=16&hd=20261114"
h = requests.get(base, headers=H, timeout=20).text
(out / "beforeinfo_16_4.html").write_text(h, encoding="utf-8")
css_urls = [urljoin(base, u) for u in re.findall(r'href="([^"]+\.css[^"]*)"', h)]
print(css_urls)
for i, u in enumerate(css_urls):
    try:
        c = requests.get(u, headers=H, timeout=20).text
    except Exception as e:
        print("css fail", u, e); continue
    hits = [m for m in re.findall(r'[^{}]*weather1_bodyUnitImage[^{}]*\{[^}]*\}', c)]
    if hits:
        (out / f"weather_css_{i}.txt").write_text(u + "\n\n" + "\n".join(hits), encoding="utf-8")
        imgs = set(re.findall(r'url\(["\']?([^"\')]+)["\']?\)', "\n".join(hits)))
        for im in sorted(imgs)[:80]:
            iu = urljoin(u, im)
            try:
                b = requests.get(iu, headers=H, timeout=20).content
                (out / ("img_" + re.sub(r"[^A-Za-z0-9_.-]", "_", im.split("/")[-1]))).write_bytes(b)
            except Exception as e:
                print("img fail", iu, e)
            time.sleep(0.3)
        print("weather css", u, len(hits), "images", len(imgs))
    time.sleep(0.5)
