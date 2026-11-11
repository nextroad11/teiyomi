"""公式の過去データ（番組表 B / 競走成績 K）を取得し、学習用の形にそろえる。

配布元: https://www1.mbrace.or.jp/od2/{B|K}/YYYYMM/{b|k}YYMMDD.lzh
保存先: data/history/YYYYMMDD.json（1日1ファイル、全場・全レース）

使い方:
  python scraper/history.py --data data            # 未取得の日を古い順に埋める（既定は直近400日）
  python scraper/history.py --data data --days 30
  python scraper/history.py --parse-b B.txt --parse-k K.txt   # 手元のテキストで解析だけ確認
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import tempfile
import time
import unicodedata
from pathlib import Path

import requests

BASE = "https://www1.mbrace.or.jp/od2"
HEADERS = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def download_text(kind: str, day: dt.date) -> str | None:
    url = f"{BASE}/{kind}/{day:%Y%m}/{kind.lower()}{day:%y%m%d}.lzh"
    try:
        r = requests.get(url, headers=HEADERS, timeout=(10, 30))
    except requests.RequestException as e:
        print(f"  {url}: {e}")
        return None
    if r.status_code != 200 or len(r.content) < 100:
        return None
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.lzh").write_bytes(r.content)
        p = subprocess.run(["lha", "xqf", "a.lzh"], cwd=td, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"lha {p.returncode} {url} head={r.content[:40]!r} {p.stderr[:200]}")
        txts = [f for f in Path(td).iterdir() if f.suffix.upper() == ".TXT"]
        return txts[0].read_bytes().decode("cp932", errors="replace") if txts else None


# ---------------------------------------------------------------- 番組表（出走前の情報）
B_ROW = re.compile(r"^([1-6]) (\d{4})(.{4})(\d{2})(.{2})(\d{2})([AB][12])")
# 級別の後ろは固定幅（全国勝率5 全国2連6 当地勝率5 当地2連6 モーター3 2連6 ボート3 2連6）。
# 100.00 などで数字同士がくっつくので、空白ではなく桁位置で切る
B_WIDTHS = (5, 6, 5, 6, 3, 6, 3, 6)


def fixed_fields(rest: str):
    out, i = [], 0
    for w in B_WIDTHS:
        f = rest[i:i + w].strip()
        if not re.fullmatch(r"\d+(\.\d+)?", f):
            return None
        out.append(f)
        i += w
    return out
B_RACE = re.compile(r"^\s*(\d{1,2})R\s+(\S+).*?H(\d{3,4})m(?:.*?締切予定(\d{1,2}:\d{2}))?")


def parse_b(text: str) -> dict:
    """{(jcd, rno): {name, distance, deadline, boats:{waku: {...}}}}"""
    out, jcd, cur = {}, None, None
    for raw in text.splitlines():
        m = re.match(r"^(\d{2})BBGN", raw)
        if m:
            jcd = int(m.group(1))
            continue
        if jcd is None:
            continue
        line = nfkc(raw)
        m = B_RACE.match(line)
        if m and "R" in line[:8]:
            cur = out.setdefault((jcd, int(m.group(1))), {
                "name": m.group(2), "distance": int(m.group(3)), "deadline": m.group(4), "boats": {}})
            continue
        m = B_ROW.match(raw)
        if m and cur is not None:
            t = fixed_fields(raw[m.end():])
            if t is None:
                continue
            g = m.groups() + tuple(t[:8])
            cur["boats"][int(g[0])] = {
                "toban": int(g[1]), "name": g[2].replace("\u3000", "").strip(), "branch": g[4].replace("\u3000", "").strip(),
                "age": int(g[3]), "weight": int(g[5]), "cls": g[6],
                "natWin": float(g[7]), "nat2": float(g[8]), "locWin": float(g[9]), "loc2": float(g[10]),
                "motor": int(g[11]), "motor2": float(g[12]), "boat": int(g[13]), "boat2": float(g[14]),
            }
    return out


# ---------------------------------------------------------------- 競走成績（結果）
K_RACE = re.compile(r"^\s+(\d{1,2})R\s+.*?H(\d{3,4})m\s+(\S+)\s+風\s+(\S+)\s+(\d+)m\s+波\s+(\d+)cm")
K_ROW = re.compile(r"^\s+(\S{1,2})\s+([1-6]) (\d{4}) ")
K_TRI = re.compile(r"3連単\s+(\d)-(\d)-(\d)\s+(\d+)\s+人気\s+(\d+)")


def fnum(s):
    m = re.search(r"\d*\.\d+", s or "")
    return float(m.group(0)) if m else None


def parse_k(text: str) -> dict:
    """{(jcd, rno): {weather, windDir, windSpeed, wave, tri:{order,payout,pop}, boats:{waku:{finish,course,exTime,st,flying}}}}"""
    out, jcd, cur = {}, None, None
    for raw in text.splitlines():
        m = re.match(r"^(\d{2})KBGN", raw)
        if m:
            jcd = int(m.group(1))
            continue
        if jcd is None:
            continue
        line = nfkc(raw)
        m = K_RACE.match(line)
        if m:
            cur = out.setdefault((jcd, int(m.group(1))), {
                "weather": m.group(3), "windDir": m.group(4), "windSpeed": int(m.group(5)), "wave": int(m.group(6)),
                "boats": {}, "tri": None})
            continue
        if cur is None:
            continue
        if "レースタイム" in line:  # 見出し行の右端が決まり手（逃げ・差し・まくり・まくり差し・抜き・恵まれ）
            km = line.split("レースタイム", 1)[1].strip()
            cur["kimarite"] = km or None
            continue
        m = K_ROW.match(line)
        if m:
            code, waku = m.group(1), int(m.group(2))
            rest = line[m.end():]
            # 氏名（全角8文字、NFKCで空白が詰まるため元の行から位置で切る）の後ろの数値列
            nums = re.findall(r"F?L?\d*\.\d+|\d+|\.", rest)
            # nums: [モーター, ボート, 展示, 進入, ST, ...]
            ex = course = st = None
            if len(nums) >= 5:
                ex = fnum(nums[2]) if "." in nums[2] else None
                course = int(nums[3]) if nums[3].isdigit() and 1 <= int(nums[3]) <= 6 else None
                st = fnum(nums[4])
            cur["boats"][waku] = {
                "finish": int(code) if code.isdigit() else None, "code": code,
                "course": course, "exTime": ex, "st": st, "flying": code.startswith("F"),
            }
            continue
        m = K_TRI.search(line)
        if m and cur["tri"] is None:
            cur["tri"] = {"order": f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "payout": int(m.group(4)),
                          "pop": int(m.group(5))}
    return out


def merge(day: dt.date, b: dict, k: dict) -> list[dict]:
    races = []
    for key in sorted(set(b) & set(k)):
        jcd, rno = key
        bb, kk = b[key], k[key]
        boats = []
        for w in range(1, 7):
            if w not in bb["boats"] or w not in kk["boats"]:
                break
            boats.append({"waku": w, **bb["boats"][w], **kk["boats"][w]})
        if len(boats) != 6:
            continue
        races.append({"date": f"{day:%Y%m%d}", "jcd": jcd, "rno": rno, "name": bb["name"], "distance": bb["distance"],
                      "deadline": bb["deadline"], "weather": kk["weather"], "windDir": kk["windDir"],
                      "windSpeed": kk["windSpeed"], "wave": kk["wave"], "tri": kk["tri"],
                      "kimarite": kk.get("kimarite"), "boats": boats})
    return races


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument("--max-new", type=int, default=420, help="1回の実行で新しく取る日数の上限")
    ap.add_argument("--minutes", type=float, default=45, help="この時間を過ぎたら区切って保存する")
    ap.add_argument("--names", type=int, default=0, help="直近N日分の番組表を取り直して、選手名と支部を足す")
    ap.add_argument("--kimarite", action="store_true", help="決まり手が無い過去の日に、競走成績だけ取り直して足す")
    ap.add_argument("--parse-b")
    ap.add_argument("--parse-k")
    a = ap.parse_args()

    if a.parse_b and a.parse_k:
        b = parse_b(Path(a.parse_b).read_text(encoding="utf-8"))
        k = parse_k(Path(a.parse_k).read_text(encoding="utf-8"))
        races = merge(dt.date.today(), b, k)
        print(len(b), len(k), len(races))
        print(json.dumps(races[:1], ensure_ascii=False, indent=1)[:2500])
        return

    hist = Path(a.data) / "history"
    hist.mkdir(parents=True, exist_ok=True)
    if a.names:
        t0, n = time.time(), 0
        for f in sorted(hist.glob("2*.json"), reverse=True)[: a.names]:
            if time.time() - t0 > a.minutes * 60:
                print("時間切れ。続きは次回", flush=True)
                break
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("nm") or not d.get("races"):
                continue
            day = dt.datetime.strptime(f.stem, "%Y%m%d").date()
            try:
                b = parse_b(download_text("B", day) or "")
            except Exception as e:
                print(f"  {day}: {e}", flush=True)
                continue
            time.sleep(1)
            for r in d["races"]:
                bb = b.get((r["jcd"], r["rno"]))
                if not bb:
                    continue
                for x in r["boats"]:
                    q = bb["boats"].get(x["waku"])
                    if q and q["toban"] == x["toban"]:
                        x["name"], x["branch"] = q["name"], q["branch"]
            d["nm"] = 1
            f.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            n += 1
        print(f"選手名を追加 {n}日", flush=True)
        return
    if a.kimarite:
        t0, n = time.time(), 0
        for f in sorted(hist.glob("2*.json"), reverse=True):
            if time.time() - t0 > a.minutes * 60:
                print("時間切れ。続きは次回", flush=True)
                break
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("km") or not d.get("races"):
                continue
            day = dt.datetime.strptime(f.stem, "%Y%m%d").date()
            try:
                k = parse_k(download_text("K", day) or "")
            except Exception as e:
                print(f"  {day}: {e}", flush=True)
                continue
            time.sleep(1)
            for r in d["races"]:
                kk = k.get((r["jcd"], r["rno"]))
                if kk:
                    r["kimarite"] = kk.get("kimarite")
            d["km"] = 1
            f.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            n += 1
        print(f"決まり手を追加 {n}日", flush=True)
        return
    today = dt.date.today()
    # 新しい日から順に取る（途中で区切っても直近のデータが先にそろう）
    todo = [today - dt.timedelta(days=i) for i in range(1, a.days + 1)]
    todo = [d for d in todo if not (hist / f"{d:%Y%m%d}.json").exists()][: a.max_new]
    print(f"未取得 {len(todo)}日", flush=True)
    got, t0, errors = 0, time.time(), []
    for d in todo:
        if time.time() - t0 > a.minutes * 60:
            print("時間切れ。続きは次回", flush=True)
            break
        try:
            btxt = download_text("B", d)
            time.sleep(1)
            ktxt = download_text("K", d) if btxt else None
            time.sleep(1)
            races = merge(d, parse_b(btxt), parse_k(ktxt)) if (btxt and ktxt) else None
        except Exception as e:  # 1日分の失敗で全体を止めない
            msg = f"{d}: {type(e).__name__}: {e}"
            print("  " + msg, flush=True)
            errors.append(msg[:300])
            continue
        if races is None:
            # 開催なし・未公開の日も記録して二度取りしない（直近3日は再挑戦）
            if (today - d).days > 3:
                (hist / f"{d:%Y%m%d}.json").write_text('{"races":[]}', encoding="utf-8")
            continue
        (hist / f"{d:%Y%m%d}.json").write_text(
            json.dumps({"races": races, "km": 1, "nm": 1}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        got += 1
        if got % 20 == 0:
            print(f"  {d} まで {got}日分 ({time.time() - t0:.0f}秒)", flush=True)
    print(f"取得 {got}日", flush=True)
    rest = len([1 for i in range(1, a.days + 1)
                if not (hist / f"{today - dt.timedelta(days=i):%Y%m%d}.json").exists()])
    (hist / "_progress.json").write_text(json.dumps(
        {"updated": f"{dt.datetime.now():%Y-%m-%d %H:%M}", "new": got, "remaining": rest,
         "secPerDay": round((time.time() - t0) / max(got, 1), 1),
         "errors": errors[:30]}, ensure_ascii=False), encoding="utf-8")
    Path("/tmp/history_new").write_text(str(got))


if __name__ == "__main__":
    main()
