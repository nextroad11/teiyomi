"""BOATCAST（race.boatcast.jp）だけからレースデータを取る（boatrace.jp・mbrace には一切アクセスしない）。

  python scraper/bcast.py --data data              # 1回分（スクレイプのループから1分ごとに呼ばれる）
  python scraper/bcast.py --data data --date YYYYMMDD   # その日の出走表を作る・補う（＋あれば直前・結果）
  python scraper/bcast.py --data data --fill-ori YYYYMMDD ...  # 欠けているオリジナル展示を取り込む

取るもの：出走表（bc_j_str3）・開催一覧と締切（getHoldingList2、当日だけ）・開催日程（bc_mon_2）・
直前（bc_j_tkz：展示タイム・体重・チルト・部品）・スタート展示（bc_j_stt：進入・展示ST）・
オリジナル展示（bc_oriten）・水面（bc_sui）・結果（bc_rs1_2：着順・決まり手・ST、bc_rs2：配当）。オッズは取らない。
負担を減らすため、1回の取得の間は1秒以上あけ、同じレースの読み直しは3分以上あける。
BOATCAST に断られた（時刻APIまで403）ときは、その日の取得をやめる（data/bcast_blocked.json）。"""
import argparse, datetime as dt, json, re, sys, time, unicodedata
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from teiyomi_scraper import (VENUES, JST, parse_oriten, ori_incomplete, ori_filled, read_json, write_json,
                             deadline_dt, now_jst, fnum)

B = "https://race.boatcast.jp"
S = requests.Session()
S.headers.update({"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)", "Referer": "https://race.boatcast.jp/"})
SLEEP, _last, NREQ = 1.0, 0.0, 0
GRADE = {"SG": "SG", "G1": "G1b", "G2": "G2b", "G3": "G3b", "IP": "ippan"}
WEATHER = {"1": "晴", "2": "曇り", "3": "雨", "4": "雪", "5": "霧", "6": "台風"}
DIRS = ['北', '北北東', '北東', '東北東', '東', '東南東', '南東', '南南東', '南', '南南西', '南西', '西南西', '西', '西北西', '北西', '北北西']
# 方角 → 水面図の矢印番号（アプリの windDir、1=上・時計回り、5=右=1マーク向き）。過去1年の向かい風・追い風で場ごとに確認済み
OFF = {1: 5, 2: 7, 3: 11, 4: 12, 5: 0, 6: 4, 7: 2, 8: 0, 9: 15, 10: 5, 11: 4, 12: 4, 13: 1, 14: 6, 15: 14, 16: 4, 17: 2, 18: 14, 19: 2, 20: 1, 21: 8, 22: 9, 23: 3, 24: 10}
RECHECK = 180  # 同じレースの読み直し間隔（秒）


def log(*a):
    print(*a, flush=True)


class Blocked(Exception):
    pass


def get(path: str) -> str | None:
    """取れなければ None（BOATCAST は無いファイルにも 403 の HTML を返す）"""
    global _last, NREQ
    w = SLEEP - (time.time() - _last)
    if w > 0:
        time.sleep(w)
    for i in range(2):
        try:
            r = S.get(B + path, timeout=20)
            _last = time.time(); NREQ += 1
            if r.status_code == 200 and not r.text.lstrip().startswith("<"):
                r.encoding = "utf-8"
                return r.text
            return None
        except requests.RequestException as e:
            log(f"  error ({i + 1}): {path} {e}")
            time.sleep(3)
    return None


def check_alive():
    t = get("/api/getServerDateTime.php")
    if not t:
        raise Blocked("BOATCAST の時刻APIが取れない")
    return json.loads(t)


def z(s):  # 全角→半角・空白除去
    return re.sub(r"[\s　]", "", unicodedata.normalize("NFKC", s or ""))


def lines_of(txt):
    return [l.rstrip("\r") for l in txt.split("\n") if l.strip() and not l.startswith("data=")]


