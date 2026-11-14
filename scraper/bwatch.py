"""B級穴選手ウォッチ：開催の足の相対評価を毎朝つくる。

考え方（2026/11/14 の検証で決めたもの。くわしくは README）
- 足スコア（オリジナル展示＋展示タイム、場別の補正・重み）を、その開催の「前日まで」の全レースでまとめて評価する。
  レースごとの水面・風・時間帯の差は「レース効果」として差し引き、選手ごとの速さ（選手効果）だけを残す。
  → 開催の全選手を同じものさしで並べられる。日がたつほど計測が増えて正確になる（古い日も同じ重みでよい）。
- その日の情報（当日の展示・結果）は一切使わない。朝の時点で決まる評価。
- 場によって足の効き目が大きく違う（江戸川・住之江・三国・蒲郡は弱い）ので、その場では評価を一段下げる。

使い方: python scraper/bwatch.py <dataディレクトリ> [YYYYMMDD] [出力ファイル]
  出力は平文の JSON。GitHub Actions で合言葉を使って暗号化してから保存する（enc/bwatch/YYYYMMDD.json）。
"""
from __future__ import annotations

import collections
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

VERSION = "2026-11-14"
VENUES = {1: '桐生', 2: '戸田', 3: '江戸川', 4: '平和島', 5: '多摩川', 6: '浜名湖', 7: '蒲郡', 8: '常滑', 9: '津', 10: '三国',
          11: 'びわこ', 12: '住之江', 13: '尼崎', 14: '鳴門', 15: '丸亀', 16: '児島', 17: '宮島', 18: '徳山', 19: '下関',
          20: '若松', 21: '芦屋', 22: '福岡', 23: '唐津', 24: '大村'}

# ---- 足スコアの設定（docs/index.html の ASHI_CONFIG 2026-11-08 と同じ値）
CORR_COMMON = {1: [0.40, 0.20, 0, 0.02], 2: [0.30, 0.10, 0, 0.01], 3: [0.20, 0, 0, 0],
               4: [0.10, -0.05, -0.01, -0.01], 5: [0.05, -0.10, -0.02, -0.02], 6: [0, -0.15, -0.02, -0.02]}
