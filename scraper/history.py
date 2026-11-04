"""公式の過去データ（番組表 B / 競走成績 K）を取得する。

配布元: https://www1.mbrace.or.jp/od2/{B|K}/YYYYMM/{b|k}YYMMDD.lzh
--sample: 1日分を展開して先頭部分を data/debug/ に保存（形式確認用）
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import tempfile
import time
from pathlib import Path

import requests

BASE = "https://www1.mbrace.or.jp/od2"
HEADERS = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}


def download_text(kind: str, day: dt.date) -> str | None:
    """kind: 'B'(番組表) or 'K'(競走成績)。展開したテキスト（Shift_JIS→str）を返す"""
    url = f"{BASE}/{kind}/{day:%Y%m}/{kind.lower()}{day:%y%m%d}.lzh"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200 or len(r.content) < 100:
        print(f"  {url} -> HTTP {r.status_code}")
        return None
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.lzh"
        p.write_bytes(r.content)
        subprocess.run(["lha", "xqf", "a.lzh"], cwd=td, check=True)
        txts = [f for f in Path(td).iterdir() if f.suffix.upper() == ".TXT"]
        if not txts:
            print(f"  {url}: 展開後にテキストがありません {list(Path(td).iterdir())}")
            return None
        return txts[0].read_bytes().decode("cp932", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--sample", action="store_true")
    a = ap.parse_args()
    root = Path(a.data)
    if a.sample:
        dbg = root / "debug"
        dbg.mkdir(parents=True, exist_ok=True)
        day = dt.date.today() - dt.timedelta(days=3)
        for kind in ("B", "K"):
            t = download_text(kind, day)
            time.sleep(1)
            if t:
                lines = t.splitlines()
                (dbg / f"hist_{kind}_sample.txt").write_text("\n".join(lines[:600]), encoding="utf-8")
                print(f"{kind}: {len(lines)}行 保存")


if __name__ == "__main__":
    main()
