"""一回きり：BOATCAST で取れるデータの種類を1レース分ずつ確認（boatrace.jp・mbrace には一切アクセスしない）。"""
import sys, time, json, requests
from pathlib import Path
out = Path(sys.argv[1]); (out / "bc").mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"}
B = "https://race.boatcast.jp"
d, j, r = "20261119", "04", "05"
d2 = "20261120"
U = {
 "出走表": f"/hp_txt/{j}/bc_j_str3_{d}_{j}_{r}.txt",
 "出走表_明日": f"/hp_txt/{j}/bc_j_str3_{d2}_{j}_{r}.txt",
 "直前": f"/hp_txt/{j}/bc_j_tkz_{d}_{j}_{r}.txt",
 "スタート展示": f"/hp_txt/{j}/bc_j_stt_{d}_{j}_{r}.txt",
 "結果": f"/m_txt/{j}/bc_rs1_2_{d}_{j}_{r}.txt",
 "水面": f"/m_txt/{j}/bc_sui_{d}_{j}.txt",
 "水面R": f"/m_txt/{j}/bc_sui_{d}_{j}_{r}.txt",
 "オリ展": f"/txt/{j}/bc_oriten_{d}_{j}_{r}.txt",
 "枠別10走": f"/hp_txt/{j}/bc_j_waku10_{d}_{j}_{r}.txt",
 "前走": f"/hp_txt/{j}/bc_zensou_{d}_{j}.txt",
 "モーター": f"/hp_txt/{j}/bc_mst_{j}.txt",
}
rep = {}
for k, p in U.items():
    try:
        x = requests.get(B + p, headers=H, timeout=20); x.encoding = "utf-8"
        rep[k] = {"url": p, "status": x.status_code, "len": len(x.content), "head": x.text[:1500]}
        print(k, x.status_code, len(x.content), flush=True)
    except Exception as e:
        rep[k] = {"url": p, "err": str(e)}
    time.sleep(2)
(out / "bc" / "kinds.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
