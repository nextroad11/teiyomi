"""平和島・浜名湖 足スコア 日次更新＋分析レポート

使い方: python3 daily.py DATA_DIR [--no-update]
  DATA_DIR = teiyomi の data ブランチを clone したフォルダ（history/ oriten/ と当日の YYYYMMDD.json）
  - 新しいレースを data/*.txt に追記、グレードを data/grades.json に記録
  - reports/YYYYMMDD.md を書き、内容を標準出力にも出す
"""
import json, os, sys, glob, subprocess, datetime
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'lib'))
import gama as G
from search_g import ranks, stats, grid, score

DATA = sys.argv[1]
UPDATE = '--no-update' not in sys.argv
CFG = json.load(open(os.path.join(HERE, 'config.json')))
KEYS = ['一周', 'まわり足', '直線', '展示']
FORMS = {k: dict(zip(KEYS, v)) for k, v in CFG['forms'].items()}
GR_PATH = os.path.join(HERE, 'data', 'grades.json')
grades = json.load(open(GR_PATH))
today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y%m%d')

def git(*a):
    return subprocess.run(['git', '-C', DATA, *a], capture_output=True, text=True).stdout

def grade_from_root(day, jcd):
    """その日の出走表ファイル（data ブランチ直下 YYYYMMDD.json）からグレードを読む。消えていれば git 履歴から。"""
    txt = None
    p = os.path.join(DATA, day + '.json')
    if os.path.exists(p):
        txt = open(p, encoding='utf-8').read()
    else:
        h = git('log', '-n1', '--format=%H', '--diff-filter=D', '--', day + '.json').strip()
        if h: txt = git('show', f'{h}^:{day}.json')
    if not txt: return None
    try: rs = json.loads(txt)['races']
    except Exception: return None
    gs = {r.get('grade') for r in rs if r.get('jcd') == jcd}
    gs.discard(None)
    return sorted(gs)[0] if gs else None

def fmt(x): return '' if x is None else f'{x:.2f}'

def convert(jcd, have):
    out = []
    for of in sorted(glob.glob(os.path.join(DATA, 'oriten', '2*.json'))):
        day = os.path.basename(of)[:8]
        hf = os.path.join(DATA, 'history', day + '.json')
        if not os.path.exists(hf): continue
        ori = json.load(open(of))['races']
        for r in json.load(open(hf))['races']:
            if r['jcd'] != jcd: continue
            key = f"{day}_{r['rno']}"
            if key in have: continue
            o = ori.get(f"{jcd:02d}-{r['rno']:02d}")
            if not o: continue
            boats = []
            for b in sorted(r['boats'], key=lambda b: b['waku']):
                v = o['boats'].get(str(b['waku']))
                if not v: continue
                m = dict(zip(o['items'], v))
                fin = str(b['finish']) if b.get('finish') else (b.get('code') or '')
                boats.append(','.join([str(b['waku']), b.get('cls') or '', fmt(b.get('exTime')), fmt(m.get('一周')),
                                       fmt(m.get('まわり足')), fmt(m.get('直線')), fin, str(b.get('course') or '')]))
            if len(boats) < 5: continue
            t = r.get('tri') or {}
            out.append(f"{key}|{';'.join(boats)}|,0,{t.get('order','')},{t.get('payout') or 0},,0")
    return out

def series_of(days):
    """連続する開催日を1節とみなす（2日以上空いたら別の節）"""
    days = sorted(set(days)); lab = {}; start = prev = None
    for d in days:
        dt = datetime.datetime.strptime(d, '%Y%m%d')
        if prev is None or (dt - prev).days > 1: start = d
        lab[d] = start; prev = dt
    return lab

def best(d, GR):
    res = [(score(stats(d, w)), w) for w in GR]
    res.sort(key=lambda x: -x[0]); return res