# ---------------------------------------------------------------- 開催・出走表
def mon_venues(D: str, root: Path) -> dict:
    """その日に開催している場 {jcd: {title, grade}}（bc_mon_2 は月ごと。1日1回だけ読む）"""
    cache = root / "bcast" / f"mon_{D}.json"
    c = read_json(cache, None)
    if c is not None:
        return {int(k): v for k, v in c.items()}
    out = {}
    for j in range(1, 25):
        t = get(f"/hp_txt/{j:02d}/bc_mon_2_{D[:6]}_{j:02d}.txt")
        for l in lines_of(t or "")[1:]:
            c2 = l.split("\t")
            if len(c2) >= 4 and c2[0].isdigit() and c2[0] <= D <= c2[1]:
                out[j] = {"title": z(c2[3]) and c2[3].replace("　", " ").strip(), "grade": GRADE.get(c2[2].strip(), "ippan"),
                          "start": c2[0], "end": c2[1]}
    cache.parent.mkdir(exist_ok=True)
    write_json(cache, {str(k): v for k, v in out.items()})
    return out


def parse_str3(txt: str) -> list | None:
    rows = [l.split("\t") for l in lines_of(txt)]
    boats = []
    for c in rows:
        if len(c) < 24 or not c[0].strip().isdigit() or len(c[0].strip()) != 4:
            continue
        flag = z("".join(c[6:9]))
        f = re.search(r"F(\d)", flag); l = re.search(r"L(\d)", flag)
        kon = []
        for x in c[25:37]:
            p = x.split(",")
            if len(p) == 5 and p[0] not in ("-", ""):
                kon.append({"rno": int(p[0]) if p[0].isdigit() else None, "waku": p[1], "course": p[2], "st": p[3], "fin": z(p[4])})
        boats.append({"waku": len(boats) + 1, "toban": int(c[0]), "name": z(c[1]), "branch": z(c[3].split(":")[0]),
                      "age": int(c[4]) if c[4].strip().isdigit() else None, "cls": z(c[5]),
                      "f": int(f.group(1)) if f else 0, "l": int(l.group(1)) if l else 0, "st": fnum(c[9]),
                      "natWin": fnum(c[10]), "nat2": fnum(c[11]), "nat3": fnum(c[12]),
                      "locWin": fnum(c[13]), "loc2": fnum(c[14]), "loc3": fnum(c[15]),
                      "motor": int(c[17]) if c[17].strip().isdigit() else None, "motor2": fnum(c[18]), "motor3": fnum(c[19]),
                      "boat": int(c[21]) if c[21].strip().isdigit() else None, "boat2": fnum(c[22]), "boat3": fnum(c[23]),
                      "kon": kon})
    return boats if len(boats) == 6 else None


def holding(D: str) -> dict:
    """当日の開催一覧（締切時刻・節の名前・日目・レース名）。当日しか出ない"""
    t = get(f"/api_txt/getHoldingList2_{D}.json")
    if not t:
        return {}
    out = {}
    for h in json.loads(t).get("return_info", []):
        try:
            j = int(h["RaceStudiumNo"])
        except (KeyError, ValueError):
            continue
        out[j] = {"title": (h.get("HoldingTitle") or "").replace("　", " ").strip(), "day": z(h.get("DailyTitle")) or None,
                  "grade": GRADE.get(h.get("RaceGrade"), "ippan"), "deadlines": h.get("DeadlineTimeAll") or [],
                  "names": [z(x) for x in (h.get("RaceTitleAll") or [])], "cancel": h.get("CancelStatusAll") or []}
    return out


