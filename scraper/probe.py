"""一回きり：BOATCASTのページとスクリプトから、オッズのファイル名を探す（名乗りは変えない。断られたら止める）。
保存するのはファイル名の候補だけ（ページそのものは保存しない）。"""
import re, sys, pathlib, requests
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
B = "https://race.boatcast.jp"
lines = []
def get(u):
    r = requests.get(u, headers=H, timeout=20); r.encoding = "utf-8"; lines.append(f"{r.status_code} {u} {len(r.text)}"); return r
top = get(B + "/")
if top.status_code != 200: (out / "odds_probe.txt").write_text("\n".join(lines)); sys.exit()
srcs = sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', top.text)))
lines.append("scripts: " + " ".join(srcs))
found = set()
for s in srcs[:15]:
    u = s if s.startswith("http") else B + ("" if s.startswith("/") else "/") + s
    if "boatcast" not in u: continue
    t = get(u).text
    for m in re.findall(r'["\'`]([^"\'`]*(?:odds|Odds|ODDS|oz|_o3|3t|bc_[a-z0-9_]+)[^"\'`]{0,60})["\'`]', t):
        if len(m) < 120: found.add(m)
lines.append("候補:"); lines += sorted(found)[:400]
(out / "odds_probe.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines[:60]))