CORR_VENUE = {
    1: {1: [0.23, 0.11, 0.05, 0.02], 2: [0.09, 0.07, 0.03, 0.01], 3: [0.05, 0.05, 0.02, 0], 4: [0.02, 0.03, 0.01, 0], 5: [0.02, 0.02, 0.01, 0], 6: [0, 0, 0, 0]},
    2: {1: [0.40, 0.08, 0.07, 0.05], 2: [0.15, 0.04, 0.03, 0.03], 3: [0.04, 0.02, 0.01, 0.02], 4: [0.01, 0.01, 0, 0.01], 5: [-0.02, 0.01, 0, 0], 6: [0, 0, 0, 0]},
    4: {1: [0.41, 0.18, 0.01, 0.01], 2: [0.14, 0.11, 0, 0], 3: [0.05, 0.05, 0, 0], 4: [0.03, 0.03, 0, -0.01], 5: [0, 0.01, 0, -0.01], 6: [0, 0, 0, 0]},
    6: {1: [0.48, 0.19, -0.06, 0.02], 2: [0.17, 0.12, -0.04, 0.01], 3: [0.05, 0.07, -0.03, 0], 4: [0.03, 0.04, -0.02, 0], 5: [0.01, 0.02, -0.01, 0], 6: [0, 0, 0, 0]},
    7: {1: [0.35, 0.29, -0.02, 0.04], 2: [0.10, 0.15, -0.02, 0.01], 3: [0, 0.07, -0.02, 0], 4: [0, 0.02, -0.01, 0], 5: [-0.01, 0, 0, 0], 6: [0, 0, 0, 0]},
    8: {1: [0.43, 0.08, 0.06, 0.01], 2: [0.16, 0.04, 0.01, 0], 3: [0.05, 0.01, 0, 0], 4: [0.01, 0, 0, 0], 5: [0, -0.02, 0, 0], 6: [0, 0, 0, 0]},
    9: {1: [0.46, 0.37, -0.11, 0.01], 2: [0.16, 0.19, -0.05, 0], 3: [0.05, 0.11, -0.04, 0], 4: [0.01, 0.06, -0.02, 0], 5: [0, 0.03, -0.01, -0.01], 6: [0, 0, 0, 0]},
    10: {1: [0.44, 0.14, 0.03, 0.01], 2: [0.17, 0.06, 0.01, 0], 3: [0.07, 0.03, 0, 0], 4: [0.05, 0.02, 0.01, 0], 5: [0.03, 0.01, 0.01, 0], 6: [0, 0, 0, 0]},
    11: {1: [0.38, 0.35, -0.12, 0.03], 2: [0.10, 0.19, -0.09, 0.02], 3: [0.03, 0.11, -0.06, 0.01], 4: [0, 0.05, -0.04, 0], 5: [-0.03, 0.02, -0.01, 0], 6: [0, 0, 0, 0]},
    14: {1: [0.35, 0.07, 0.12, 0.05], 2: [0.10, 0.05, 0.04, 0.01], 3: [0.01, 0.03, 0.01, 0], 4: [-0.01, 0.02, 0, 0.01], 5: [-0.04, 0.01, 0, 0], 6: [0, 0, 0, 0]},
    15: {1: [0.35, 0.09, 0.14, 0.03], 2: [0.09, 0.08, 0.10, 0.01], 3: [0.01, 0.05, 0.09, 0.01], 4: [-0.02, 0.04, 0.08, 0], 5: [-0.02, 0.03, 0.07, 0], 6: [0, 0, 0, 0]},
    16: {1: [0.39, -0.03, 0.12, 0.04], 2: [0.14, -0.01, 0.04, 0.03], 3: [0.03, -0.01, 0.02, 0.02], 4: [0.03, 0, 0.01, 0.01], 5: [0, -0.01, 0.01, 0.01], 6: [0, 0, 0, 0]},
    17: {1: [0.31, 0, 0.04, 0.01], 2: [0.11, 0.01, 0.01, 0], 3: [0.03, 0, 0.01, 0], 4: [0.02, 0, 0.01, 0], 5: [0.02, 0.01, 0, 0], 6: [0, 0, 0, 0]},
    20: {1: [0.50, 0.15, 0.02, 0.01], 2: [0.23, 0.07, 0, 0], 3: [0.10, 0.02, 0, 0], 4: [0.06, 0.01, 0, 0], 5: [0, 0, 0, 0], 6: [0, 0, 0, 0]},
    21: {1: [0.51, 0.23, 0.02, 0.01], 2: [0.21, 0.10, 0, 0], 3: [0.09, 0.06, -0.01, 0], 4: [0.07, 0.03, -0.01, 0], 5: [0.01, 0.02, -0.01, 0], 6: [0, 0, 0, 0]},
    22: {1: [0.76, 0.16, 0.01, 0.02], 2: [0.45, 0.11, 0, 0.01], 3: [0.29, 0.06, 0, 0.01], 4: [0.17, 0.03, 0, 0], 5: [0.05, 0.02, 0, 0], 6: [0, 0, 0, 0]},
    23: {1: [0.39, 0.28, -0.03, 0.02], 2: [0.16, 0.15, -0.02, 0.01], 3: [0.05, 0.07, -0.02, 0], 4: [0.04, 0.05, -0.01, -0.01], 5: [0.02, 0.02, 0, 0], 6: [0, 0, 0, 0]},
    24: {1: [0.30, 0.06, 0.03, 0.01], 2: [0.10, 0.02, 0, 0], 3: [0.04, 0.02, -0.01, 0], 4: [0.02, 0.02, -0.01, -0.01], 5: [0.02, 0.01, 0, 0], 6: [0, 0, 0, 0]},
}
W_DEFAULT = [1, 0.5, 0.5, 1]
W_VENUE = {1: [1, 2/3, 1, 2/3], 5: [1, 2/3, 1, 2/3], 7: [1, 0, 0, 1], 16: [1, 2/3, 1, 2/3], 19: [1, 0, 0, 0.25], 24: [1, 0, 1, 1]}
ITEMS = ['一周', 'まわり足', '直線', '展示']

# 場ごとの「足の評価の効き目」（検証期間の改善度。11/14 のバックテスト 3日目以降・後半17,192R）
EFFECT = {1: 48, 2: 44, 3: 2, 4: 32, 5: 65, 6: 55, 7: 18, 8: 46, 9: 64, 10: 8, 11: 42, 12: 6, 13: 44, 14: 29, 15: 35,
          16: 20, 17: 43, 18: 61, 19: 22, 20: 46, 21: 44, 22: 78, 23: 28, 24: 48}


def reliab(jcd: int) -> str:
    e = EFFECT.get(jcd)
    return '高' if e is not None and e >= 40 else '低' if e is not None and e < 20 else '中'


# ---- データの読み込み（その日の取得ファイルがあればそれ、なければ過去データ＋オリ展）
_cache: dict = {}


