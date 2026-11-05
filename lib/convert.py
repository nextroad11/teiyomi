"""teiyomi data ブランチ（history/ + oriten/）→ 足分析用のコンパクト形式。
使い方: python3 convert.py DATA_DIR JCD [FROM_YYYYMMDD]  → 標準出力に行を出す"""
import json, sys, glob, os
root, jcd = sys.argv[1], int(sys.argv[2]); since = sys.argv[3] if len(sys.argv) > 3 else '00000000'
def f2(x): return '' if x is None else f'{x:.2f}'
for of in sorted(glob.glob(os.path.join(root, 'oriten', '2*.json'))):
    day = os.path.basename(of)[:8]
    if day < since: continue
    hf = os.path.join(root, 'history', day + '.json')
    if not os.path.exists(hf): continue
    ori = json.load(open(of))['races']
    hist = {r['rno']: r for r in json.load(open(hf))['races'] if r['jcd'] == jcd}
    for rno, r in sorted(hist.items()):
        o = ori.get(f'{jcd:02d}-{rno:02d}')
        if not o: continue
        it = o['items']; ob = o['boats']
        boats = []
        for b in sorted(r['boats'], key=lambda b: b['waku']):
            v = ob.get(str(b['waku']))
            if not v: continue
            m = dict(zip(it, v))
            fin = b.get('finish'); fin = str(fin) if fin else (b.get('code') or '')
            boats.append(','.join([str(b['waku']), b.get('cls') or '', f2(b.get('exTime')), f2(m.get('一周')), f2(m.get('まわり足')), f2(m.get('直線')), fin, str(b.get('course') or '')]))
        t = r.get('tri') or {}
        print(f"{day}_{rno}|{';'.join(boats)}|,0,{t.get('order','')},{t.get('payout') or 0},,0")