def build_card(D: str, day: dict, root: Path, full: bool = False) -> int:
    """出走表を作る・補う。既にある（配布ファイル由来など）レースは、選手の数字だけ BOATCAST のものに入れ替える"""
    R = {(r["jcd"], r["rno"]): r for r in day["races"]}
    mv = mon_venues(D, root)
    jcds = sorted(set(mv) | {k[0] for k in R})
    n = 0
    for j in jcds:
        for rno in range(1, 13):
            r = R.get((j, rno))
            if r and r.get("bcCard") and not full:
                continue
            t = get(f"/hp_txt/{j:02d}/bc_j_str3_{D}_{j:02d}_{rno:02d}.txt")
            boats = parse_str3(t) if t else None
            if not boats:
                if rno == 1 and not r:
                    break  # この場はこの日に出走表がない
                continue
            if not r:
                m = mv.get(j, {})
                r = {"id": f"{D}-{j:02d}-{rno:02d}", "date": D, "jcd": j, "venue": VENUES[j], "rno": rno,
                     "title": m.get("title") or "", "grade": m.get("grade") or "ippan", "day": None, "name": "",
                     "distance": 1800, "deadline": ""}
                R[(j, rno)] = r
            old = {b["waku"]: b for b in r.get("boats") or []}
            for b in boats:
                o = old.get(b["waku"], {})
                if o.get("weight") is not None and b.get("weight") is None:
                    b["weight"] = o["weight"]
            r["boats"] = boats
            r["bcCard"] = True
            n += 1
    day["races"] = [R[k] for k in sorted(R, key=lambda k: (R[k].get("deadline") or "99", k[0], k[1]))]
    return n


def apply_holding(D: str, day: dict) -> int:
    hl = holding(D)
    n = 0
    for r in day["races"]:
        h = hl.get(r["jcd"])
        if not h:
            continue
        i = r["rno"] - 1
        dl = h["deadlines"][i] if i < len(h["deadlines"]) else ""
        if re.match(r"^\d{1,2}:\d{2}$", dl or "") and r.get("deadline") != dl:
            r["deadline"] = dl; n += 1
        if h["title"]: r["title"] = h["title"]
        if h["day"]: r["day"] = h["day"]
        r["grade"] = h["grade"] or r.get("grade")
        if i < len(h["names"]) and h["names"][i]: r["name"] = h["names"][i]
        if i < len(h["cancel"]) and h["cancel"][i]: r["cancel"] = h["cancel"][i]
    day["holdingAt"] = now_jst().isoformat(timespec="seconds")
    day["races"].sort(key=lambda r: (r.get("deadline") or "99", r["jcd"], r["rno"]))
    return n


# ---------------------------------------------------------------- 直前・スタート展示・水面
def parse_tkz(txt: str) -> dict:
    out = {}
    rows = [l.split("\t") for l in lines_of(txt)]
    w = 0
    for c in rows:
        if len(c) >= 7 and not c[0].strip().isdigit() and z(c[0]):
            w += 1
            if w > 6:
                break
            ex = fnum(c[1]); wt = fnum(c[4]); tilt = fnum(z(c[6]))
            out[str(w)] = {"exTime": ex if ex and ex > 5 else None, "weight": wt, "parts": z(c[3]).strip("0") and z(c[3]) or "",
                           "tilt": tilt}
    return out


def parse_stt(txt: str) -> dict:
    out = {}
    for c in (l.split("\t") for l in lines_of(txt)):
        # [進入コース, 枠, 名前, (今節平均ST?), 展示ST, F, ...]。展示STは5列目、Fは6列目（11/20 芦屋・鳴門で確認）
        if len(c) >= 6 and c[0].strip().isdigit() and c[1].strip().isdigit():
            course, waku, s, fl = int(c[0]), c[1].strip(), z(c[4]), z(c[5])
            v = fnum(s)
            out[waku] = {"course": course, "exST": (-v if ("F" in fl or "F" in s) else v) if v is not None else None}
    return out


