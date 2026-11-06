// 足スコア（場別・場専用補正対応）
const CORR_COMMON = { // 枠番: [一周, まわり足, 直線, 展示] に足す値（全場共通）
  1: [0.40, 0.20, 0, 0.02], 2: [0.30, 0.10, 0, 0.01], 3: [0.20, 0, 0, 0],
  4: [0.10, -0.05, -0.01, -0.01], 5: [0.05, -0.10, -0.02, -0.02], 6: [0, -0.15, -0.02, -0.02],
};
const CORR_VENUE = { // 場専用補正（6号艇=0基準）
  '04': {1: [0.41, 0.18, 0.01, 0.01], 2: [0.14, 0.11, 0, 0], 3: [0.05, 0.05, 0, 0], 4: [0.03, 0.03, 0, -0.01], 5: [0, 0.01, 0, -0.01], 6: [0, 0, 0, 0]}, // 平和島
  '06': {1: [0.48, 0.19, -0.06, 0.02], 2: [0.17, 0.12, -0.04, 0.01], 3: [0.05, 0.07, -0.03, 0], 4: [0.03, 0.04, -0.02, 0], 5: [0.01, 0.02, -0.01, 0], 6: [0, 0, 0, 0]}, // 浜名湖
  '11': {1: [0.38, 0.35, -0.12, 0.03], 2: [0.10, 0.19, -0.09, 0.02], 3: [0.03, 0.11, -0.06, 0.01], 4: [0, 0.05, -0.04, 0], 5: [-0.03, 0.02, -0.01, 0], 6: [0, 0, 0, 0]}, // びわこ
  '24': {1: [0.30, 0.06, 0.03, 0.01], 2: [0.10, 0.02, 0, 0], 3: [0.04, 0.02, -0.01, 0], 4: [0.02, 0.02, -0.01, -0.01], 5: [0.02, 0.01, 0, 0], 6: [0, 0, 0, 0]}, // 大村
};
const DEFAULT_W = [1, 0.5, 0.5, 1]; // 戸田新式（未検証の場）
const WEIGHTS = { // 場コード: [一周, まわり足, 直線, 展示]
  '02': [1, 0.5, 0.5, 1],     // 戸田（戸田新式）
  '04': [1, 0.5, 0.5, 1],     // 平和島（戸田新式＋平和島補正）
  '05': [1, 2/3, 1, 2/3],     // 多摩川
  '06': [1, 0.5, 0.5, 1],     // 浜名湖（戸田新式＋浜名湖補正）
  '07': [1, 0, 0, 1],         // 蒲郡
  '11': [1, 0.5, 0.5, 1],     // びわこ（戸田新式＋びわこ補正）
  '19': [1, 0, 0, 0.25],      // 下関
  '24': [1, 0, 1, 1],         // 大村（大村式＋大村補正）
};

// boats: [{waku:1..6, lap:一周, turn:まわり足, straight:直線, ex:展示タイム}]
// 計測なしの項目は null。欠場・展示タイムなしの艇は渡さない
function ashiScore(jcd, boats) {
  const code = String(jcd).padStart(2, '0');
  const w = WEIGHTS[code] || DEFAULT_W;
  const corr = CORR_VENUE[code] || CORR_COMMON;
  const keys = ['lap', 'turn', 'straight', 'ex'];
  const z = boats.map(() => [0, 0, 0, 0]);
  keys.forEach((k, j) => {
    const xs = boats.map(b => b[k] == null ? null
      : Math.round((b[k] + corr[b.waku][j]) * 100) / 100); // 補正後を小数第2位に
    const v = xs.filter(x => x != null);
    if (v.length < 2) return;
    const mu = v.reduce((a, b) => a + b, 0) / v.length;
    const sd = Math.sqrt(v.reduce((a, b) => a + (b - mu) ** 2, 0) / (v.length - 1)); // 標本標準偏差
    if (sd === 0) return;
    xs.forEach((x, i) => { if (x != null) z[i][j] = (mu - x) / sd; });
  });
  const out = boats.map((b, i) => ({
    waku: b.waku, z: z[i],
    score: z[i].reduce((a, zz, j) => a + w[j] * zz, 0),
  }));
  [...out].sort((a, b) => b.score - a.score || a.waku - b.waku)
    .forEach((o, r) => { o.rank = r + 1; });
  return out; // [{waku, z:[一周,まわり足,直線,展示], score, rank}]
}
if (typeof module !== 'undefined') module.exports = { ashiScore, WEIGHTS, CORR_COMMON, CORR_VENUE };
