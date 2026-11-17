"""全24場の「場の向き」（公式の直前情報ページの is-direction）を確かめる一回きりの下見。"""
import re, sys, time
from pathlib import Path
import requests
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
V = {"6": ["20261104", 12], "7": ["20261114", 12], "8": ["20261116", 12], "9": ["20261115", 12], "10": ["20261114", 12], "14": ["20261111", 12], "15": ["20261116", 12], "16": ["20261116", 12], "17": ["20261112", 12], "19": ["20261112", 12], "20": ["20261116", 12], "21": ["20261112", 12], "23": ["20261116", 12], "1": ["20261108", 12], "3": ["20261116", 12], "12": ["20261110", 12], "18": ["20261116", 12], "2": ["20261115", 12], "5": ["20261111", 12], "11": ["20261116", 12], "22": ["20261115", 12], "24": ["20261116", 12], "4": ["20261114", 12], "13": ["20261116", 12]}
lines = []
for j, (d, rno) in sorted(V.items(), key=lambda x: int(x[0])):
    u = f"https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno={rno}&jcd={int(j):02d}&hd={d}"
    try:
        h = requests.get(u, headers=H, timeout=20).text
        m = re.search(r"is-direction(\d+)", h); w = re.search(r"is-wind(\d+)", h)
        lines.append(f"{j}\t{d}\t{m.group(1) if m else ''}\t{w.group(1) if w else ''}")
    except Exception as e:
        lines.append(f"{j}\t{d}\terror {e}")
    time.sleep(1)
(out / "venue_direction.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