def boot(d, wa, wb, B=300, seed=0):
    d = d[d.fin.notna()]
    races = d.race.unique(); rng = np.random.default_rng(seed)
    A = dict(tuple(d.assign(rk=ranks(d, wa)).groupby('race'))); Bm = dict(tuple(d.assign(rk=ranks(d, wb)).groupby('race')))
    def sep(x):
        num = den = 0
        for c, g in x.groupby('進入'):
            u = g[g.rk <= 3].top3.mean(); l = g[g.rk > 3].top3.mean()
            if not (np.isnan(u) or np.isnan(l)): num += (u - l) * len(g); den += len(g)
        return num / den * 100
    out = []
    for _ in range(B):
        s = rng.choice(races, len(races))
        out.append(sep(pd.concat([A[r] for r in s])) - sep(pd.concat([Bm[r] for r in s])))
    return np.percentile(out, [2.5, 50, 97.5])

def wstr(w): return '/'.join(f"{w[k]:.2g}" for k in KEYS)
def pct(x): return f"{x*100:.1f}"

GR = list(grid())
lines = [f"# 足スコア日次レポート（平和島・浜名湖） {today[:4]}/{today[4:6]}/{today[6:]}", "",
         "式の重みは 一周/まわり足/直線/展示。sep＝同じ進入コース内で足スコア上位3艇と下位3艇の3連対率の差（ポイント）。SG・G1・G2は除外、G3は含む。", ""]
