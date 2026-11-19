"""一回きり：公式の配布ファイル（mbrace）の公開状況を確認（boatrace.jp には一切アクセスしない）。"""
import sys, requests
H = {"User-Agent": "teiyomi-bot/1.0 (personal race analysis; GitHub Actions)"}
for kind, d in [("K", "261116"), ("K", "261117"), ("K", "261118"), ("K", "261119"), ("B", "261119"), ("B", "261120"), ("B", "261121")]:
    u = f"https://www1.mbrace.or.jp/od2/{kind}/20{d[:4]}/{kind.lower()}{d}.lzh"
    try:
        r = requests.get(u, headers=H, timeout=30); print(kind, d, r.status_code, len(r.content), r.headers.get("Last-Modified"), flush=True)
    except Exception as e:
        print(kind, d, e)
