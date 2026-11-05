"""アプリが読むデータを合言葉（GitHub Secrets の APP_PASS）で暗号化する。

- 暗号化: 合言葉 → PBKDF2-SHA256(310000回) → AES-256-GCM。アプリは WebCrypto で同じ計算をして読む。
- 受け箱: Claude など合言葉を知らない人が、予想（一撃くんの買い目など）を安全に渡すための仕組み。
  合言葉から作った X25519 の鍵の「公開鍵」（enc/pub.txt）で封をして inbox/ に置くと、
  GitHub Actions が合言葉で開けて、暗号化した picks に混ぜる。

使い方（GitHub Actions 内、APP_PASS を環境変数で渡す）
  python scraper/crypt.py encrypt data/model.json data/enc/model.json
  python scraper/crypt.py decrypt data/enc/model.json data/model.json
  python scraper/crypt.py pub data/enc/pub.txt
  python scraper/crypt.py inbox data            # inbox/*.json を enc/picks/ に取り込む
使い方（合言葉なし。公開鍵で封をするだけ）
  python scraper/crypt.py seal data/enc/pub.txt picks.json data/inbox/20261105-xxxx.json
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SALT = b"teiyomi-v1"
ITER = 310000
b64 = lambda b: base64.b64encode(b).decode()
unb64 = base64.b64decode


def _pass() -> bytes:
    p = os.environ.get("APP_PASS", "")
    if not p:
        sys.exit("APP_PASS が未設定です")
    return p.encode("utf-8")


def data_key(pw: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pw, SALT, ITER, 32)


def inbox_key(pw: bytes) -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(hashlib.pbkdf2_hmac("sha256", pw, b"teiyomi-inbox", ITER, 32))


def encrypt_bytes(key: bytes, plain: bytes) -> dict:
    iv = secrets.token_bytes(12)
    return {"v": 1, "iv": b64(iv), "ct": b64(AESGCM(key).encrypt(iv, plain, None))}


def decrypt_bytes(key: bytes, box: dict) -> bytes:
    return AESGCM(key).decrypt(unb64(box["iv"]), unb64(box["ct"]), None)


def _hk(shared: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"teiyomi-seal").derive(shared)


def seal(pub_hex: str, plain: bytes) -> dict:
    eph = X25519PrivateKey.generate()
    key = _hk(eph.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))))
    epk = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"epk": epk.hex(), **encrypt_bytes(key, plain)}


def unseal(priv: X25519PrivateKey, box: dict) -> bytes:
    key = _hk(priv.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(box["epk"]))))
    return decrypt_bytes(key, box)


def main():
    cmd, *a = sys.argv[1:]
    if cmd == "seal":
        pub = Path(a[0]).read_text().strip()
        Path(a[2]).parent.mkdir(parents=True, exist_ok=True)
        Path(a[2]).write_text(json.dumps(seal(pub, Path(a[1]).read_bytes())), encoding="utf-8")
        return
    pw = _pass()
    if cmd == "encrypt":
        Path(a[1]).parent.mkdir(parents=True, exist_ok=True)
        Path(a[1]).write_text(json.dumps(encrypt_bytes(data_key(pw), Path(a[0]).read_bytes())), encoding="utf-8")
    elif cmd == "decrypt":
        Path(a[1]).parent.mkdir(parents=True, exist_ok=True)
        Path(a[1]).write_bytes(decrypt_bytes(data_key(pw), json.loads(Path(a[0]).read_text(encoding="utf-8"))))
    elif cmd == "pub":
        pub = inbox_key(pw).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        Path(a[0]).parent.mkdir(parents=True, exist_ok=True)
        Path(a[0]).write_text(pub.hex())
    elif cmd == "inbox":
        root = Path(a[0]); key = data_key(pw); priv = inbox_key(pw); n = 0
        for f in sorted((root / "inbox").glob("*.json")):
            try:
                inc = json.loads(unseal(priv, json.loads(f.read_text(encoding="utf-8"))))
            except Exception as e:  # 壊れた・別の鍵で封をしたもの
                print(f"  {f.name}: 開けません {e}")
                continue
            date = inc["date"]
            dst = root / "enc" / "picks" / f"{date}.json"
            cur = json.loads(decrypt_bytes(key, json.loads(dst.read_text()))) if dst.exists() else {"races": {}}
            for rid, v in inc.get("races", {}).items():
                cur["races"].setdefault(rid, {}).update(v)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(encrypt_bytes(key, json.dumps(cur, ensure_ascii=False).encode())), encoding="utf-8")
            f.unlink(); n += 1
        print(f"受け箱 {n}件を取り込み")
    else:
        sys.exit(f"不明なコマンド {cmd}")


if __name__ == "__main__":
    main()