def parse_wx(line: list) -> dict:
    """[時刻, 天候, 風速, 風向(追い風など), 波高, 気温, 水温, ...]"""
    if len(line) < 5:
        return {}
    d = re.sub(r"[\s　（(].*$", "", line[3].strip())
    side = re.search(r"[（(](.+?)[)）]", line[3])
    o = {"weather": WEATHER.get(line[1].strip(), None), "windSpeed": int(line[2]) if line[2].strip().isdigit() else None,
         "wave": int(line[4]) if line[4].strip().isdigit() else None, "windText": z(side.group(1)) if side else None,
         "windCompass": d or None}
    return o


def wind_code(jcd: int, compass: str | None, speed) -> int | None:
    if speed == 0 or compass == "無風":
        return 17
    if compass in DIRS:
        return (DIRS.index(compass) + OFF[jcd]) % 16 + 1
    return None


def update_before(r: dict, D: str, now: dt.datetime, sui_cache: dict) -> bool:
    bf = r.get("before") or {}; r["before"] = bf
    j, rno = r["jcd"], r["rno"]
    tk = get(f"/hp_txt/{j:02d}/bc_j_tkz_{D}_{j:02d}_{rno:02d}.txt")
    st = get(f"/hp_txt/{j:02d}/bc_j_stt_{D}_{j:02d}_{rno:02d}.txt")
    boats = bf.get("boats") or {}; bf["boats"] = boats
    if tk:
        for w, v in parse_tkz(tk).items():
            e = boats.setdefault(w, {})
            for k2, x in v.items():
                if x is not None and x != "":
                    e[k2] = x
            if v.get("weight") is not None:
                for b in r.get("boats", []):
                    if str(b["waku"]) == w:
                        b["weight"] = v["weight"]
    if st:
        for w, v in parse_stt(st).items():
            e = boats.setdefault(w, {})
            for k2, x in v.items():
                if x is not None:
                    e[k2] = x
    if j not in sui_cache:
        t = get(f"/m_txt/{j:02d}/bc_sui_{D}_{j:02d}.txt")
        sui_cache[j] = parse_wx(t.split("\n")[0].split("\t")) if t else {}
    wx = sui_cache[j]
    if wx:
        if "wx0" not in bf and bf.get("windSpeed") is not None:
            bf["wx0"] = {k: bf.get(k) for k in ("windSpeed", "windDir", "wave", "weather")}
        bf.update({"weather": wx["weather"], "windSpeed": wx["windSpeed"], "wave": wx["wave"], "windText": wx["windText"],
                   "windCompass": wx["windCompass"], "windDir": wind_code(j, wx["windCompass"], wx["windSpeed"])})
    ok = all(boats.get(str(w), {}).get("exTime") is not None and boats.get(str(w), {}).get("course") for w in range(1, 7))
    bf["complete"] = ok
    bf["fetchedAt"] = now.isoformat(timespec="seconds")
    bf["src"] = "boatcast"; bf["stt2"] = True
    # オリジナル展示
    if ok and (not bf.get("ori") or ori_incomplete(bf["ori"])):
        t = get(f"/txt/{j:02d}/bc_oriten_{D}_{j:02d}_{rno:02d}.txt")
        o = parse_oriten(t) if t else None
        if o and (not bf.get("ori") or ori_filled(o) >= ori_filled(bf["ori"])):
            bf["ori"] = o; bf["oriAt"] = now.isoformat(timespec="seconds")
    return ok


# ---------------------------------------------------------------- 結果
FIN = {"１": 1, "２": 2, "３": 3, "４": 4, "５": 5, "６": 6}


