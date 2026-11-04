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

FEATS = ["skill", "local", "motor", "boat", "st", "ex"]
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
    return races


def build(races):
    """平均ST・F持ちを過去だけから計算し、特徴量の配列を作る"""
    st_hist = defaultdict(list)   # toban -> 直近のST
    f_dates = defaultdict(list)   # toban -> Fの日付
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
        for i, b in enumerate(boats):
            nat = b["natWin"] or 5.0
            loc = b["locWin"] if b["locWin"] and b["locWin"] > 0 else nat
            m2 = b["motor2"] if b["motor2"] and b["motor2"] > 0 else 33.0
            b2 = b["boat2"] if b["boat2"] and b["boat2"] > 0 else 33.0
            hist = st_hist[b["toban"]][-30:]
            st_avg = (sum(hist) + 0.16 * 3) / (len(hist) + 3)
            ex = -np.clip((exs[i] - ex_mean) / 0.07, -2.5, 2.5) if ex_ok else 0.0
            x[i] = [(nat - 5.5) / 1.2, (loc - nat) / 1.2, (m2 - 35) / 8, (b2 - 33) / 6,
                    -np.clip((st_avg - 0.16) / 0.025, -2.5, 2.5), ex]
            fflag[i] = 1.0 if any((d - fd).days <= 180 for fd in f_dates[b["toban"]]) else 0.0
            cls[i] = CLS.index(b["cls"]) if b["cls"] in CLS else 2
        if ok:
            rows.append({
                "date": r["date"], "jcd": r["jcd"], "course": np.array(courses) - 1, "x": x, "f": fflag, "cls": cls,
                "w1": fin[1], "w2": fin.get(2, -1), "w3": fin.get(3, -1),
                "payout": (r.get("tri") or {}).get("payout"), "order": (r.get("tri") or {}).get("order"),
            })
        # 結果を履歴に反映（このレースの後に使う）
        for b in boats:
            if b.get("flying"):
                f_dates[b["toban"]].append(d)
            elif b.get("st") is not None and 0 <= b["st"] <= 0.6:
                st_hist[b["toban"]].append(b["st"])
    return rows


def stack(rows):
    return {
        "venue": np.array([r["jcd"] - 1 for r in rows]),
        "course": np.stack([r["course"] for r in rows]),
        "x": np.stack([r["x"] for r in rows]),
        "f": np.stack([r["f"] for r in rows]),
        "cls": np.stack([r["cls"] for r in rows]),
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


def order_index(orders):
    lut = {f"{i + 1}-{j + 1}-{k + 1}": n for n, (i, j, k) in enumerate(PERMS)}
    return np.array([lut.get(o, -1) for o in orders])


# ---------------------------------------------------------------- 人気モデル（実際の払戻から）
def market_logits(D, lnbase, lnplace, th):
    inner, kNat, kMot, kEx, cA1, cA2, cB2, kPl = th
    clsb = np.array([cA1, cA2, 0.0, cB2])[D["cls"]]
    sm = kNat * D["x"][:, :, 0] + kMot * D["x"][:, :, 2] + kEx * D["x"][:, :, 5] + clsb
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
            and ratio[i] >= ana_rule["minRatio"]]
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
        return dict(A=A, beta=beta, g=g, place=place, kPl=kPl, lnbase=lnbase, lnplace=lnplace, th=th, c0=c0)

    def predict(M, Dx):
        s = Dx["x"] @ M["beta"]
        Lw = M["lnbase"][Dx["venue"][:, None], Dx["course"]] + s + M["g"] * Dx["f"]
        Lp = M["lnplace"][Dx["course"]] + M["kPl"] * s
        PA = tri_probs(Lw, Lp)
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
        for minOdds in (10, 20, 40, 80):
            for minP in (0.003, 0.007, 0.012):
                rule = {"minRatio": minRatio, "minOdds": minOdds, "minP": minP, "max": 5}
                bt = backtest(PAv, PMv, Dv, rule)["ana"]
                if bt["races"] >= max(200, 0.15 * len(PAv)) and bt["roi"] > best:
                    best, best_rule = bt["roi"], rule
    best_rule = best_rule or {"minRatio": 1.25, "minOdds": 20, "minP": 0.007, "max": 5}
    print("穴の条件", best_rule, f"検証期間の回収率 {best:.3f}")

    # 3. テスト期間（未使用）で最終評価
    PAt, PMt, wint = predict(M, Dte)
    bt = backtest(PAt, PMt, Dte, best_rule)
    top_hit = float((wint.argmax(1) == Dte["w1"]).mean())
    in1 = float((Dte["course"][np.arange(len(Dte["w1"])), Dte["w1"]] == 0).mean())
    ll_model = float(-np.log(wint[np.arange(len(Dte["w1"])), Dte["w1"]]).mean())
    base_only = np.exp(M["lnbase"][Dte["venue"][:, None], Dte["course"]])
    ll_base = float(-np.log(base_only[np.arange(len(Dte["w1"])), Dte["w1"]]).mean())

    # 4. 本番用は全期間で学習し直す
    Mall = fit_all(np.ones(len(dates), dtype=bool))
    base = np.exp(Mall["lnbase"])
    w = dict(zip(FEATS, Mall["beta"].round(4).tolist()))
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
    }
    report = {
        "trainedAt": model["trainedAt"],
        "period": {"from": str(ud[0]), "to": str(ud[-1]), "testFrom": str(cut_test)},
        "races": {"all": len(rows), "test": int(te.sum())},
        "test": {
            "winTopHit": top_hit, "innerWinRate": in1,
            "logLoss": ll_model, "logLossCourseOnly": ll_base,
            "honsen": bt["hon"], "ana": bt["ana"],
        },
        "anaRule": best_rule,
    }
    (root / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(model["weights"], ensure_ascii=False))


if __name__ == "__main__":
    main()
