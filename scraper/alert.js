// 展示が出そろったレースをアプリと同じ計算（docs/index.html の analyze）で見直し、
// 「1号艇が飛ぶ」確率が高ければ ntfy に通知する。
//
// 使い方: node scraper/alert.js <dataディレクトリ> <平文の学習結果ディレクトリ> [YYYYMMDD]
//   平文の学習結果ディレクトリには model.json / stats.json を置く（GitHub Actions で合言葉を使って復号したもの）
//   通知済みのレースは <data>/alerts/YYYYMMDD.json に残し、同じレースで二度送らない。
// 環境変数: NTFY_TOPIC（未設定なら通知せず、出すはずだった内容を表示するだけ）
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const TOBU_TH = 0.35;          // 1号艇が飛ぶ確率の基準（11/5〜11の982Rで、35%以上は実際に46%が飛んだ）
const APP_URL = 'https://nextroad11.github.io/teiyomi/';

const [dataDir, plainDir, dateArg] = process.argv.slice(2);
const jst = new Date(Date.now() + 9 * 3600e3);
const today = dateArg || jst.toISOString().slice(0, 10).replace(/-/g, '');
const nowMin = jst.getUTCHours() * 60 + jst.getUTCMinutes();

// ---- ブラウザの代わり（画面は描かない。計算だけ使う）
function stub() {
  const f = function () { return P; };
  const P = new Proxy(f, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => '';
      if (k === Symbol.iterator) return function* () {};
      if (k === 'then') return undefined;
      if (k === 'length') return 0;
      if (k === 'value' || k === 'textContent' || k === 'innerHTML') return '';
      if (k === 'dataset') return {};
      if (k === 'style') return { setProperty() {}, removeProperty() {}, getPropertyValue() { return ''; } };
      if (k === 'offsetHeight' || k === 'offsetWidth' || k === 'scrollWidth') return 0;
      if (k === 'classList') return { add() {}, remove() {}, toggle() {}, contains() { return false; } };
      return P;
    },
    apply() { return P; },
    set() { return true; },
  });
  return P;
}
const store = new Map();
const readJSON = f => JSON.parse(fs.readFileSync(f, 'utf8'));
function fakeFetch(url) {
  const u = String(url).split('?')[0];
  const name = u.includes('/data/') ? u.split('/data/')[1] : u.split('/').pop();
  let file = null;
  if (name.startsWith('enc/')) file = null;                                   // 平文で渡すので鍵つきは「無い」ことにする
  else if (['model.json', 'stats.json', 'report.json'].includes(name)) file = path.join(plainDir, name);
  else file = path.join(dataDir, name);
  if (!file || !fs.existsSync(file)) return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  const body = fs.readFileSync(file, 'utf8');
  return Promise.resolve({ ok: true, status: 200, json: async () => JSON.parse(body), text: async () => body });
}
const document = {
  querySelector: () => stub(), querySelectorAll: () => [], getElementById: () => stub(),
  addEventListener() {}, createElement: () => stub(), body: stub(), documentElement: stub(),
};
const ctx = {
  document, window: null, navigator: { clipboard: { writeText: async () => {} } },
  localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
  fetch: fakeFetch, setInterval: () => 0, clearInterval() {}, setTimeout, clearTimeout,
  console, crypto: require('crypto').webcrypto, TextEncoder, TextDecoder,
  atob: s => Buffer.from(s, 'base64').toString('binary'), btoa: s => Buffer.from(s, 'binary').toString('base64'),
  matchMedia: () => ({ matches: false, addEventListener() {} }), location: { search: '', hash: '' }, history: { replaceState() {} },
  alert() {}, Intl, Date, Math, JSON,
};
ctx.window = ctx;
vm.createContext(ctx);
// 画面を描く処理で失敗しても、計算（analyze）は使えるので止めない
process.on('unhandledRejection', e => console.log('（画面処理のエラーは無視）', String(e && e.message || e)));
const html = fs.readFileSync(path.join(__dirname, '..', 'docs', 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
vm.runInContext(scripts[scripts.length - 1], ctx, { filename: 'index.html' });

async function notify(title, body, tags) {
  const topic = (process.env.NTFY_TOPIC || '').trim();
  if (!topic) { console.log('[通知なし・NTFY_TOPIC未設定]', title, '|', body); return true; }
  const r = await fetch(`https://ntfy.sh/${topic}`, {
    method: 'POST', body,
    headers: { Title: Buffer.from(title).toString('latin1') === title ? title : `=?UTF-8?B?${Buffer.from(title).toString('base64')}?=`, Priority: '4', Tags: tags, Click: APP_URL },
  });
  console.log('通知', r.status, title);
  return r.ok;
}

(async () => {
  // 起動処理（学習結果の読み込み）が終わるのを待つ
  for (let i = 0; i < 50; i++) {
    const ready = vm.runInContext('typeof MODEL!=="undefined"&&typeof STATS!=="undefined"&&STATS!==null', ctx);
    if (ready) break;
    await new Promise(r => setTimeout(r, 100));
  }
  if (!vm.runInContext('STATS!==null', ctx)) { console.log('学習結果が読めません'); process.exit(0); }
  const dayFile = path.join(dataDir, today + '.json');
  if (!fs.existsSync(dayFile)) { console.log('今日のデータなし'); return; }
  const races = readJSON(dayFile).races || [];
  const alertDir = path.join(dataDir, 'alerts');
  fs.mkdirSync(alertDir, { recursive: true });
  const sentFile = path.join(alertDir, today + '.json');
  const sent = fs.existsSync(sentFile) ? readJSON(sentFile) : { tobu: [] };
  ctx.__races = races;
  let n = 0;
  for (const r of races) {
    if (sent.tobu.includes(r.id)) continue;
    const b = r.before;
    if (!b || !b.complete || !r.deadline) continue;
    const [h, m] = r.deadline.split(':').map(Number);
    if (!process.env.ALERT_TEST && (r.result || h * 60 + m < nowMin)) continue;   // 締切を過ぎたものは送らない（試験時は全部見る）
    ctx.__r = r;
    const res = vm.runInContext(`(()=>{const a=analyze(__r);if(!a)return null;let b0=null;try{b0=analyze({...__r,before:null});}catch(e){}
      const top=a.top[0];return {tobu:a.one.tobu,win:a.one.win,course:a.one.course,top:top.waku,topP:top.pWin,tobu0:b0?b0.one.tobu:null,
      honsen:a.honsen.map(c=>c.k).slice(0,4),ori:!!(__r.before&&__r.before.ori)};})()`, ctx);
    if (!res || res.tobu < TOBU_TH) continue;
    const pc = v => Math.round(v * 100) + '%';
    const title = `⚠️ 1号艇が飛ぶ予測 ${r.venue}${r.rno}R（締切${r.deadline}）`;
    const body = [
      `飛ぶ（4着以下）確率 ${pc(res.tobu)}${res.tobu0 != null ? `（展示前 ${pc(res.tobu0)}）` : ''}`,
      `1号艇の1着 ${pc(res.win)}${res.course !== 1 ? `・進入${res.course}コース` : ''}`,
      `本命 ${res.top}号艇（1着 ${pc(res.topP)}）`,
      `本線 ${res.honsen.join(' ')}`,
      res.ori ? '' : '※オリジナル展示はまだ（展示タイムまでで判定）',
    ].filter(Boolean).join('\n');
    if (await notify(title, body, 'warning,speedboat')) { sent.tobu.push(r.id); n++; }
  }
  fs.writeFileSync(sentFile, JSON.stringify(sent));
  console.log(`1号艇が飛ぶアラート ${n}件`);
})();
