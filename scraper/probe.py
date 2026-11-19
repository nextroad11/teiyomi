"""一回きり：競技情報ページの直前情報（yoso05）と結果（kekka01）を5場で確認（boatrace.jp には一切アクセスしない）。"""
import json, re, sys, time, html as H_
from pathlib import Path
import requests
out = Path(sys.argv[1]); (out / "p9").mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
S = {4: "https://www.heiwajima.gr.jp", 12: "https://www.boatrace-suminoe.jp", 15: "https://www.marugameboat.jp", 16: "https://www.kojimaboat.jp", 24: "https://www.omurakyotei.jp"}
def text(t):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S | re.I)
    return re.sub(r"\s+", " ", H_.unescape(re.sub(r"<[^>]+>", " ", t)))
for j, b in S.items():
    for n in ("yoso0501", "kekka0101", "yoso0512", "kekka0112"):
        u = f"{b}/asp/kyogi/{j:02d}/pc/{n}.htm"
        try:
            r = requests.get(u, headers=H, timeout=20); r.encoding = r.apparent_encoding
            tx = text(r.text); (out / "p9" / f"{j:02d}_{n}.txt").write_text(tx[:60000], encoding="utf-8")
            print(j, n, r.status_code, {k: tx.count(k) for k in ["展示タイム", "展示", "チルト", "進入", "スタート展示", "決まり手", "風速", "波高", "部品", "ST"]}, flush=True)
        except Exception as e:
            print(j, n, e)
        time.sleep(2)