def parse_result(t1: str, t2: str | None) -> dict | None:
    ls = [l.split("\t") for l in t1.replace("\r", "").split("\n") if l.strip()]
    if len(ls) < 7:
        return None
    head = ls[0]
    st = []
    for i in range(0, len(head) - 2, 3):
        w, fl, s = head[i].strip(), z(head[i + 1]), z(head[i + 2])
        if w.isdigit():
            st.append([int(w), (fl if fl in ("F", "L") else "") + s])
    order, km = [], None
    for c in ls[1:7]:
        if len(c) >= 2 and c[1].strip().isdigit():
            f = FIN.get(c[0].strip()) or (int(z(c[0])) if z(c[0]).isdigit() else None)
            if f and f <= 3:
                order.append((f, int(c[1])))
            if f == 1 and len(c) >= 5 and z(c[4]):
                km = z(c[4])
    order = [w for _, w in sorted(order)]
    if len(order) < 3:
        return None
    res = {"order": "-".join(map(str, order[:3])), "km": km, "st": st, "src": "boatcast"}
    wx = parse_wx(ls[-1]) if len(ls) >= 8 else {}
    if wx:
        res["wx"] = wx
    if t2:
        for l in t2.split("\n"):
            c = l.split("\t")
            if len(c) >= 6 and all(x.strip().isdigit() for x in c[:3]) and c[4].strip() == "円":
                res["payout"] = int(c[3].replace(",", ""))
                res["pop"] = int(c[5]) if c[5].strip().isdigit() else None
                break
    return res


def update_result(r: dict, D: str, now: dt.datetime) -> bool:
    j, rno = r["jcd"], r["rno"]
    t1 = get(f"/m_txt/{j:02d}/bc_rs1_2_{D}_{j:02d}_{rno:02d}.txt")
    if not t1:
        return False
    t2 = get(f"/m_txt/{j:02d}/bc_rs2_{D}_{j:02d}_{rno:02d}.txt")
    p = parse_result(t1, t2)
    if not p:
        return False
    old = r.get("result") or {}
    r["result"] = {**old, **p, "at": now.isoformat(timespec="seconds")}
    bf = r.get("before") or {}; r["before"] = bf
    wx = p.get("wx")
    if wx and not bf.get("complete"):
        bf.update({"weather": wx["weather"], "windSpeed": wx["windSpeed"], "wave": wx["wave"],
                   "windDir": wind_code(j, wx["windCompass"], wx["windSpeed"])})
    return bool(r["result"].get("payout")) and bool(r["result"].get("km"))


# ---------------------------------------------------------------- 1回分
def ts(r, k):
    v = r.get(k)
    try:
        return dt.datetime.fromisoformat(v) if v else None
    except ValueError:
        return None


def tick(root: Path, D: str, now: dt.datetime) -> dict:
    path = root / f"{D}.json"
    day = read_json(path, {"date": D, "races": []})
    st = {"card": 0, "dl": 0, "before": 0, "result": 0}
    if not day["races"] or not all(r.get("bcCard") for r in day["races"]) and not day.get("bcCardAt"):
        st["card"] = build_card(D, day, root)
        day["bcCardAt"] = now.isoformat(timespec="seconds")
    h = ts(day, "holdingAt")
    if not h or (now - h).total_seconds() > 1800 or any(not r.get("deadline") for r in day["races"]):
        if not h or (now - h).total_seconds() > 300:
            st["dl"] = apply_holding(D, day)
    sui = {}
    for r in day["races"]:
        d0 = deadline_dt(r)
        if not d0 or r.get("cancel"):
            continue
        mins = (d0 - now).total_seconds() / 60
        bf = r.get("before") or {}
        last = ts(bf, "fetchedAt")
        need_ori = bf.get("complete") and (not bf.get("ori") or ori_incomplete(bf["ori"])) and mins > -30
        if (-5 <= mins <= 25 and not bf.get("complete")) or (need_ori and mins <= 20):
            if not last or (now - last).total_seconds() >= RECHECK:
                update_before(r, D, now, sui); st["before"] += 1
        if bf.get("complete") and not bf.get("stt2") and mins > -360:  # 11/20 朝の展示STの読み違いを直す（1回だけ）
            t = get(f"/hp_txt/{r['jcd']:02d}/bc_j_stt_{D}_{r['jcd']:02d}_{r['rno']:02d}.txt")
            if t:
                for w, v in parse_stt(t).items():
                    bf.setdefault("boats", {}).setdefault(w, {}).update({k: x for k, x in v.items() if x is not None})
            bf["stt2"] = True
        res = r.get("result") or {}
        done = res.get("order") and res.get("payout") and res.get("km") and res.get("st")
        if not done and mins <= -2 and mins >= -360:
            la = ts(res, "at")
            if not la or (now - la).total_seconds() >= RECHECK:
                if not update_result(r, D, now):
                    r["result"] = {**(r.get("result") or {}), "at": now.isoformat(timespec="seconds")}
                st["result"] += 1
    day["updated"] = now.isoformat(timespec="seconds")
    day["src"] = "boatcast"
    write_json(path, day)
    idx = read_json(root / "index.json", {"dates": []})
    if D not in idx.get("dates", []):
        idx["dates"] = sorted(set(idx.get("dates", [])) | {D}, reverse=True)
        write_json(root / "index.json", idx)
    return st


