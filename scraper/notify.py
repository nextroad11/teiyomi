"""スマホへの通知（ntfy）。トピック名は GitHub の Secrets（NTFY_TOPIC）に置き、公開されるファイルには書かない。
使い方: python scraper/notify.py "タイトル" "本文" [優先度1-5] [タグ]"""
import os
import sys

import requests


def send(title: str, body: str, priority: int = 3, tags: str = "speedboat") -> bool:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC が未設定のため通知しません")
        return False
    r = requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), timeout=15,
                      headers={"Title": title.encode("utf-8"), "Priority": str(priority), "Tags": tags,
                               "Click": "https://nextroad11.github.io/teiyomi/"})
    print("通知", r.status_code)
    return r.ok


if __name__ == "__main__":
    a = sys.argv[1:]
    send(a[0], a[1], int(a[2]) if len(a) > 2 else 3, a[3] if len(a) > 3 else "speedboat")
