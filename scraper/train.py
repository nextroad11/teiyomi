"""過去データから予想エンジンの重みを学習し、成績を検証する。

入力: data/history/*.json（history.py が作る）
出力: data/model.json（アプリが読む重み）, data/report.json（学習と検証の成績）

学習するもの
  1. 1着モデル: 場×コースの基礎値 + 選手・機力・ST・展示・F持ち の重み（条件付きロジット）
  2. 2・3着モデル: コース別の基礎値 + 強さの効き方
  3. 人気モデル: 実際の3連単払戻から「世間の見立て」を推定（穴の判定に使う）
  4. 穴の条件: 検証用期間で回収率が最も良くなる人気比・倍率の下限
検証は学習に使っていない直近の期間で行う。
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares, minimize

import os
# モーター（11/20 殿の指摘で見直し）：2連率は乗った選手の腕が混ざるので使わず、
#   mfoot: そのモーターの過去の実測の足（交換後に乗った全員の展示タイム・オリ展のレース内z の平均、少数は0に寄せる）
#   madj : 乗り手の腕を差し引いた成績（着順点 − 選手の全国勝率 − コース差 の平均、少数は0に寄せる）
MOTOR_MODE = os.environ.get("MOTOR_MODE", "new")   # old: 2連率と直近着順 / new: 新しい2つ / both: 全部（比較用）
_MF = {"old": ["motor", "mform"], "new": ["mfoot", "madj"], "both": ["motor", "mform", "mfoot", "madj"]}[MOTOR_MODE]
FEATS = ["skill", "local", *[k for k in _MF if k == "motor"], "boat", "st", "ex", "cwin", "form",
         *[k for k in _MF if k != "motor"], "olap", "oturn", "ostr", "nozoki", "wall", "dash",
         "asa", "amk", "ams", "av1"]
# 相性（11/20 殿の展開予想の式から。テスト8,854Rで1着損失1.1889→1.1856）：攻める艇の今のコースでの差し/まくり/まくり差しの率（log比）
# ＋1コースの選手の差され/まくられ/まくり差され率（log比）。av1＝1コースの選手の負けにくさ（3つの平均の符号反転）
# スリットの隊形（11/20 追加。st は平均STの速さ）：nozoki＝すぐ内の艇より速い、wall＝1コースが2コースより速い、
# dash＝4〜6コースが1〜3コースの平均より速い
PTS = {1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1}
CADJ = {1: 2.39, 2: 0.21, 3: 0.07, 4: -0.37, 5: -0.93, 6: -1.59}  # コースごとの着順点の上乗せ（過去1年の前半から）
MF_K, MA_K = 5, 10
ZAN_K = 8  # 残り方のクセ：少ない選手は0に寄せる強さ


def renew_dates(races):
    """場ごとのモーター交換日：その日の場のモーター2連率の中央値が前の開催日より12以上下がり、25未満になった日"""
    med = defaultdict(lambda: defaultdict(list))
    for r in races:
        for b in r["boats"]:
            if b.get("motor2") is not None:
                med[r["jcd"]][r["date"]].append(b["motor2"])
    out = {}
    for j, dd in med.items():
        last, rs = None, []
        for d in sorted(dd):
            m = float(np.median(dd[d]))
            if last is not None and last - m >= 12 and m < 25:
                rs.append(d)
            last = m
        out[j] = rs
    return out


def motor_key(renew, jcd, date, motor):
    p = [x for x in renew.get(jcd, []) if x <= date]
    return f'{jcd}-{p[-1] if p else "0"}-{motor}'
# olap/oturn/ostr: オリジナル展示の 一周（半周）・まわり足・直線。同じレース内で速いほど＋（無い場は0）
ORI_GROUP = {"一周": 0, "半周ラップ": 0, "半周": 0, "まわり足": 1, "直線": 2}
ORI = {}


def ori_feats(o):
    f = np.zeros((6, 3))
    if not o:
        return f
    for j, name in enumerate(o.get("items", [])):
        g = ORI_GROUP.get(name)
        if g is None:
            continue
        v = np.array([(o["boats"].get(str(w)) or [None] * 9)[j] if j < len(o["boats"].get(str(w)) or []) else None
                      for w in range(1, 7)], dtype=float)
        ok = np.isfinite(v)
        if ok.sum() < 5:
            continue
        sd = max(np.nanstd(v), 0.03)
        f[ok, g] = -np.clip((v[ok] - np.nanmean(v)) / sd, -2.5, 2.5)
    return f
# cwin: その選手のそのコースでの1着率（コースの平均との差、対数オッズ）
# form: 直近10走の平均着順 / mform: そのモーターの直近20走の平均着順（場ごと）
BASE1 = np.array([.55, .14, .12, .11, .06, .02])
CW_K = 8
PERMS = np.array(list(itertools.permutations(range(6), 3)))  # 120通り
PAYBACK = 0.75
CLS = ["A1", "A2", "B1", "B2"]


# ---------------------------------------------------------------- データの準備
def load(root: Path):
    files = sorted(f for f in (root / "history").glob("*.json") if not f.name.startswith("_"))
    races = []
    for f in files:
        races += json.loads(f.read_text(encoding="utf-8")).get("races", [])
    races.sort(key=lambda r: (r["date"], r["jcd"], r["rno"]))
    for f in (root / "oriten").glob("2*.json") if (root / "oriten").exists() else []:
        ORI[f.stem] = json.loads(f.read_text(encoding="utf-8")).get("races", {})
    return races


def cwin_of(wn, c):
    w, n = wn
    p = (w + BASE1[c - 1] * CW_K) / (n + CW_K)
    return float(np.log(p / (1 - p)) - np.log(BASE1[c - 1] / (1 - BASE1[c - 1])))


def form_of(fs, need):
    return (3.5 - float(np.mean(fs))) / 1.5 if len(fs) >= need else 0.0


STATE = {}


def build(races):
    """平均ST・F持ち・コース別成績・調子を過去だけから計算し、特徴量の配列を作る"""
    st_hist = defaultdict(list)   # toban -> 直近のST
    f_dates = defaultdict(list)   # toban -> Fの日付
    cw = defaultdict(lambda: [[0, 0] for _ in range(6)])  # toban -> コース別 [1着, 出走]
    stc = defaultdict(lambda: [[] for _ in range(6)])     # toban -> コース別の直近ST（スリット予測用）
    stv = defaultdict(list)                               # "jcd-course" -> 直近ST（場のクセ）
    recent = defaultdict(list)    # toban -> 直近の着順
    motorf = defaultdict(list)    # "jcd-motor" -> 直近の着順
    mh = defaultdict(lambda: [[], []])  # "jcd-交換日-motor" -> [実測の足z, 腕を差し引いた着順点]
    renew = renew_dates(races)
    # 相性用：決まり手の全体の割合（inkm_features と同じ）と、選手ごとの通算（そのレースより前だけ）
    okr = _ok_races(races); tot = np.zeros(5); totw = np.zeros((6, 4))
    for r in okr:
        km = r.get("kimarite"); wc = [b["course"] for b in r["boats"] if b.get("finish") == 1][0]
        tot[0] += 1
        if wc != 1:
            tot[1 + KM3.index(km) if km in KM3 else 4] += 1
        for b in r["boats"]:
            totw[b["course"] - 1][0] += 1
            if b.get("finish") == 1 and km in KM3:
                totw[b["course"] - 1][1 + KM3.index(km)] += 1
    aPL = tot[1:4] / max(tot[0], 1); aPW = np.clip(totw[:, 1:] / np.maximum(totw[:, :1], 1), 1e-4, 1)
    alose = defaultdict(lambda: np.zeros(5)); awin = defaultdict(lambda: np.zeros((6, 4)))
    arate = lambda a, n, p: (a + INK * p) / (n + INK)
    # 残り方のクセ（11/20）：1着でないときに2・3着へ残った数 − コースごとの期待 を、そのレースより前だけで数える
    zb = np.zeros((6, 2))
    for r in okr:
        f1 = [b for b in r["boats"] if b.get("finish") == 1][0]
        for b in r["boats"]:
            if b is not f1:
                zb[b["course"] - 1] += [1, b.get("finish") in (2, 3)]
    zp23 = zb[:, 1] / np.maximum(zb[:, 0], 1)
    zacc = defaultdict(lambda: [0.0, 0])
    rows = []
    for r in races:
        d = dt.datetime.strptime(r["date"], "%Y%m%d").date()
        boats = r["boats"]
        courses = [b.get("course") for b in boats]
        fin = {b["finish"]: b["waku"] - 1 for b in boats if b.get("finish")}
        ok = all(c in range(1, 7) for c in courses) and len(set(courses)) == 6 and 1 in fin
        exs = [b.get("exTime") for b in boats]
        ex_ok = all(e and 6.0 <= e <= 7.8 for e in exs)
        ex_mean = float(np.mean(exs)) if ex_ok else None
        x = np.zeros((6, len(FEATS)))
        fflag = np.zeros(6)
        sm = np.zeros((6, 4))  # 人気モデル用: skill, motor, ex, 級別
        cls = np.zeros(6, dtype=int)
        mkf = np.zeros((6, 3)); stz = np.zeros(6); crs = np.zeros(6, dtype=int)  # 人気モデル用: 勝率・モーター2連率・展示（世間が見る数字なので2連率のまま）
        of = ori_feats(ORI.get(r["date"], {}).get(f'{r["jcd"]:02d}-{r["rno"]:02d}'))
        for i, b in enumerate(boats):
            nat = b["natWin"] or 5.0
            loc = b["locWin"] if b["locWin"] and b["locWin"] > 0 else nat
            m2 = b["motor2"] if b["motor2"] and b["motor2"] > 0 else 33.0
            b2 = b["boat2"] if b["boat2"] and b["boat2"] > 0 else 33.0
            hist = st_hist[b["toban"]][-30:]
            st_avg = (sum(hist) + 0.16 * 3) / (len(hist) + 3)
            ex = -np.clip((exs[i] - ex_mean) / 0.07, -2.5, 2.5) if ex_ok else 0.0
            c = b.get("course") if b.get("course") in range(1, 7) else b["waku"]
            mk = motor_key(renew, r["jcd"], r["date"], b["motor"])
            fs, rs_ = mh[mk]
            v = {"skill": (nat - 5.5) / 1.2, "local": (loc - nat) / 1.2, "motor": (m2 - 35) / 8, "boat": (b2 - 33) / 6,
                 "st": -np.clip((st_avg - 0.16) / 0.025, -2.5, 2.5), "ex": ex,
                 "cwin": cwin_of(cw[b["toban"]][c - 1], c), "form": form_of(recent[b["toban"]][-10:], 3),
                 "mform": form_of(motorf[f'{r["jcd"]}-{b["motor"]}'][-20:], 5),
                 "mfoot": sum(fs) / (len(fs) + MF_K), "madj": sum(rs_) / (len(rs_) + MA_K) / 2,
                 "olap": of[b["waku"] - 1][0], "oturn": of[b["waku"] - 1][1], "ostr": of[b["waku"] - 1][2],
                 "nozoki": 0.0, "wall": 0.0, "dash": 0.0, "asa": 0.0, "amk": 0.0, "ams": 0.0, "av1": 0.0}
            x[i] = [v[k] for k in FEATS]
            stz[i] = v["st"]; crs[i] = c - 1
            mkf[i] = [v["skill"], v["motor"], v["ex"]]
            fflag[i] = 1.0 if any((d - fd).days <= 180 for fd in f_dates[b["toban"]]) else 0.0
            cls[i] = CLS.index(b["cls"]) if b["cls"] in CLS else 2
        if len(set(crs.tolist())) == 6:
            byc = np.zeros(6); byc[crs] = stz
            for i in range(6):
                c = crs[i]
                if "nozoki" in FEATS:
                    x[i, FEATS.index("nozoki")] = np.clip(stz[i] - byc[c - 1], -4, 4) if c > 0 else 0.0
                    x[i, FEATS.index("wall")] = np.clip(stz[i] - byc[1], -4, 4) if c == 0 else 0.0
                    x[i, FEATS.index("dash")] = np.clip(stz[i] - byc[:3].mean(), -4, 4) if c >= 3 else 0.0
        if ok and "asa" in FEATS:
            c1b = [b for b in boats if b["course"] == 1][0]; l = alose[c1b["toban"]]
            V = np.log(np.clip([arate(l[1 + j], l[0], aPL[j]) for j in range(3)], 1e-4, 1) / np.clip(aPL, 1e-4, 1))
            for i, b in enumerate(boats):
                c = b["course"]
                if c == 1:
                    x[i, FEATS.index("av1")] = np.clip(-V.mean(), -6, 6)
                else:
                    w_ = awin[b["toban"]][c - 1]
                    A = np.log(np.clip([arate(w_[1 + j], w_[0], aPW[c - 1][j]) for j in range(3)], 1e-4, 1) / aPW[c - 1])
                    for j, k in enumerate(("asa", "amk", "ams")):
                        x[i, FEATS.index(k)] = np.clip(A[j] + V[j], -6, 6)
            wc = [b["course"] for b in boats if b.get("finish") == 1][0]; km = r.get("kimarite")
            l[0] += 1
            if wc != 1:
                l[1 + KM3.index(km) if km in KM3 else 4] += 1
            for b in boats:
                w_ = awin[b["toban"]][b["course"] - 1]; w_[0] += 1
                if b.get("finish") == 1 and km in KM3:
                    w_[1 + KM3.index(km)] += 1
        zan = np.array([zacc[b["toban"]][0] / (zacc[b["toban"]][1] + ZAN_K) * 3 for b in boats])
        if ok:
            for b in boats:
                if b.get("finish") != 1:
                    a_ = zacc[b["toban"]]; a_[0] += (b.get("finish") in (2, 3)) - zp23[b["course"] - 1]; a_[1] += 1
            rows.append({
                "zan": zan,
                "date": r["date"], "jcd": r["jcd"], "course": np.array(courses) - 1, "x": x, "f": fflag, "cls": cls, "mk": mkf,
                "w1": fin[1], "w2": fin.get(2, -1), "w3": fin.get(3, -1),
                "payout": (r.get("tri") or {}).get("payout"), "order": (r.get("tri") or {}).get("order"),
            })
        # 結果を履歴に反映（このレースの後に使う）
        has = [ex_ok] + [bool(np.any(of[:, g] != 0)) for g in range(3)]
        for i, b in enumerate(boats):
            comp = ([-np.clip((exs[i] - ex_mean) / 0.07, -2.5, 2.5)] if ex_ok else []) + [of[i, g] for g in range(3) if has[g + 1]]
            mk = motor_key(renew, r["jcd"], r["date"], b["motor"])
            if comp:
                mh[mk][0].append(float(np.mean(comp)))
            c0 = b.get("course") if b.get("course") in range(1, 7) else b["waku"]
            if b.get("finish") in PTS and b.get("natWin"):
                mh[mk][1].append(PTS[b["finish"]] - b["natWin"] - CADJ[c0])
        for b in boats:
            if b.get("flying"):
                f_dates[b["toban"]].append(d)
            elif b.get("st") is not None and 0 <= b["st"] <= 0.6:
                st_hist[b["toban"]].append(b["st"])
                if b.get("course") in range(1, 7):
                    stc[b["toban"]][b["course"] - 1] = (stc[b["toban"]][b["course"] - 1] + [b["st"]])[-15:]
                    k = f'{r["jcd"]}-{b["course"]}'
                    stv[k] = (stv[k] + [b["st"]])[-300:]
            c, fin_b = b.get("course"), b.get("finish")
            if c in range(1, 7) and (fin_b or str(b.get("code", "")).startswith(("F", "L", "S"))):
                cw[b["toban"]][c - 1][1] += 1
                if fin_b == 1:
                    cw[b["toban"]][c - 1][0] += 1
            if fin_b:
                recent[b["toban"]] = (recent[b["toban"]] + [fin_b])[-10:]
                k = f'{r["jcd"]}-{b["motor"]}'
                motorf[k] = (motorf[k] + [fin_b])[-20:]
    # アプリ用：今の交換期間のモーターだけ（"jcd-motor" -> [mfoot, madj, 走数]）
    mt = {}
    for k, (fs, rs_) in mh.items():
        j, per, m = k.split("-")
        cur = renew.get(int(j), [])
        if per == (cur[-1] if cur else "0"):
            mt[f"{j}-{m}"] = [round(sum(fs) / (len(fs) + MF_K), 3), round(sum(rs_) / (len(rs_) + MA_K) / 2, 3), len(rs_)]
    STATE["zn"] = {t: round(a_[0] / (a_[1] + ZAN_K) * 3, 3) for t, a_ in zacc.items()}
    STATE.update(cw=cw, recent=recent, motorf=motorf, st=st_hist, stc=stc, stv=stv, mt=mt, renew=renew)
    return rows


def stack(rows):
    return {
        "venue": np.array([r["jcd"] - 1 for r in rows]),
        "course": np.stack([r["course"] for r in rows]),
        "x": np.stack([r["x"] for r in rows]),
        "f": np.stack([r["f"] for r in rows]),
        "cls": np.stack([r["cls"] for r in rows]),
        "mk": np.stack([r["mk"] for r in rows]),
        "zan": np.stack([r["zan"] for r in rows]),
        "w1": np.array([r["w1"] for r in rows]),
        "w2": np.array([r["w2"] for r in rows]),
        "w3": np.array([r["w3"] for r in rows]),
        "payout": np.array([r["payout"] or np.nan for r in rows], dtype=float),
        "order": [r["order"] for r in rows],
    }


def logsumexp(a, axis):
    m = a.max(axis=axis, keepdims=True)
    return (m + np.log(np.exp(a - m).sum(axis=axis, keepdims=True))).squeeze(axis)


# ---------------------------------------------------------------- 1着モデル
def fit_win(D, lam=2.0):
    R, F = len(D["venue"]), len(FEATS)
    oh = np.zeros((R, 6)); oh[np.arange(R), D["w1"]] = 1

    def f(p):
        a = p[:144].reshape(24, 6); beta = p[144:144 + F]; g = p[-1]
        L = a[D["venue"][:, None], D["course"]] + D["x"] @ beta + g * D["f"]
        lse = logsumexp(L, 1)
        nll = -(L[np.arange(R), D["w1"]] - lse).sum()
        d = a - a.mean(0)
        nll += lam * (d ** 2).sum() + 1e-4 * (a ** 2).sum()
        P = np.exp(L - lse[:, None]); G = P - oh
        ga = np.zeros((24, 6)); np.add.at(ga, (D["venue"][:, None], D["course"]), G)
        ga += 2 * lam * d + 2e-4 * a
        gb = np.einsum("rk,rkf->f", G, D["x"]); gg = (G * D["f"]).sum()
        return nll, np.concatenate([ga.ravel(), gb, [gg]])

    p0 = np.zeros(144 + F + 1); p0[:144] = np.tile(np.log([.55, .14, .12, .11, .06, .02]), 24)
    res = minimize(f, p0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    a = res.x[:144].reshape(24, 6); beta = res.x[144:144 + F]; g = res.x[-1]
    return a, beta, g


# ---------------------------------------------------------------- 2・3着モデル
def fit_place(D, beta):
    s = D["x"] @ beta
    m = D["w2"] >= 0
    m3 = D["w3"] >= 0
    R = len(s)

    def nll(p):
        lp = np.concatenate([[0.0], p[:5]]); k = p[5]
        L = lp[D["course"]] + k * s
        tot = 0.0
        L2 = L.copy(); L2[np.arange(R), D["w1"]] = -np.inf
        tot -= (L2[np.arange(R), np.maximum(D["w2"], 0)] - logsumexp(L2, 1))[m].sum()
        L3 = L2.copy(); L3[np.arange(R), np.maximum(D["w2"], 0)] = -np.inf
        tot -= (L3[np.arange(R), np.maximum(D["w3"], 0)] - logsumexp(L3, 1))[m & m3].sum()
        return tot

    res = minimize(nll, np.concatenate([np.log([.21, .19, .18, .13, .09]) - np.log(.2), [0.6]]), method="L-BFGS-B")
    lp = np.concatenate([[0.0], res.x[:5]])
    place = np.exp(lp) / np.exp(lp).sum()
    return place, res.x[5]


# ---------------------------------------------------------------- 3連単の確率
def tri_probs(Lw, Lp):
    """Lw, Lp: (R,6) の対数の強さ → (R,120) の確率"""
    w = np.exp(Lw - Lw.max(1, keepdims=True)); w /= w.sum(1, keepdims=True)
    p = np.exp(Lp - Lp.max(1, keepdims=True)); P = p.sum(1, keepdims=True)
    a, b, c = PERMS[:, 0], PERMS[:, 1], PERMS[:, 2]
    return w[:, a] * p[:, b] / (P - p[:, a]) * p[:, c] / (P - p[:, a] - p[:, b])


# ---------------------------------------------------------------- 展開（11/20 追加）：2着・3着は1着の艇のコースで変わる
# 2着の強さに B2[1着のコース, 候補のコース]、3着に B3[1着のコース, 候補]＋C3[2着のコース, 候補] を足す
def fit_tenkai(D, Lp):
    """11/20 追加：2着・3着の強さに 選手の残り方のクセ×kz を足す（テストで3連単損失3.7890→3.7874）"""
    R = len(D["w1"]); C = D["course"]; w1, w2, w3 = D["w1"], D["w2"], D["w3"]
    m = (w2 >= 0) & (w3 >= 0); idx = np.where(m)[0]; Rm = len(idx)
    c1 = C[idx, w1[idx]]; c2 = C[idx, w2[idx]]; Ci = C[idx]; Lpi = Lp[idx]; Zi = D["zan"][idx]
    def nll(p):
        B2 = p[:36].reshape(6, 6); B3 = p[36:72].reshape(6, 6); C3 = p[72:108].reshape(6, 6)
        L2 = Lpi + p[108] * Zi + B2[c1[:, None], Ci]; L2[np.arange(Rm), w1[idx]] = -np.inf
        L3 = Lpi + p[109] * Zi + B3[c1[:, None], Ci] + C3[c2[:, None], Ci]
        L3[np.arange(Rm), w1[idx]] = -np.inf; L3[np.arange(Rm), w2[idx]] = -np.inf
        return -((L2[np.arange(Rm), w2[idx]] - logsumexp(L2, 1)) + (L3[np.arange(Rm), w3[idx]] - logsumexp(L3, 1))).mean() + 1e-3 * (p[:108] ** 2).sum()
    p = minimize(nll, np.zeros(110), method="L-BFGS-B").x
    return p[:36].reshape(6, 6), p[36:72].reshape(6, 6), p[72:108].reshape(6, 6), p[108:110]


def tri_probs_t(Lw, Lp, C, TK, Z):
    """展開つきの3連単の確率。C: (R,6) 枠→コース(0-5)、Z: (R,6) 残り方のクセ"""
    B2, B3, C3, kz = TK
    W = np.exp(Lw - logsumexp(Lw, 1)[:, None]); R = len(Lw)
    out = np.zeros((R, 120))
    for n, (i, j, k) in enumerate(PERMS):
        ci, cj = C[:, i], C[:, j]
        L2 = Lp + kz[0] * Z + B2[ci[:, None], C]; L2[:, i] = -np.inf
        L3 = Lp + kz[1] * Z + B3[ci[:, None], C] + C3[cj[:, None], C]; L3[:, i] = -np.inf; L3[:, j] = -np.inf
        out[:, n] = W[:, i] * np.exp(L2[:, j] - logsumexp(L2, 1)) * np.exp(L3[:, k] - logsumexp(L3, 1))
    return out


def order_index(orders):
    lut = {f"{i + 1}-{j + 1}-{k + 1}": n for n, (i, j, k) in enumerate(PERMS)}
    return np.array([lut.get(o, -1) for o in orders])


# ---------------------------------------------------------------- 人気モデル（実際の払戻から）
def market_logits(D, lnbase, lnplace, th):
    inner, kNat, kMot, kEx, cA1, cA2, cB2, kPl = th
    clsb = np.array([cA1, cA2, 0.0, cB2])[D["cls"]]
    sm = kNat * D["mk"][:, :, 0] + kMot * D["mk"][:, :, 1] + kEx * D["mk"][:, :, 2] + clsb  # 11/20 列の取り違えを修正
    Lw = lnbase[D["venue"][:, None], D["course"]] + inner * (D["course"] == 0) + sm
    Lp = lnplace[D["course"]] + kPl * sm
    return Lw, Lp


def fit_market(D, lnbase, lnplace):
    oi = order_index(D["order"])
    m = (oi >= 0) & np.isfinite(D["payout"]) & (D["payout"] > 0)
    Dm = {k: (v[m] if isinstance(v, np.ndarray) else [v[i] for i in np.where(m)[0]]) for k, v in D.items()}
    oi = oi[m]; y = np.log(Dm["payout"] / 100.0)
    a, b, c = PERMS[oi, 0], PERMS[oi, 1], PERMS[oi, 2]
    idx = np.arange(len(oi))

    def resid(th):
        Lw, Lp = market_logits(Dm, lnbase, lnplace, th[:-1])
        w = np.exp(Lw - Lw.max(1, keepdims=True)); w /= w.sum(1, keepdims=True)
        p = np.exp(Lp - Lp.max(1, keepdims=True)); P = p.sum(1)
        pr = w[idx, a] * p[idx, b] / (P - p[idx, a]) * p[idx, c] / (P - p[idx, a] - p[idx, b])
        return y - (np.log(PAYBACK) + th[-1] - np.log(pr))

    res = least_squares(resid, np.array([0.15, 0.9, 0.2, 0.3, 0.25, 0.1, -0.5, 0.7, 0.0]), loss="soft_l1")
    return res.x[:-1], float(res.x[-1])


# ---------------------------------------------------------------- 買い目の選び方と検証
def picks(pa, pm, ana_rule):
    """1レース分。pa, pm: (120,) → 本線と穴のインデックス"""
    order = np.argsort(-pa)
    hon, cum = [], 0.0
    for i in order:
        if len(hon) >= 6 or (len(hon) >= 3 and cum >= 0.35):
            break
        hon.append(i); cum += pa[i]
    odds = np.maximum(1.0, PAYBACK / pm)
    ratio = pa / pm
    cand = [i for i in range(120) if i not in hon and pa[i] >= ana_rule["minP"] and odds[i] >= ana_rule["minOdds"]
            and ratio[i] >= ana_rule["minRatio"] and odds[i] <= ana_rule.get("maxOdds", 1e9)]
    cand.sort(key=lambda i: -pa[i] * odds[i])
    return hon, cand[: ana_rule["max"]]


def backtest(PA, PM, D, rule):
    oi = order_index(D["order"]); pay = D["payout"]
    out = {"hon": [0, 0, 0.0, 0], "ana": [0, 0, 0.0, 0]}  # レース数, 的中, 払戻, 点数
    for r in range(len(oi)):
        if oi[r] < 0 or not np.isfinite(pay[r]):
            continue
        hon, ana = picks(PA[r], PM[r], rule)
        for key, sel in (("hon", hon), ("ana", ana)):
            if not sel:
                continue
            o = out[key]; o[0] += 1; o[3] += len(sel)
            if oi[r] in sel:
                o[1] += 1; o[2] += pay[r]
    res = {}
    for key, (n, hit, ret, pts) in out.items():
        res[key] = {"races": n, "hits": hit, "hitRate": hit / n if n else 0, "points": pts,
                    "roi": ret / (pts * 100) if pts else 0}
    return res


def subset(D, m):
    return {k: (v[m] if isinstance(v, np.ndarray) else [v[i] for i in np.where(m)[0]]) for k, v in D.items()}


def kimarite_year(races):
    """選手ごとの直近1年の決まり手。[2〜6コースの出走, 差し, まくり, まくり差し, 1コースの出走, 逃げ]（1着になったときの決まり手）"""
    last = max(r["date"] for r in races)
    since = (dt.datetime.strptime(last, "%Y%m%d") - dt.timedelta(days=365)).strftime("%Y%m%d")
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    idx = {"差し": 1, "まくり": 2, "まくり差し": 3}
    for r in races:
        if r["date"] < since:
            continue
        km = r.get("kimarite")
        for b in r["boats"]:
            c = b.get("course")
            if c not in range(1, 7) or b.get("code") in ("欠", "K0", "K1"):
                continue
            o = out[b["toban"]]
            if c == 1:
                o[4] += 1
                if b.get("finish") == 1 and km == "逃げ":
                    o[5] += 1
            else:
                o[0] += 1
                if b.get("finish") == 1 and km in idx:
                    o[idx[km]] += 1
    return out


def course_year(races):
    """選手×コースの直近1年。[出走, 1着, 2連対, 3連対, ST合計, ST数, ST順合計, 差し, まくり, まくり差し, 逃げ]
    ＋全体のコース別平均（cbase）と、今節（同じ場で続けて走っている日）のSTとST順"""
    last = max(r["date"] for r in races)
    since = (dt.datetime.strptime(last, "%Y%m%d") - dt.timedelta(days=365)).strftime("%Y%m%d")
    out = defaultdict(lambda: [[0] * 11 for _ in range(6)])
    base = [[0] * 7 for _ in range(6)]  # 出走, 1着, 2連, 3連, ST合計, ST数, ST順合計
    kon = {}  # toban -> {"jcd", "dates":set, "st":[], "rk":[]}（新しい日から見て同じ場が続く間）
    kidx = {"差し": 7, "まくり": 8, "まくり差し": 9, "逃げ": 10}
    # 1コースで負けたとき：勝った艇のコース（2〜6）×決まり手（差し・まくり・まくり差し）の回数
    lidx = {"差し": 0, "まくり": 1, "まくり差し": 2}
    l1 = defaultdict(lambda: [[0] * 3 for _ in range(5)])
    l1base = [[0] * 3 for _ in range(5)]
    for r in races:
        if r["date"] < since:
            continue
        km = r.get("kimarite")
        if km in lidx:
            win = next((b for b in r["boats"] if b.get("finish") == 1), None)
            one = next((b for b in r["boats"] if b.get("course") == 1 and b.get("code") not in ("欠", "K0", "K1")), None)
            if win and one and win is not one and win.get("course") in range(2, 7):
                l1[one["toban"]][win["course"] - 2][lidx[km]] += 1
                l1base[win["course"] - 2][lidx[km]] += 1
        sts = sorted(b["st"] for b in r["boats"] if b.get("st") is not None and 0 <= b["st"] <= 0.6 and not b.get("flying"))
        for b in r["boats"]:
            c = b.get("course")
            if c not in range(1, 7) or b.get("code") in ("欠", "K0", "K1"):
                continue
            o, g = out[b["toban"]][c - 1], base[c - 1]
            f = b.get("finish")
            for a in (o, g):
                a[0] += 1
                if f == 1: a[1] += 1
                if f and f <= 2: a[2] += 1
                if f and f <= 3: a[3] += 1
            st = b.get("st")
            if st is not None and 0 <= st <= 0.6 and not b.get("flying"):
                rk = 1 + sum(1 for x in sts if x < st)
                for a in (o, g):
                    a[4] += st; a[5] += 1; a[6] += rk
                # 今節
                k = kon.get(b["toban"])
                if k is None or k["jcd"] != r["jcd"] or (dt.datetime.strptime(r["date"], "%Y%m%d") - dt.datetime.strptime(max(k["dates"]), "%Y%m%d")).days > 2:
                    k = kon[b["toban"]] = {"jcd": r["jcd"], "dates": set(), "st": [], "rk": []}
                k["dates"].add(r["date"]); k["st"].append(st); k["rk"].append(rk)
            if f == 1 and km in kidx:
                o[kidx[km]] += 1
    cbase = [{"n": g[0], "win": g[1] / max(g[0], 1), "top2": g[2] / max(g[0], 1), "top3": g[3] / max(g[0], 1),
              "st": g[4] / max(g[5], 1), "rk": g[6] / max(g[5], 1)} for g in base]
    pl = {t: [[round(x, 2) if isinstance(x, float) else x for x in row] for row in v] for t, v in out.items()}
    kn = {t: {"jcd": k["jcd"], "last": max(k["dates"]), "days": len(k["dates"]),
              "st": round(sum(k["st"]) / len(k["st"]), 3), "rk": round(sum(k["rk"]) / len(k["rk"]), 2), "n": len(k["st"])}
          for t, k in kon.items()}
    return pl, cbase, kn, dict(l1), l1base


def kimarite_stats(races):
    """1着艇のコース別に決まり手を数える（全国と場ごと）。展開予想に使う"""
    allc = defaultdict(lambda: defaultdict(int)); ven = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in races:
        km = r.get("kimarite")
        w = next((b for b in r["boats"] if b.get("finish") == 1), None)
        if not km or not w or w.get("course") not in range(1, 7):
            continue
        allc[str(w["course"])][km] += 1
        ven[str(r["jcd"])][str(w["course"])][km] += 1
    return {"all": {c: dict(v) for c, v in allc.items()},
            "v": {j: {c: dict(v) for c, v in cs.items()} for j, cs in ven.items()}}


# ---------------------------------------------------------------- 1コースが負ける確率と、負けるときの決まり手（11/20 殿の依頼で追加）
KM3 = ["差し", "まくり", "まくり差し"]
INK = 15  # 少ない選手は全体の割合に寄せる強さ


def _ok_races(races):
    out = []
    for r in races:
        bs = r["boats"]; cs = [b.get("course") for b in bs]; fin = {b["finish"] for b in bs if b.get("finish")}
        if all(c in range(1, 7) for c in cs) and len(set(cs)) == 6 and 1 in fin:
            out.append(r)
    return out


def slit_arrays(D):
    """決まり手用（11/20）：コース順の 平均STの速さ(z) と 足（展示＋オリ展の生の値の和）"""
    X = D["x"]; fi = FEATS.index; R = len(X)
    stz = X[:, :, fi("st")]; ft = X[:, :, fi("ex")] + X[:, :, fi("olap")] + X[:, :, fi("oturn")] + X[:, :, fi("ostr")]
    oc = np.argsort(D["course"], 1); ar = np.arange(R)[:, None]
    return stz[ar, oc], ft[ar, oc]


def inkm_features(races, P, SZ=None, FT=None):
    """各レースについて、そのレースより前の結果だけから：1コースの艇の負け方の率、2〜6コースの艇の勝ち方の率。
    P は rows（枠順）の1着確率。戻り値は学習用の特徴と、アプリ用の選手ごとの通算"""
    ok = _ok_races(races)
    tot = np.zeros(5); totw = np.zeros((6, 4))
    for r in ok:
        km = r.get("kimarite"); bs = sorted(r["boats"], key=lambda b: b["course"])
        wc = [b["course"] for b in bs if b.get("finish") == 1][0]
        tot[0] += 1
        if wc != 1:
            tot[1 + KM3.index(km) if km in KM3 else 4] += 1
        for b in bs:
            totw[b["course"] - 1][0] += 1
            if b.get("finish") == 1 and km in KM3:
                totw[b["course"] - 1][1 + KM3.index(km)] += 1
    PL = tot[1:4] / tot[0]; PW = totw[:, 1:] / np.maximum(totw[:, :1], 1)
    lose = defaultdict(lambda: np.zeros(5)); win = defaultdict(lambda: np.zeros((6, 4)))
    F1, FK, Y1, YK = [], [], [], []
    rate = lambda a, n, p: (a + INK * p) / (n + INK)
    for i, r in enumerate(ok):
        bs = sorted(r["boats"], key=lambda b: b["course"])
        l = lose[bs[0]["toban"]]
        v = np.log(np.clip([rate(l[1 + j], l[0], PL[j]) for j in range(3)], 1e-4, 1) / PL)
        att = np.array([[rate(win[b["toban"]][b["course"] - 1][1 + j], win[b["toban"]][b["course"] - 1][0], PW[b["course"] - 1][j])
                         for j in range(3)] for b in bs[1:]])
        a = np.log(np.clip(att, 1e-4, 1) / np.clip(PW[1:], 1e-4, 1))
        pr = np.array([P[i][b["waku"] - 1] for b in bs])
        F1.append(inkm_vec(pr[0], v, a))
        FK.append(km_mat(pr, v, a, PW, None if SZ is None else SZ[i], None if FT is None else FT[i]))
        wc = [b["course"] for b in bs if b.get("finish") == 1][0]; km = r.get("kimarite")
        Y1.append(0 if wc == 1 else 1)
        YK.append(-1 if wc == 1 else ((wc - 2) * 3 + KM3.index(km) if km in KM3 else 15))
        l[0] += 1
        if wc != 1:
            l[1 + KM3.index(km) if km in KM3 else 4] += 1
        for b in bs:
            w_ = win[b["toban"]][b["course"] - 1]; w_[0] += 1
            if b.get("finish") == 1 and km in KM3:
                w_[1 + KM3.index(km)] += 1
    per = {"lk": {t: v.astype(int).tolist() for t, v in lose.items()}, "wk": {t: v[1:].astype(int).tolist() for t, v in win.items()}}
    return np.array(F1), np.array(FK), np.array(Y1), np.array(YK), PL, PW, per


def inkm_vec(p1, v, a):
    p1 = float(np.clip(p1, 1e-4, 1 - 1e-4))
    f = [1.0, np.log(p1 / (1 - p1)), *v, *a.max(0), *np.log(np.exp(a).mean(0))]
    return np.clip(f, -8, 8)


KM_SLIT = 24  # 決まり手×(2〜3コース / 4〜6コース)ごとに [自分のSTの速さ, すぐ内のSTの速さ, 内の最速, 足]


def km_mat(pr, v, a, PW, sz=None, ft=None):
    """11/20：STの並び（とくに すぐ内の艇のST＝壁）と足を足した。テストで決まり手損失2.2106→2.2018、
    3コースの壁が速いレースでの4コースまくりの言いすぎ 4.0%→3.1%（実際2.2%）"""
    pn = pr[1:] / max(pr[1:].sum(), 1e-9)
    rows = []
    for c in range(2, 7):
        for j in range(3):
            e = np.zeros(KM_SLIT)
            if sz is not None:
                k = c - 1; g = 0 if c <= 3 else 1
                e[g * 12 + j * 4:g * 12 + j * 4 + 4] = [sz[k], sz[k - 1], sz[:k].max(), np.clip(ft[k] - ft.mean(), -4, 4)]
            rows.append([np.log(pn[c - 2] + 1e-9), np.log(PW[c - 1][j] / max(PW[c - 1].sum(), 1e-9)), a[c - 2][j], v[j], *e])
    rows.append([0.0] * (4 + KM_SLIT))
    return np.clip(np.array(rows), -12, 8)


def fit_inkm(F1, FK, Y1, YK, m):
    def nll1(t):
        z = F1[m] @ t; return np.mean(np.logaddexp(0, z) - Y1[m] * z)
    t1 = minimize(nll1, np.zeros(F1.shape[1]), method="L-BFGS-B").x
    mk = m & (YK >= 0)
    nf = FK.shape[2]
    def nllk(t):
        u = FK[mk] @ t[:nf]; u[:, -1] = t[nf]; u = u - u.max(1, keepdims=True)
        lp = u - np.log(np.exp(u).sum(1, keepdims=True)); return -lp[np.arange(mk.sum()), YK[mk]].mean() + 1e-4 * (t[4:nf] ** 2).sum()
    tk = minimize(nllk, np.concatenate([[1.0, 1.0, 0.0, 0.0], np.zeros(nf - 4), [-2.0]]), method="L-BFGS-B").x
    return t1, tk


def eval_inkm(F1, FK, Y1, YK, t1, tk, m):
    p = 1 / (1 + np.exp(-(F1[m] @ t1))); y = Y1[m]; p = np.clip(p, 1e-6, 1 - 1e-6)
    ll1 = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    p0 = 1 - np.clip(1 / (1 + np.exp(-F1[m][:, 1])), 1e-6, 1 - 1e-6)
    ll0 = float(-np.mean(y * np.log(p0) + (1 - y) * np.log(1 - p0)))
    mk = m & (YK >= 0)
    nf = FK.shape[2]
    u = FK[mk] @ tk[:nf]; u[:, -1] = tk[nf]; u = u - u.max(1, keepdims=True)
    lp = u - np.log(np.exp(u).sum(1, keepdims=True))
    return {"loseLogLoss": ll1, "loseLogLossAI": ll0, "kmLogLoss": float(-lp[np.arange(mk.sum()), YK[mk]].mean()),
            "kmTop1": float((lp.argmax(1) == YK[mk]).mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    root = Path(a.data)
    races = load(root)
    rows = build(races)
    print(f"レース {len(races)} / 学習に使える {len(rows)}")
    if len(rows) < 3000:
        print("データが少ないため学習を見送り")
        return
    D = stack(rows)
    dates = np.array([r["date"] for r in rows])
    ud = np.unique(dates)
    cut_val, cut_test = ud[int(len(ud) * 0.70)], ud[int(len(ud) * 0.85)]
    tr, va, te = dates < cut_val, (dates >= cut_val) & (dates < cut_test), dates >= cut_test

    # 1. 学習（学習期間のみ）→ 検証
    def fit_all(m):
        Dt = subset(D, m)
        A, beta, g = fit_win(Dt)
        place, kPl = fit_place(Dt, beta)
        lnbase = A - logsumexp(A, 1)[:, None]
        lnplace = np.log(place)
        th, c0 = fit_market(Dt, lnbase, lnplace)
        s_ = Dt["x"] @ beta
        TK = fit_tenkai(Dt, lnplace[Dt["course"]] + kPl * s_)
        return dict(A=A, beta=beta, g=g, place=place, kPl=kPl, lnbase=lnbase, lnplace=lnplace, th=th, c0=c0, TK=TK)

    def predict(M, Dx):
        s = Dx["x"] @ M["beta"]
        Lw = M["lnbase"][Dx["venue"][:, None], Dx["course"]] + s + M["g"] * Dx["f"]
        Lp = M["lnplace"][Dx["course"]] + M["kPl"] * s
        PA = tri_probs_t(Lw, Lp, Dx["course"], M["TK"], Dx["zan"])
        mw, mp = market_logits(Dx, M["lnbase"], M["lnplace"], M["th"])
        PM = tri_probs(mw, mp)
        win = np.exp(Lw - logsumexp(Lw, 1)[:, None])
        return PA, PM, win

    M = fit_all(tr)
    Dv, Dte = subset(D, va), subset(D, te)
    PAv, PMv, _ = predict(M, Dv)
    # 2. 穴の条件を検証期間で選ぶ（回収率最大、ただし対象レースが十分あるもの）
    best, best_rule = -1, None
    for minRatio in (1.1, 1.25, 1.5, 1.8, 2.2):
        for minOdds in (8, 15, 25, 40, 80):
            for minP, maxOdds in itertools.product((0.003, 0.007, 0.012), (40, 80, 150, 1e9)):
                if maxOdds <= minOdds:
                    continue
                rule = {"minRatio": minRatio, "minOdds": minOdds, "minP": minP, "maxOdds": maxOdds, "max": 5}
                bt = backtest(PAv, PMv, Dv, rule)["ana"]
                if bt["races"] >= max(200, 0.15 * len(PAv)) and bt["roi"] > best:
                    best, best_rule = bt["roi"], rule
    best_rule = best_rule or {"minRatio": 1.25, "minOdds": 20, "minP": 0.007, "max": 5}
    print("穴の条件", best_rule, f"検証期間の回収率 {best:.3f}")

    # 3. テスト期間（未使用）で最終評価
    PAt, PMt, wint = predict(M, Dte)
    bt = backtest(PAt, PMt, Dte, best_rule)
    top_hit = float((wint.argmax(1) == Dte["w1"]).mean())
    mt3 = (Dte["w2"] >= 0) & (Dte["w3"] >= 0)
    pid = {tuple(p): n for n, p in enumerate(PERMS.tolist())}
    tix = np.array([pid[(a, b, c)] for a, b, c in zip(Dte["w1"][mt3], Dte["w2"][mt3], Dte["w3"][mt3])])
    pt3 = PAt[mt3][np.arange(mt3.sum()), tix]
    tri_ll = float(-np.log(np.maximum(pt3, 1e-12)).mean()); tri_top = float((PAt[mt3].argmax(1) == tix).mean())
    in1 = float((Dte["course"][np.arange(len(Dte["w1"])), Dte["w1"]] == 0).mean())
    ll_model = float(-np.log(wint[np.arange(len(Dte["w1"])), Dte["w1"]]).mean())
    base_only = np.exp(M["lnbase"][Dte["venue"][:, None], Dte["course"]])
    ll_base = float(-np.log(base_only[np.arange(len(Dte["w1"])), Dte["w1"]]).mean())

    # 3b. 1コースが負ける確率・決まり手（学習期間のモデルの1着確率から、学習＋検証で重みを決め、テストで採点）
    _, _, win_all = predict(M, D)
    F1, FK, Y1, YK, PL, PW, _ = inkm_features(races, win_all, *slit_arrays(D))
    t1, tk = fit_inkm(F1, FK, Y1, YK, ~te)
    ink_test = eval_inkm(F1, FK, Y1, YK, t1, tk, te)
    print("1コースが負ける・決まり手（テスト）", ink_test)

    # 4. 本番用は全期間で学習し直す
    Mall = fit_all(np.ones(len(dates), dtype=bool))
    _, _, win_full = predict(Mall, D)
    F1, FK, Y1, YK, PL, PW, INKPER = inkm_features(races, win_full, *slit_arrays(D))
    t1, tk = fit_inkm(F1, FK, Y1, YK, np.ones(len(Y1), dtype=bool))
    base = np.exp(Mall["lnbase"])
    w = dict(zip(FEATS, Mall["beta"].round(4).tolist()))
    n_ori = sum(len(v) for v in ORI.values())
    if n_ori < 3000:  # オリジナル展示がまだ少ないうちは重みを出さない（アプリは仮の重みを使う）
        for k in ("olap", "oturn", "ostr"):
            w.pop(k, None)
    print(f"オリジナル展示つきのレース {n_ori}")
    th = Mall["th"].round(4).tolist()
    model = {
        "version": 2,
        "trainedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "note": "過去データから自動で学習した重み（train.py）",
        "weights": {**w, "fPen": round(-float(Mall["g"]), 4), "kWin": 1.0, "kPlace": round(float(Mall["kPl"]), 4)},
        "baseDefault": (np.exp(Mall["lnbase"]).mean(0) / np.exp(Mall["lnbase"]).mean(0).sum()).round(4).tolist(),
        "baseVenue": {str(v + 1): base[v].round(4).tolist() for v in range(24)},
        "place": Mall["place"].round(4).tolist(),
        "market": {"inner": th[0], "kNat": th[1], "kMotor": th[2], "kEx": th[3],
                   "cls": {"A1": th[4], "A2": th[5], "B1": 0.0, "B2": th[6]}, "kPlace": th[7], "c0": round(Mall["c0"], 4)},
        "ana": best_rule,
        "tenkai": {"B2": Mall["TK"][0].round(4).tolist(), "B3": Mall["TK"][1].round(4).tolist(), "C3": Mall["TK"][2].round(4).tolist(),
                   "kz": Mall["TK"][3].round(4).tolist()},
        "inkm": {"PL": PL.round(5).tolist(), "PW": PW.round(5).tolist(), "K": INK, "lose": t1.round(4).tolist(), "km": tk.round(4).tolist()},
    }
    report = {
        "trainedAt": model["trainedAt"],
        "period": {"from": str(ud[0]), "to": str(ud[-1]), "testFrom": str(cut_test)},
        "races": {"all": len(rows), "test": int(te.sum())},
        "test": {
            "winTopHit": top_hit, "innerWinRate": in1,
            "logLoss": ll_model, "triLogLoss": tri_ll, "triTop1": tri_top, "logLossCourseOnly": ll_base,
            "honsen": bt["hon"], "ana": bt["ana"],
            "inkm": ink_test,
        },
        "anaRule": best_rule,
    }
    if best_rule.get("maxOdds", 0) >= 1e9:
        best_rule["maxOdds"] = 99999
    # アプリが同じ特徴量を計算できるよう、選手のコース別成績・直近着順とモーターの直近着順を書き出す
    # 選手名簿（番組表から取った名前・支部・級別・年齢の、いちばん新しいもの）
    prof = {}
    for r in races:
        for b in r["boats"]:
            if b.get("name"):
                prof[b["toban"]] = {"nm": b["name"], "br": b.get("branch", ""), "cl": b.get("cls", ""), "ag": b.get("age"), "d": r["date"]}
    kmy = kimarite_year(races)
    cy, cbase, kon, l1, l1base = course_year(races)
    stats = {"updated": model["trainedAt"],
             "p": {str(t): {"cw": v, "rf": STATE["recent"].get(t, []), "st": [round(x, 2) for x in STATE["st"].get(t, [])[-20:]],
                              "stc": [[round(x, 2) for x in l] for l in STATE["stc"][t]] if t in STATE["stc"] else None,
                              "kmy": kmy.get(t), "cy": cy.get(t), "lk": INKPER["lk"].get(t), "wk": INKPER["wk"].get(t), "zn": STATE["zn"].get(t), "kon": kon.get(t), "l1": l1.get(t), **prof.get(t, {})}
                   for t, v in STATE["cw"].items()},
             "km": kimarite_stats(races),
             "cbase": cbase,
             "l1base": l1base,
             "stv": {k: round(float(np.mean(v)), 4) for k, v in STATE["stv"].items() if len(v) >= 50},
             "m": {k: v for k, v in STATE["motorf"].items()},
             "mt": STATE["mt"], "renew": {str(k): v[-1] for k, v in STATE["renew"].items() if v}}
    (root / "stats.json").write_text(json.dumps(stats, separators=(",", ":")), encoding="utf-8")
    (root / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(model["weights"], ensure_ascii=False))


if __name__ == "__main__":
    main()
