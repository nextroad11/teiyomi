"""艇読みAI データ取得スクリプト

GitHub Actions から5分おきに呼ばれ、公式サイト（boatrace.jp）から
  1. 朝: その日の全場・全レースの出走表
  2. 締切25分前〜: 直前情報（展示タイム・チルト・進入・風・波）
  3. 締切後: 3連単の結果と払戻
を取得して data/YYYYMMDD.json に保存する。

使い方: python scraper/teiyomi_scraper.py --data data [--force-load] [--date YYYYMMDD]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

JST = ZoneInfo("Asia/Tokyo")
BASE = "https://www.boatrace.jp/owpc/pc/race"
HEADERS = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
VENUES = {1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖", 7: "蒲郡", 8: "常滑",
          9: "津", 10: "三国", 11: "びわこ", 12: "住之江", 13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島",
          17: "宮島", 18: "徳山", 19: "下関", 20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村"}
SLEEP = 1.0  # 公式サイトに負担をかけないよう、1秒に1回まで

session = requests.Session()
session.headers.update(HEADERS)
_last = 0.0
debug_dir: Path | None = None


def log(*a):
    print(*a, flush=True)


def get(url: str) -> str | None:
    global _last
    wait = SLEEP - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(2):
        try:
            r = session.get(url, timeout=20)
            _last = time.time()
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r.text
            log(f"  HTTP {r.status_code}: {url}")
            return None
        except requests.RequestException as e:
            log(f"  error ({attempt + 1}): {e}")
            time.sleep(3)
    return None


def save_debug(kind: str, html: str):
    """解析を改良するため、ページ種別ごとに最新のHTMLを1つだけ残す"""
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / f"{kind}.html").write_text(html, encoding="utf-8")


def text_of(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    s = soup.get_text(" ", strip=True)
    return re.sub(r"[ \t\r\n]+", " ", s)


def fnum(s):
    if s is None:
        return None
    s = str(s).strip()
    if s in ("", "-", "－"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def inum(s):
    v = fnum(s)
    return None if v is None else int(v)


# ---------------------------------------------------------------- 開催場一覧
def venues_of_day(hd: str) -> list[int]:
    html = get(f"{BASE}/index?hd={hd}")
    if not html:
        return []
    jcds = sorted({int(m) for m in re.findall(r"raceindex\?jcd=(\d{2})&(?:amp;)?hd=" + hd, html)})
    return jcds


# ---------------------------------------------------------------- 出走表
NUM = r"([\d.]+|-)"
BOAT_RE = re.compile(
    r"(\d{4})\s*/\s*(A1|A2|B1|B2)\s+(.+?)\s+([^\s/]+)\s*/\s*([^\s/]+)\s+(\d+)\s*歳\s*/\s*([\d.]+)\s*kg\s+"
    r"F(\d+)\s+L(\d+)\s+" + r"\s+".join([NUM] * 13)
)


def parse_racelist(html: str) -> dict | None:
    txt = text_of(html)
    boats = []
    for m in BOAT_RE.finditer(txt):
        g = m.groups()
        boats.append({
            "waku": len(boats) + 1, "toban": int(g[0]), "cls": g[1],
            "name": re.sub(r"[\s　]+", "", g[2]), "branch": g[3],
            "age": inum(g[5]), "weight": fnum(g[6]), "f": inum(g[7]), "l": inum(g[8]),
            "st": fnum(g[9]), "natWin": fnum(g[10]), "nat2": fnum(g[11]), "nat3": fnum(g[12]),
            "locWin": fnum(g[13]), "loc2": fnum(g[14]), "loc3": fnum(g[15]),
            "motor": inum(g[16]), "motor2": fnum(g[17]), "motor3": fnum(g[18]),
            "boat": inum(g[19]), "boat2": fnum(g[20]), "boat3": fnum(g[21]),
        })
        if len(boats) == 6:
            break
    if len(boats) != 6:
        return None
    out = {"boats": boats}
    # 締切予定時刻（1R〜の並び）
    m = re.search(r"締切予定時刻((?:\s+\d{1,2}:\d{2})+)", txt)
    if m:
        out["deadlines"] = re.findall(r"\d{1,2}:\d{2}", m.group(1))
    # レース名と距離（例: 予選 1800m）
    m = re.search(r"([^\s]{1,20})\s+(\d{3,4})m\b", txt)
    if m:
        out["name"], out["distance"] = m.group(1), int(m.group(2))
    soup = BeautifulSoup(html, "html.parser")
    h = soup.select_one(".heading2_titleName") or soup.find("h2")
    if h:
        out["title"] = h.get_text(" ", strip=True)
    g = re.search(r"heading2_title\s+is-([A-Za-z0-9]+)", html)
    if g:
        out["grade"] = g.group(1)
    d = re.search(r"(\d+日目|初日|最終日)", txt)
    if d:
        out["day"] = d.group(1)
    return out


def load_day(hd: str, day: dict, only_new: bool = True):
    jcds = venues_of_day(hd)
    log(f"開催場: {[VENUES.get(j, j) for j in jcds]}")
    have = {(r["jcd"], r["rno"]) for r in day["races"]}
    for jcd in jcds:
        deadlines = []
        for rno in range(1, 13):
            if only_new and (jcd, rno) in have:
                continue
            html = get(f"{BASE}/racelist?rno={rno}&jcd={jcd:02d}&hd={hd}")
            if not html:
                break
            p = parse_racelist(html)
            if not p:
                save_debug("racelist_failed", html)
                log(f"  {VENUES[jcd]}{rno}R: 出走表を読めませんでした")
                if rno == 1:
                    break
                continue
            save_debug("racelist", html)
            deadlines = p.get("deadlines") or deadlines
            race = {
                "id": f"{hd}-{jcd:02d}-{rno:02d}", "date": hd, "jcd": jcd, "venue": VENUES[jcd], "rno": rno,
                "title": p.get("title"), "grade": p.get("grade"), "day": p.get("day"),
                "name": p.get("name"), "distance": p.get("distance"),
                "deadline": deadlines[rno - 1] if len(deadlines) >= rno else None,
                "boats": p["boats"], "before": None, "result": None,
            }
            day["races"].append(race)
            log(f"  {VENUES[jcd]}{rno}R 取得（締切 {race['deadline']}）")
    day["races"].sort(key=lambda r: (r["jcd"], r["rno"]))
    day["loadedAt"] = now_jst().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 直前情報
def parse_beforeinfo(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    boats = {}
    for tb in soup.find_all("tbody"):
        tr = tb.find("tr")
        if not tr:
            continue
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not cells or cells[0] not in list("123456"):
            continue
        waku = cells[0]
        if waku in boats:
            continue
        ex = tilt = None
        prop = parts = ""
        for i, c in enumerate(cells[1:], start=1):
            if ex is None and re.fullmatch(r"\d\.\d{2}", c) and 6.0 <= float(c) <= 7.8:
                ex = float(c)
                if i + 1 < len(cells) and re.fullmatch(r"-?\d\.\d", cells[i + 1]):
                    tilt = float(cells[i + 1])
                    # チルトの後ろは プロペラ（新など）・部品交換（リング等）
                    prop = cells[i + 2] if i + 2 < len(cells) else ""
                    parts = cells[i + 3] if i + 3 < len(cells) else ""
                break
        boats[waku] = {"exTime": ex, "tilt": tilt, "prop": prop, "parts": parts}
    # スタート展示: 上から順にコース1〜6
    order = re.findall(r"table1_boatImage1Number[^\"]*\"[^>]*>\s*(\d)\s*<", html)
    sts = re.findall(r"table1_boatImage1Time[^>]*>\s*([^<]*?)\s*<", html)
    if len(order) >= 6:
        for course, w in enumerate(order[:6], start=1):
            boats.setdefault(w, {})["course"] = course
            if course - 1 < len(sts):
                t = sts[course - 1].replace(" ", "")
                m = re.fullmatch(r"(F|L)?(\d*\.\d+)", t)
                if m:  # 展示のST。フライングはマイナスで持つ
                    v = float(m.group(2))
                    boats[w]["exST"] = -v if m.group(1) == "F" else v
    txt = text_of(html)
    out = {"boats": boats}
    m = re.search(r"風速\s*(\d+)\s*m", txt)
    if m:
        out["windSpeed"] = int(m.group(1))
    m = re.search(r"波高\s*(\d+)\s*cm", txt)
    if m:
        out["wave"] = int(m.group(1))
    m = re.search(r"is-wind(\d+)", html)
    if m:
        out["windDir"] = int(m.group(1))  # 1〜16の方位番号（公式の表記）
    m = re.search(r"天候\s*(\S+)", txt)
    if m:
        out["weather"] = m.group(1)
    exs = [b.get("exTime") for b in boats.values() if b.get("exTime")]
    out["complete"] = len(exs) == 6
    return out if boats else None


# ---------------------------------------------------------------- 結果
RESULT_RE = re.compile(r"3連単\s*(\d)\s*-\s*(\d)\s*-\s*(\d)\s*¥?\s*([\d,]+)")


def parse_result(html: str) -> dict | None:
    txt = text_of(html)
    m = RESULT_RE.search(txt)
    if m:
        return {"order": f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "payout": int(m.group(4).replace(",", ""))}
    if re.search(r"(レース中止|不成立|返還)", txt) and "3連単" in txt:
        return {"order": "", "payout": 0, "note": "中止・返還"}
    return None


# ---------------------------------------------------------------- オリジナル展示（BOATCAST）
BOATCAST = "https://race.boatcast.jp"


def fetch_oriten(hd: str, jcd: int, rno: int) -> dict | None:
    """一周・まわり足・直線など（場ごとに項目が違う）。{items:[...], boats:{"1":[37.17, 5.63, 7.41], ...}}"""
    url = f"{BOATCAST}/txt/{jcd:02d}/bc_oriten_{hd}_{jcd:02d}_{rno:02d}.txt"
    txt = get(url)
    return parse_oriten(txt) if txt else None


def parse_oriten(txt: str) -> dict | None:
    lines = [l for l in txt.replace("\r", "").split("\n") if l.strip() and not l.startswith("data=")]
    if len(lines) < 3:
        return None
    items = [re.sub(r"[\s\u3000]", "", x) for x in lines[1].split("\t") if x.strip()]
    boats = {}
    for l in lines[2:]:
        c = l.split("\t")
        if c and c[0].strip() in list("123456"):
            vals = [fnum(x) for x in c[2:2 + len(items)]]
            boats[c[0].strip()] = vals
    if not any(v is not None for vs in boats.values() for v in vs):
        return None
    return {"items": items, "boats": boats}


# ---------------------------------------------------------------- 3連単オッズ
# 並び順は 1-2-3, 1-2-4, ... 6-5-4（辞書順の120通り）。アプリも同じ順で読む
TRI_KEYS = [f"{a}-{b}-{c}" for a in range(1, 7) for b in range(1, 7) for c in range(1, 7) if len({a, b, c}) == 3]
TRI_INDEX = {k: i for i, k in enumerate(TRI_KEYS)}


def parse_odds3t(html: str) -> dict | None:
    """公式の3連単オッズ表。20行×6列で、列が1着、4行ごとに2着、各行が3着。"""
    soup = BeautifulSoup(html, "html.parser")
    cells = soup.select("td.oddsPoint")
    if len(cells) != 120:
        return None
    odds = [None] * 120
    mismatch = 0
    for i, td in enumerate(cells):
        row, col = divmod(i, 6)
        a = col + 1
        rest = [x for x in range(1, 7) if x != a]
        b = rest[row // 4]
        rest2 = [x for x in rest if x != b]
        c = rest2[row % 4]
        # 念のため、直前のセル（3着の艇番）と位置からの読みが合っているか確かめる
        prev = td.find_previous_sibling("td")
        if prev is not None and prev.get_text(strip=True).isdigit() and int(prev.get_text(strip=True)) != c:
            mismatch += 1
        v = fnum(td.get_text(strip=True).replace(",", ""))
        odds[TRI_INDEX[f"{a}-{b}-{c}"]] = v if v and v >= 1.0 else None
    vals = [v for v in odds if v]
    if len(vals) < 60:
        return None
    inv = sum(1 / v for v in vals)  # 控除率25%なら約1.33
    return {"t": odds, "inv": round(inv, 3), "mismatch": mismatch}


# ---------------------------------------------------------------- 本体
def now_jst() -> dt.datetime:
    return dt.datetime.now(JST)


def deadline_dt(r: dict) -> dt.datetime | None:
    if not r.get("deadline"):
        return None
    h, m = map(int, r["deadline"].split(":"))
    d = dt.datetime.strptime(r["date"], "%Y%m%d").replace(tzinfo=JST)
    return d.replace(hour=h % 24, minute=m) + (dt.timedelta(days=1) if h >= 24 else dt.timedelta())


def update_before_and_results(day: dict, now: dt.datetime) -> int:
    n = 0
    for r in day["races"]:
        dl = deadline_dt(r)
        if not dl:
            continue
        hd, jcd, rno = r["date"], r["jcd"], r["rno"]
        q = f"rno={rno}&jcd={jcd:02d}&hd={hd}"
        # 直前情報: 締切25分前〜締切3分後、全艇の展示がそろうまで
        b = r.get("before") or {}
        if dl - dt.timedelta(minutes=25) <= now <= dl + dt.timedelta(minutes=3) and not b.get("complete"):
            html = get(f"{BASE}/beforeinfo?{q}")
            if html:
                save_debug("beforeinfo", html)
                p = parse_beforeinfo(html)
                if p and any(v.get("exTime") for v in p["boats"].values()):
                    p["fetchedAt"] = now.isoformat(timespec="seconds")
                    r["before"] = p
                    n += 1
                    log(f"  {r['venue']}{rno}R 直前情報 {'完了' if p['complete'] else '一部'}")
        # オリジナル展示: 展示が出そろってから、取れるまで
        b = r.get("before") or {}
        if b.get("complete") and not b.get("ori") and now <= dl + dt.timedelta(minutes=3):
            o = fetch_oriten(hd, jcd, rno)
            if o:
                b["ori"] = o
                n += 1
                log(f"  {r['venue']}{rno}R オリジナル展示 {'・'.join(o['items'])}")
        # 3連単オッズ: 締切20分前〜締切1分後。毎回取り直して最新にする（締切時点のものが残る）
        o = r.get("odds") or {}
        if dl - dt.timedelta(minutes=20) <= now <= dl + dt.timedelta(minutes=1) and not o.get("final"):
            html = get(f"{BASE}/odds3t?{q}")
            if html:
                save_debug("odds3t", html)
                p = parse_odds3t(html)
                if p:
                    p["fetchedAt"] = now.isoformat(timespec="seconds")
                    p["final"] = now >= dl
                    r["odds"] = p
                    n += 1
                    log(f"  {r['venue']}{rno}R オッズ 合計{p['inv']} ずれ{p['mismatch']}")
        # 結果: 締切8分後〜6時間後
        if not r.get("result") and dl + dt.timedelta(minutes=8) <= now <= dl + dt.timedelta(hours=6):
            html = get(f"{BASE}/raceresult?{q}")
            if html:
                p = parse_result(html)
                if p:
                    save_debug("raceresult", html)
                    r["result"] = p
                    n += 1
                    log(f"  {r['venue']}{rno}R 結果 {p['order']} {p['payout']}円")
    return n


def read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(p: Path, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main():
    global debug_dir
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--force-load", action="store_true")
    ap.add_argument("--date")
    a = ap.parse_args()
    root = Path(a.data)
    root.mkdir(parents=True, exist_ok=True)
    debug_dir = root / "debug"
    now = now_jst()
    hd = a.date or now.strftime("%Y%m%d")
    path = root / f"{hd}.json"
    day = read_json(path, {"date": hd, "races": []})
    before = json.dumps(day, ensure_ascii=False, sort_keys=True)

    # 1. 出走表（その日最初の実行、または手動指定）
    if a.force_load or not day.get("loadedAt"):
        if now.hour >= 7 or a.date or a.force_load:
            load_day(hd, day)
    # 朝の取り込み後、昼までに追加で開催が見つかる場合に備えて正午に一度だけ再確認
    elif now.hour >= 12 and not day.get("rechecked"):
        load_day(hd, day)
        day["rechecked"] = True

    # 2. 直前情報と結果
    n = update_before_and_results(day, now)

    # 前日の結果の取りこぼし（朝の時間帯だけ）
    if now.hour < 10:
        yd = (now - dt.timedelta(days=1)).strftime("%Y%m%d")
        ypath = root / f"{yd}.json"
        yday = read_json(ypath, None)
        if yday:
            ybefore = json.dumps(yday, ensure_ascii=False, sort_keys=True)
            for r in yday["races"]:
                if not r.get("result"):
                    html = get(f"{BASE}/raceresult?rno={r['rno']}&jcd={r['jcd']:02d}&hd={yd}")
                    p = parse_result(html) if html else None
                    if p:
                        r["result"] = p
            if json.dumps(yday, ensure_ascii=False, sort_keys=True) != ybefore:
                write_json(ypath, yday)

    if json.dumps(day, ensure_ascii=False, sort_keys=True) != before:
        day["updated"] = now.isoformat(timespec="seconds")
        write_json(path, day)
        idx = read_json(root / "index.json", {"dates": []})
        dates = sorted(set(idx.get("dates", [])) | {hd}, reverse=True)
        write_json(root / "index.json", {"dates": dates, "updated": day["updated"]})
        log(f"保存: {path}（{len(day['races'])}レース、更新 {n}件）")
    else:
        log("変更なし")


if __name__ == "__main__":
    sys.exit(main())
