"""一回きり：BOATCASTで締切時刻・配当・開催場の一覧がどこにあるかを探す（boatrace.jp・mbrace には一切アクセスしない）。"""
import sys, time, json, re, requests
from pathlib import Path
from urllib.parse import urljoin
out = Path(sys.argv[1]); (out / "bc").mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
B = "https://race.boatcast.jp"
d, j, r = "20261119", "04", "05"
rep = {}
def get(p):
    x = requests.get(urljoin(B, p), headers=H, timeout=20); x.encoding = "utf-8"; time.sleep(1.5); return x
# 1) トップとJS一式を読み、データの置き場所を全部書き出す
top = get("/")
rep["top"] = {"status": top.status_code, "head": top.text[:3000]}
js = re.findall(r'(?:src|href)="([^"]+\.js)"', top.text)
paths = set(); ctx = []
seen = set()
queue = list(js)
while queue and len(seen) < 40:
    s = queue.pop(0)
    if s in seen: continue
    seen.add(s)
    try: b = get(s).text
    except Exception: continue
    for m in re.finditer(r'(?:import\(|from\s*)"(\./[^"]+\.js)"', b):
        queue.append(urljoin(urljoin(B, s), m.group(1)))
    for m in re.finditer(r'["`](/(?:hp_txt|m_txt|txt|api|json)[^"`]{0,160})["`]|"(/(?:hp_txt|m_txt|txt)/"\+[^;]{0,160})', b):
        paths.add((m.group(1) or m.group(2))[:200])
    for m in re.finditer(r'.{0,120}(締切|shime|deadline|haraimodo|払戻|harai|kaisai|today|jyo_list|jlist).{0,120}', b):
        ctx.append(m.group(0)[:260])
rep["js"] = sorted(seen); rep["paths"] = sorted(paths); rep["ctx"] = ctx[:60]
# 2) 候補を直接読む
C = {f"rs1_{k}": f"/m_txt/{j}/bc_rs1_{k}_{d}_{j}_{r}.txt" for k in (1, 3, 4, 5)}
C.update({"rs2": f"/m_txt/{j}/bc_rs2_{d}_{j}_{r}.txt", "mdc": f"/hp_txt/{j}/bc_mdc_{d}_{j}.txt", "mst": f"/hp_txt/{j}/bc_mst_{j}.txt",
          "mon2": f"/hp_txt/{j}/bc_mon_2_{d[:6]}_{j}.txt", "str3_hdr": f"/hp_txt/{j}/bc_j_str3_{d}_{j}_{r}.txt"})
for k, p in C.items():
    try:
        x = get(p); rep[k] = {"url": p, "status": x.status_code, "head": x.text[:800]}; print(k, x.status_code, len(x.content), flush=True)
    except Exception as e: rep[k] = {"err": str(e)}
(out / "bc" / "find.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
print("paths", len(paths), "js", len(seen))