def load_day(root: str, d: str) -> dict:
    """{jcd: [ {rno, boats:[{toban,waku,cls,name,ex,ori,fin}], order} ]}"""
    if (root, d) in _cache:
        return _cache[(root, d)]
    out = collections.defaultdict(list)
    live = os.path.join(root, f'{d}.json')
    hist = os.path.join(root, 'history', f'{d}.json')
    if os.path.exists(hist):
        races = json.load(open(hist, encoding='utf-8'))['races']
        op = os.path.join(root, 'oriten', f'{d}.json')
        ori = json.load(open(op, encoding='utf-8'))['races'] if os.path.exists(op) else {}
        for r in races:
            o = ori.get(f"{r['jcd']:02d}-{r['rno']:02d}")
            t = r.get('tri') or {}
            out[r['jcd']].append(dict(rno=r['rno'], ori=o, order=t.get('order'), pay=t.get('payout'),
                boats=[dict(toban=b['toban'], waku=b['waku'], cls=b.get('cls'), name=b.get('name'), ex=b.get('exTime'),
                            fin=b.get('finish'), m2=b.get('motor2'), nw=b.get('natWin')) for b in r['boats']]))
    elif os.path.exists(live):
        for r in json.load(open(live, encoding='utf-8'))['races']:
            bf = r.get('before') or {}
            bb = bf.get('boats') or {}
            res = r.get('result') or {}
            order = res.get('order')
            fin = {}
            if order:
                for i, w in enumerate(order.split('-')):
                    if w.isdigit():
                        fin[int(w)] = i + 1
            out[r['jcd']].append(dict(rno=r['rno'], ori=bf.get('ori'), order=order, pay=res.get('payout'),
                boats=[dict(toban=b['toban'], waku=b['waku'], cls=b.get('cls'), name=b.get('name'),
                            ex=(bb.get(str(b['waku'])) or {}).get('exTime'), fin=fin.get(b['waku']),
                            m2=b.get('motor2'), nw=b.get('natWin')) for b in r['boats']]))
    _cache[(root, d)] = dict(out)
    return _cache[(root, d)]


def items_of(jcd: int, race: dict) -> dict:
    """{toban: [一周, まわり足, 直線, 展示]}（枠ごとの補正後。ない項目は None）"""
    ori = race.get('ori')
    idx = {}
    if ori and ori.get('items'):
        for k, nm in enumerate(ori['items']):
            if nm in ('一周', '半周ラップ'):
                idx[0] = k
            elif nm == 'まわり足':
                idx[1] = k
            elif nm == '直線':
                idx[2] = k
    corr = CORR_VENUE.get(jcd, CORR_COMMON)
    res = {}
    for b in race['boats']:
        if b.get('ex') is None:
            continue
        ov = ((ori or {}).get('boats') or {}).get(str(b['waku'])) or []
        v = []
        for q in range(3):
            x = ov[idx[q]] if q in idx and idx[q] < len(ov) and ov[idx[q]] is not None else None
            v.append(None if x is None else float(x) + corr[b['waku']][q])
        v.append(float(b['ex']) + corr[b['waku']][3])
        res[b['toban']] = v
    return res


def _dd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:]))


def _ds(x: date) -> str:
    return x.strftime('%Y%m%d')


def meeting_days(root: str, d: str, jcd: int, players: set) -> list[str]:
    """その日より前の、同じ開催の日（古い順）。前日と出場選手の半分以上が同じなら同じ開催とみなす。"""
    days = []
    cur = players
    x = _dd(d)
    for _ in range(9):
        x -= timedelta(days=1)
        races = load_day(root, _ds(x)).get(jcd)
        if not races:
            break
        s = {b['toban'] for r in races for b in r['boats']}
        if len(s & cur) < 0.5 * len(cur):
            break
        days.append(_ds(x))
        cur = s
    return days[::-1]


def rating(jcd: int, races_items: list[dict]) -> tuple[dict, dict, dict]:
    """x = レース効果 + 選手効果 を項目ごとに解き、場の重みで合計。返り値: (合計, 項目ごとのz, 計測レース数)"""
    w = W_VENUE.get(jcd, W_DEFAULT)
    players = sorted({p for ri in races_items for p in ri})
    tot = {p: 0.0 for p in players}
    per = {p: [None] * 4 for p in players}
    cnt = collections.Counter(p for ri in races_items for p in ri)
    for k in range(4):
        obs = [(i, p, ri[p][k]) for i, ri in enumerate(races_items) for p in ri if ri[p][k] is not None]
        if len(obs) < 12:
            continue
        a = {p: 0.0 for p in players}
        for _ in range(15):
            g = collections.defaultdict(list)
            for i, p, x in obs:
                g[i].append(x - a[p])
            c = {i: sum(v) / len(v) for i, v in g.items()}
            g = collections.defaultdict(list)
            for i, p, x in obs:
                g[p].append(x - c[i])
            a = {p: sum(v) / len(v) for p, v in g.items()}
            m = sum(a.values()) / len(a)
            a = {p: v - m for p, v in a.items()}
        vals = list(a.values())
        mu = sum(vals) / len(vals)
        sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5
        if sd > 0:
            for p in a:
                z = -a[p] / sd
                tot[p] += w[k] * z
                per[p][k] = z
    return tot, per, dict(cnt)