summary = []
for jcd_s, v in CFG['venues'].items():
    jcd = int(jcd_s); path = os.path.join(HERE, v['file'])
    have = {l.split('|')[0] for l in open(path) if l.strip()}
    added = []
    if UPDATE:
        for day in sorted({os.path.basename(f)[:8] for f in glob.glob(os.path.join(DATA, 'oriten', '2*.json')) + glob.glob(os.path.join(DATA, '2*.json'))} | {today}):
            if day not in grades[jcd_s]:
                g = grade_from_root(day, jcd)
                if g: grades[jcd_s][day] = g
        added = convert(jcd, have)
        if added:
            allk = {l.split('|')[0]: l.strip() for l in open(path) if l.strip()}
            for l in added: allk[l.split('|')[0]] = l
            ks = sorted(allk, key=lambda k: (k[:8], int(k[9:])))
            open(path, 'w').write('\n'.join(allk[k] for k in ks) + '\n')
    d, _ = G.load_compact([path])
    d['day'] = d.race.str[:8]
    d['grade'] = d.day.map(grades[jcd_s]).fillna('不明')
    unknown = sorted(d[d.grade == '不明'].day.unique())
    ex = set(CFG['exclude_grades'])
    d = d[~d.grade.isin(ex)].copy()
    lab = series_of(d.day.unique()); d['節'] = d.day.map(lab)
    W0 = FORMS[v['adopted']]
    newdays = sorted({l[:8] for l in added})
    lines += [f"## {v['name']}（採用式: {v['adopted']} {wstr(W0)}）", ""]
    lines.append(f"- データ: 一般戦 {d.race.nunique()}R・{d['節'].nunique()}節（{d.day.min()}〜{d.day.max()}）。今回追加 {len(added)}R" + (f"（{', '.join(x[4:6]+'/'+x[6:] for x in newdays)}）" if newdays else "（新しい結果なし）"))
    if unknown: lines.append(f"- ⚠ グレード不明の日（分析には含めています）: {', '.join(unknown)}")
    # 追加分の当たり具合
    if added:
        nd = d[d.race.isin({l.split('|')[0] for l in added})]
        if len(nd):
            x = nd.assign(rk=ranks(nd, W0)); x = x[x.fin.notna() & (x.rk == 1)]
            lines.append(f"- 追加分で採用式の1位艇: 3連対 {int((x.fin<=3).sum())}/{len(x)}、1着 {int((x.fin==1).sum())}/{len(x)}")
        else:
            lines.append("- 追加分はSG・G1等のため分析対象外")
    # 全体
    allres = best(d, GR); Wb = allres[0][1]
    names = sorted(d['節'].unique())
    loso_pick = []
    loso = {k: [] for k in list(FORMS) + ['選び直し']}
    if len(names) >= 3:
        for n in names:
            tr = d[d['節'] != n]; te = d[d['節'] == n]
            if te.race.nunique() < 12: continue
            w = best(tr, GR)[0][1]; loso_pick.append(wstr(w))
            loso['選び直し'].append(stats(te, w)['sep'])
            for fn, fw in FORMS.items(): loso[fn].append(stats(te, fw)['sep'])
    recent = d[d.day >= (datetime.datetime.strptime(d.day.max(), '%Y%m%d') - datetime.timedelta(days=30)).strftime('%Y%m%d')]
    lines += ["", "| 式 | 重み | sep | 1位艇3連対 | 1位艇1着 | 節ごとの検証 sep平均 | 直近30日 sep |", "|---|---|---|---|---|---|---|"]
    rows = [(f"**{v['adopted']}（採用）**", W0, v['adopted'])] + [(k, w, k) for k, w in FORMS.items() if k != v['adopted']] + [("全体最良（参考）", Wb, '選び直し')]
    for lab_, w, lk in rows:
        s = stats(d, w); r = stats(recent, w)
        lo = f"{np.mean(loso[lk])*100:.1f}" if loso[lk] else '-'
        lines.append(f"| {lab_} | {wstr(w)} | {pct(s['sep'])} | {pct(s['top1_3'])}% | {pct(s['top1_1'])}% | {lo} | {pct(r['sep'])} |")
    lines.append("")
    lines.append("「全体最良」の節ごとの検証欄は、毎回その節を除いて式を選び直したときの成績（過学習を差し引いた実力）です。")
    # G3 抜き
    g3 = d[~d.grade.astype(str).str.startswith('G3')]
    if g3.race.nunique() < d.race.nunique():
        s1 = stats(g3, W0); s2 = stats(g3, FORMS['戸田新'])
        lines.append(f"- G3を除くと（{g3.race.nunique()}R）: 採用式 sep {pct(s1['sep'])}・1位艇3連対 {pct(s1['top1_3'])}% ／ 戸田新 sep {pct(s2['sep'])}")
    # 判定
    lo_b, med, hi = boot(d, Wb, W0)
    sel = np.mean(loso['選び直し']) * 100 if loso['選び直し'] else np.nan
    cur = np.mean(loso[v['adopted']]) * 100 if loso[v['adopted']] else np.nan
    tag = '現行維持'
    if wstr(Wb) != wstr(W0) and lo_b > 0 and sel - cur >= 1.5: tag = '切り替え候補あり'
    alt = {k: np.mean(x) * 100 for k, x in loso.items() if x and k in FORMS}
    best_fixed = max(alt, key=alt.get) if alt else v['adopted']
    lines.append(f"- 全体最良 {wstr(Wb)} と採用式の sep 差: {med:+.1f}（95%区間 {lo_b:+.1f}〜{hi:+.1f}）")
    lines.append(f"- 節ごとの検証で一番良い既存の式: {best_fixed}（{alt.get(best_fixed, float('nan')):.1f}）／採用式 {cur:.1f}")
    if loso_pick: lines.append(f"- 節ごとに選び直した重み: {', '.join(loso_pick)}（ばらつきが大きいほど式が安定していない）")
    lines.append(f"- **判定: {tag}**" + ("（区間が0をまたがず、検証でも1.5ポイント以上上回った）" if tag != '現行維持' else ""))
    lines.append("")
    summary.append(f"{v['name']}: 追加{len(added)}R／計{d.race.nunique()}R、採用式 sep {pct(stats(d, W0)['sep'])}、{tag}")
json.dump(grades, open(GR_PATH, 'w'), indent=0, sort_keys=True)
lines = lines[:1] + ["", "**要約** " + ' ／ '.join(summary)] + lines[1:]
rep = '\n'.join(lines)
os.makedirs(os.path.join(HERE, 'reports'), exist_ok=True)
open(os.path.join(HERE, 'reports', today + '.md'), 'w').write(rep)
print(rep)
