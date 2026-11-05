import csv, sys, itertools
import numpy as np, pandas as pd
from scipy.optimize import minimize

CORR = {1: [0.4, 0.2, 0, 0.02], 2: [0.3, 0.1, 0, 0.01], 3: [0.2, 0, 0, 0],
        4: [0.1, -0.05, -0.01, -0.01], 5: [0.05, -0.1, -0.02, -0.02], 6: [0, -0.15, -0.02, -0.02]}
ITEMS = ['一周', 'まわり足', '直線', '展示']

def load(fn):
    rows, pay = [], {}
    for r in csv.reader(open(fn, encoding='utf-8')):
        if not r: continue
        if r[0] == 'P':
            pay[r[1]] = dict(tan_b=r[2], tan=int(r[3] or 0), t3=r[4], t3p=int(r[5] or 0), f3=r[6], f3p=int(r[7] or 0))
        else:
            rows.append(r[:16])
    d = pd.DataFrame(rows, columns=['race', '枠', '級別', '登番', '選手名', '体重', '調整', 'チルト', '展示', '一周', 'まわり足', '直線', '着順', 'タイム', '進入', 'ST'])
    for c in ['枠', '体重', '展示', '一周', 'まわり足', '直線', '進入']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d['fin'] = pd.to_numeric(d['着順'], errors='coerce')
    d['win'] = (d.fin == 1).astype(int); d['top3'] = (d.fin <= 3).astype(int)
    for i, c in enumerate(ITEMS):
        d['補正' + c] = d[c] + d['枠'].map(lambda w: CORR[int(w)][i])
    g = d.groupby('race')
    for c in ITEMS:
        x = '補正' + c
        d['Z' + c] = ((g[x].transform('mean') - d[x]) / g[x].transform('std')).fillna(0)
    return d, pay

def score(d, w):
    s = sum(d['Z' + k] * v for k, v in w.items())
    return s, s.groupby(d.race).rank(ascending=False, method='first')

def evaluate(d, pay, w, title):
    s, rk = score(d, w); d = d.assign(S=s, rk=rk); n = d.race.nunique()
    top = d[d.rk == 1]; win = (top.fin == 1).sum()
    p = [pay[r]['tan'] for r in top[top.fin == 1].race if r in pay]
    t3 = []; f3 = []
    for r, g in d.groupby('race'):
        if set(g[g.rk <= 3]['枠']) == set(g[g.fin <= 3]['枠']) and (g.fin <= 3).sum() == 3 and r in pay:
            t3.append(pay[r]['t3p']); f3.append(pay[r]['f3p'])
    byrk = d[d.fin.notna()].groupby('rk').top3.mean()
    inner = d[d.fin.notna()].assign(up=d.rk <= 3).pivot_table(index='進入', columns='up', values='top3', aggfunc='mean')
    print(f'== {title} {n}R  重み {w}')
    print(f'  本命1着 {win}/{n} ({win/n:.0%})  本命3連対 {(top.fin<=3).mean():.0%}  単勝回収 {sum(p)/(n*100):.0%} (的中平均{(sum(p)/max(len(p),1)):.0f}円)'
          f'  上位3艇 3連単BOX回収 {sum(t3)/(n*600):.0%} / 3連複1点 {sum(f3)/(n*100):.0%} (的中{len(t3)})')
    print('  順位別3連対率 ' + ' '.join(f'{int(k)}位:{v:.0%}' for k, v in byrk.items()))
    print('  同コース内 上位3/下位3 の3連対率 ' + ' '.join(f'{int(i)}C:{r.get(True,np.nan):.0%}/{r.get(False,np.nan):.0%}' for i, r in inner.iterrows()))
    return d

def fit(d, cols, target='win', lam=0.05):
    X = d[['Z' + c for c in cols]].values; y = d[target].values
    idx = list(d.groupby('race').indices.values())
    def nll(w):
        s = X @ w; ll = 0
        for ix in idx:
            e = s[ix]; m = e.max(); lse = m + np.log(np.exp(e - m).sum())
            k = y[ix].sum()
            if k == 0: continue
            ll += e[y[ix] == 1].sum() - k * lse
        return -ll + lam * (w @ w)
    w = minimize(nll, np.zeros(len(cols))).x
    return dict(zip(cols, w))

def course_bias(d):
    t = d.copy()
    for c in ITEMS:
        t[c + '差'] = t['補正' + c] - t.groupby('race')['補正' + c].transform('mean')
    print('補正後の号艇別ずれ（マイナス=速く見える）')
    print(t.groupby('枠')[[c + '差' for c in ITEMS]].mean().round(3).to_string())

def load_compact(files):
    rows, pay = [], {}
    for fn in files:
        for line in open(fn, encoding='utf-8'):
            line = line.strip()
            if not line: continue
            k, boats, p = line.split('|')
            pp = p.split(',')
            pay[k] = dict(tan_b=pp[0], tan=int(pp[1] or 0), t3=pp[2], t3p=int(pp[3] or 0), f3=pp[4], f3p=int(pp[5] or 0))
            for b in boats.split(';'):
                f = b.split(',')
                if len(f) < 8: continue
                if f[2] == '': continue  # 欠場
                rows.append([k, f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7]])
    d = pd.DataFrame(rows, columns=['race', '枠', '級別', '展示', '一周', 'まわり足', '直線', '着順', '進入'])
    for c in ['枠', '展示', '一周', 'まわり足', '直線', '進入']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d['fin'] = pd.to_numeric(d['着順'], errors='coerce')
    d['win'] = (d.fin == 1).astype(int); d['top3'] = (d.fin <= 3).astype(int)
    for i, c in enumerate(ITEMS):
        d['補正' + c] = d[c] + d['枠'].map(lambda w: CORR[int(w)][i])
    g = d.groupby('race')
    for c in ITEMS:
        x = '補正' + c
        d['Z' + c] = ((g[x].transform('mean') - d[x]) / g[x].transform('std')).fillna(0)
    return d, pay