# ---- S〜D の基準（11/14 のバックテストで決めたもの。README と test.html にも同じ説明）
def grade_of(pct: float, n: int, rel: str, cls: str = 'B1') -> str:
    """pct: 開催内の順位の割合（0=1位）、n: 計測したレース数、rel: 場の効き目、cls: 級別"""
    g = 'S' if pct < 0.10 else 'A' if pct < 0.25 else 'B' if pct < 0.45 else 'C' if pct < 0.70 else 'D'
    order = 'SABCD'
    i = order.index(g)
    if n < 2 and i < 2:
        i = 2 if g == 'A' else 1            # 計測1走だけなら S→A、A→B
    if rel == '低':
        i = max(i, 2)                       # 足が効きにくい場は最高でもB
    if cls == 'B2':
        i = max(i, 1)                       # B2 は足が良くても3連対3割ほど（バックテスト）なので最高でもA
    return order[i]


def build(root: str, d: str) -> dict:
    today = load_day(root, d)
    venues = {}
    for jcd, races in sorted(today.items()):
        players = {b['toban'] for r in races for b in r['boats']}
        mdays = meeting_days(root, d, jcd, players)
        if not mdays:
            venues[str(jcd)] = dict(venue=VENUES.get(jcd), day=1, start=d, reliab=reliab(jcd), effect=EFFECT.get(jcd),
                                    note='初日（足の評価は今日の展示が出てから。明日の朝に初日分で評価します）', players=[])
            continue
        its, info = [], {}
        for md in mdays:
            for r in load_day(root, md)[jcd]:
                its.append(items_of(jcd, r))
                for b in r['boats']:
                    e = info.setdefault(b['toban'], dict(fin=[], name=b.get('name'), cls=b.get('cls')))
                    if b.get('fin'):
                        e['fin'].append(b['fin'])
        tot, per, cnt = rating(jcd, its)
        ranked = sorted([p for p in tot if cnt.get(p)], key=lambda p: -tot[p])
        N = len(ranked)
        rel = reliab(jcd)
        todays = collections.defaultdict(list)
        cur = {}
        for r in races:
            for b in r['boats']:
                todays[b['toban']].append([r['rno'], b['waku']])
                cur[b['toban']] = b
        out = []
        for i, p in enumerate(ranked):
            if p not in players:            # 途中帰郷など、今日いない選手は外す
                continue
            b = cur[p]
            pct = i / N
            cls = b.get('cls') or info[p]['cls']
            g = grade_of(pct, cnt[p], rel, cls) if cls in ('B1', 'B2') else None
            z = per[p]
            why = [f'今節の足 {N}人中{i + 1}位（上位{round((i + 1) / N * 100)}%・計測{cnt[p]}走）']
            good = [ITEMS[k] for k in range(4) if z[k] is not None and z[k] >= 1.0]
            bad = [ITEMS[k] for k in range(4) if z[k] is not None and z[k] <= -1.0]
            if good:
                why.append('・'.join(good) + 'が上位')
            if bad:
                why.append('・'.join(bad) + 'は下位')
            if z[0] is None and z[1] is None:
                why.append('オリジナル展示なし（展示タイムのみ）')
            f = info[p]['fin']
            if f:
                why.append('今節の着 ' + ' '.join(str(x) for x in f))
                if i / N < 0.25 and min(f) >= 4:
                    why.append('足のわりに着が悪い（巻き返しは検証上は不利）')
            if rel == '低':
                why.append(f'{VENUES.get(jcd)}は足の評価が効きにくい場（評価を一段階下げています）')
            out.append(dict(toban=p, name=b.get('name') or info[p]['name'], cls=cls, rt=round(tot[p], 3), rank=i + 1, N=N,
                            pct=round(pct, 3), n=cnt[p], z=[None if x is None else round(x, 2) for x in z], grade=g,
                            fin=f, why=why, today=todays.get(p, []), m2=b.get('m2'), nw=b.get('nw')))
        venues[str(jcd)] = dict(venue=VENUES.get(jcd), day=len(mdays) + 1, start=mdays[0], reliab=rel,
                                effect=EFFECT.get(jcd), players=out)
    return dict(date=d, version=VERSION, made=datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M'),
                venues=venues)


def main():
    root = sys.argv[1]
    d = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d')
    dst = sys.argv[3] if len(sys.argv) > 3 else os.path.join(root, 'bwatch', f'{d}.json')
    res = build(root, d)
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    json.dump(res, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    n = sum(1 for v in res['venues'].values() for p in v['players'] if p['grade'] in ('S', 'A'))
    print(f'B級ウォッチ {d}: {len(res["venues"])}場, S・A評価 {n}人 → {dst}')


if __name__ == '__main__':
    main()
