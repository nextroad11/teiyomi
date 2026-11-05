import itertools, numpy as np, pandas as pd
import gama as G

SERIES = {
    'トトまる(8/27-9/1)': ['x_c.txt'],
    '観光協会長杯(9/4-9/8)': ['x_b.txt'],
    'ルーキー(9/13-9/18)': ['x_a.txt'],
    '晴れ風賞(9/29-10/4)': ['w_a.txt', 'w_b.txt'],
    '筆柿(10/7-10/10)': ['v_a.txt', 'v_b.txt'],
    '蒲郡大賞典(10/27-11/1)': None,
}

def load_all():
    out = {}
    for n, f in SERIES.items():
        if f is None:
            d, p = G.load('gama_build.csv')
            d = d[['race', '枠', '級別', '展示', '一周', 'まわり足', '直線', '着順', '進入', 'fin', 'win', 'top3'] +
                  [c for c in d.columns if c.startswith('補正') or c.startswith('Z')]]
        else:
            d, p = G.load_compact(f)
        d = d.copy(); d['節'] = n
        out[n] = (d, p)
    return out

def ranks(d, w):
    s = sum(d['Z' + k] * v for k, v in w.items() if v)
    return s.groupby(d.race).rank(ascending=False, method='first')

def stats(d, w):
    x = d.assign(rk=ranks(d, w)); x = x[x.fin.notna()]
    top = x[x.rk == 1]
    num = den = 0
    for c, g in x.groupby('進入'):
        u = g[g.rk <= 3].top3.mean(); l = g[g.rk > 3].top3.mean()
        if not (np.isnan(u) or np.isnan(l)):
            num += (u - l) * len(g); den += len(g)
    return dict(sep=num / den, top1_3=(top.fin <= 3).mean(), top1_1=(top.fin == 1).mean(),
                rk1=x[x.rk == 1].top3.mean(), rk6=x[x.rk == 6].top3.mean(),
                corr=np.corrcoef(x.rk, x.fin)[0, 1])

GRID_V = [0, 0.5, 1, 1.5, 2]
def grid():
    seen = set()
    for a, b, c, e in itertools.product(GRID_V, repeat=4):
        if a + b + c + e == 0: continue
        v = np.array([a, b, c, e]); v = tuple(np.round(v / v.max(), 3))
        if v in seen: continue
        seen.add(v)
        yield dict(zip(['一周', 'まわり足', '直線', '展示'], v))

def score(st):  # 主指標: 同コース内の分離 + 1位の3連対率
    return st['sep'] + 0.5 * st['top1_3']
