"""公式の配布ファイル（mbrace の番組表Bと競走成績K）から、アプリ用の日別ファイル（data/YYYYMMDD.json）を作る・補う。
boatrace.jp には一切アクセスしない。

  python scraper/mbrace_day.py data 20261120          # 番組表（出走表）と、出ていれば結果
  python scraper/mbrace_day.py data 20261117 --fill   # 既存ファイルの欠けた結果・展示（展示タイム・進入）を補う

番組表Bに無い項目（F・L数、平均ST、3連率、節の日目・グレード）は空のまま。
結果Kから入れる展示（展示タイム・進入）は、レース後に分かったもの（before.fromK=True）。"""
import datetime as dt, json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import history as h

VENUES = {1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖", 7: "蒲郡", 8: "常滑",
          9: "津", 10: "三国", 11: "びわこ", 12: "住之江", 13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島",
          17: "宮島", 18: "徳山", 19: "下関", 20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村"}
JST = dt.timezone(dt.timedelta(hours=9))


def headers_b(text):
    """場ごとの節の名前と日目（番組表の見出しから。取れなければ空）"""
    out, jcd, lines = {}, None, []
    for raw in text.splitlines():
        m = re.match(r"^(\d{2})BBGN", raw)
        if m:
            jcd, lines = int(m.group(1)), []
            continue
        if jcd is None or jcd in out:
            continue
        line = h.nfkc(raw).strip()
        if re.match(r"^\d{1,2}R\s", line):
            title = next((l for l in lines if l and not re.search(r"ボートレース|番組表|月\s*\d+\s*日|第\s*\d+\s*日|^-+$|^\*+$", l)), "")
            day = next((re.search(r"第\s*(\d+)\s*日", l).group(1) for l in lines if re.search(r"第\s*(\d+)\s*日", l)), None)
            out[jcd] = {"title": re.sub(r"\s+", " ", title)[:60], "day": (f"{day}日目" if day else None), "head": lines[:8]}
            continue
        if line:
            lines.append(line)
    return out


def main():
    root, D = Path(sys.argv[1]), sys.argv[2]
    h.LOCAL = str(root / "mbrace")
    day = dt.date(int(D[:4]), int(D[4:6]), int(D[6:]))
    path = root / f"{D}.json"
    cur = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"date": D, "races": []}
    R = {(r["jcd"], r["rno"]): r for r in cur["races"]}
    btxt = h.download_text("B", day); time.sleep(1)
    ktxt = h.download_text("K", day)
    added = filled = res_n = 0
    if btxt:
        b, hd = h.parse_b(btxt), headers_b(btxt)
        for (jcd, rno), x in sorted(b.items()):
            if (jcd, rno) in R or len(x["boats"]) != 6:
                continue
            H = hd.get(jcd, {})
            R[(jcd, rno)] = {
                "id": f"{D}-{jcd:02d}-{rno:02d}", "date": D, "jcd": jcd, "venue": VENUES[jcd], "rno": rno,
                "title": H.get("title") or "", "grade": "ippan", "day": H.get("day"), "name": x["name"],
                "distance": x["distance"], "deadline": x["deadline"], "src": "mbrace",
                "boats": [{"waku": w, **x["boats"][w], "weight": float(x["boats"][w]["weight"]), "f": None, "l": None, "st": None}
                          for w in range(1, 7)]}
            added += 1
        cur["mbraceHead"] = {str(j): v["head"] for j, v in hd.items()}
    if ktxt:
        k = h.parse_k(ktxt)
        for key, x in k.items():
            r = R.get(key)
            if not r:
                continue
            res = r.get("result") or {}
            if x.get("tri") and not (res.get("order") and res.get("km") and res.get("st")):
                bs = x["boats"]
                st = [[w, ("F" if q["flying"] else "") + (f".{round(q['st'] * 100):02d}" if q["st"] is not None else "")]
                      for w, q in sorted(bs.items(), key=lambda t: t[1]["course"] or 9)]
                r["result"] = {**res, "order": x["tri"]["order"], "payout": x["tri"]["payout"], "pop": x["tri"]["pop"],
                               "km": x.get("kimarite"), "st": st, "src": "mbrace"}
                res_n += 1
            bf = r.get("before") or {}
            if not bf.get("complete"):
                boats = bf.get("boats") or {}
                for w, q in x["boats"].items():
                    e = boats.setdefault(str(w), {})
                    if e.get("exTime") is None and q["exTime"] is not None: e["exTime"] = q["exTime"]
                    if e.get("course") is None and q["course"] is not None: e["course"] = q["course"]
                if all(boats.get(str(w), {}).get("exTime") is not None and boats.get(str(w), {}).get("course") for w in range(1, 7)):
                    bf.update({"boats": boats, "complete": True, "fromK": True, "weather": bf.get("weather") or x["weather"],
                               "windSpeed": bf.get("windSpeed", x["windSpeed"]), "wave": bf.get("wave", x["wave"])})
                    r["before"] = bf
                    filled += 1
    cur["races"] = [R[k] for k in sorted(R, key=lambda k: (R[k].get("deadline") or "", k[0]))]
    cur["mbraceAt"] = dt.datetime.now(JST).isoformat(timespec="seconds")
    cur.setdefault("updated", cur["mbraceAt"])
    path.write_text(json.dumps(cur, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    idx_p = root / "index.json"
    idx = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.exists() else {"dates": []}
    idx["dates"] = sorted(set(idx.get("dates", [])) | {D}, reverse=True)
    idx_p.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    print(f"{D}: 番組表{'あり' if btxt else 'なし'} 結果{'あり' if ktxt else 'なし'} / 追加{added}R 結果{res_n}R 展示補完{filled}R / 計{len(cur['races'])}R")


if __name__ == "__main__":
    main()
