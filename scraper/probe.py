"""翌日の出走表が前の晩に公式に出ているかを確かめる一回きりの下見。"""
import sys, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import teiyomi_scraper as t
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
now = t.now_jst(); td = (now + dt.timedelta(days=1)).strftime("%Y%m%d")
lines = [f"今 {now.isoformat()} 翌日 {td}"]
html = t.get(f"{t.BASE}/index?hd={td}")
(out / "index_tomorrow.html").write_text(html or "", encoding="utf-8")
j = t.venues_of_day(td); lines.append(f"開催場 {j}")
if j:
    h = t.get(f"{t.BASE}/racelist?rno=1&jcd={j[0]:02d}&hd={td}")
    (out / "racelist_tomorrow.html").write_text(h or "", encoding="utf-8")
    p = t.parse_racelist(h) if h else None
    lines.append(f"1R 読めた {bool(p)} 選手 {len(p['boats']) if p else 0} 締切 {p.get('deadlines') if p else None}")
(out / "tomorrow.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