def fill_ori(root: Path, D: str) -> int:
    path = root / f"{D}.json"
    day = read_json(path, None)
    if not day:
        return 0
    n = 0
    for r in day["races"]:
        bf = r.get("before") or {}; r["before"] = bf
        if bf.get("ori") and not ori_incomplete(bf["ori"]):
            continue
        t = get(f"/txt/{r['jcd']:02d}/bc_oriten_{D}_{r['jcd']:02d}_{r['rno']:02d}.txt")
        o = parse_oriten(t) if t else None
        if o:
            bf["ori"] = o; bf["oriAt"] = now_jst().isoformat(timespec="seconds"); n += 1
    write_json(path, day)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--date")
    ap.add_argument("--fill-ori", nargs="*")
    ap.add_argument("--force-load", action="store_true")
    a = ap.parse_args()
    root = Path(a.data)
    flag = root / "bcast_blocked.json"
    now = now_jst()
    b = read_json(flag, None)
    if b and b.get("date") == now.strftime("%Y%m%d"):
        log("BOATCAST に断られているため、今日は取得しません", b); return
    try:
        sv = check_alive()
        if a.fill_ori is not None:
            for D in a.fill_ori:
                log(D, "オリジナル展示を補完", fill_ori(root, D), "R")
            return
        if a.date:
            day = read_json(root / f"{a.date}.json", {"date": a.date, "races": []})
            n = build_card(a.date, day, root, full=a.force_load)
            if a.date == sv.get("today"):
                apply_holding(a.date, day)
            day["bcCardAt"] = now.isoformat(timespec="seconds")
            write_json(root / f"{a.date}.json", day)
            log(a.date, "出走表", n, "R")
            tick(root, a.date, now)
            return
        D = now.strftime("%Y%m%d")
        log(D, tick(root, D, now))
        # 21時以降は翌日の出走表を用意（前の晩に読み込む）
        if now.hour >= 21:
            T = (now + dt.timedelta(days=1)).strftime("%Y%m%d")
            day = read_json(root / f"{T}.json", {"date": T, "races": []})
            if not day.get("bcCardAt"):
                n = build_card(T, day, root)
                day["bcCardAt"] = now.isoformat(timespec="seconds"); day["preloaded"] = True
                write_json(root / f"{T}.json", day)
                idx = read_json(root / "index.json", {"dates": []})
                idx["dates"] = sorted(set(idx.get("dates", [])) | {T}, reverse=True)
                write_json(root / "index.json", idx)
                log(T, "翌日の出走表", n, "R")
    except Blocked as e:
        write_json(flag, {"date": now.strftime("%Y%m%d"), "at": now.isoformat(timespec="seconds"), "why": str(e)})
        log("BOATCAST に断られたので止めます:", e)
    finally:
        log(f"BOATCAST への取得 {NREQ}回")


if __name__ == "__main__":
    main()
