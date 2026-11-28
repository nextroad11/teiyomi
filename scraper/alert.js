// 展示が出そろったレースをアプリと同じ計算（docs/index.html の analyze）で見直し、
// 「1号艇が飛ぶ」確率が高ければ ntfy に通知する。
//
// 使い方: node scraper/alert.js <dataディレクトリ> <平文の学習結果ディレクトリ> [YYYYMMDD]
//   平文の学習結果ディレクトリには model.json / stats.json を置く（GitHub Actions で合言葉を使って復号したもの）
//   通知済みのレースは <data>/alerts/YYYYMMDD.json に残し、同じレースで二度送らない。
// 環境変数: NTFY_TOPIC（未設定なら通知せず、出すはずだった内容を表示するだけ）
//           NTFY_TOPIC_KIN（金城さん専用。特別戦アラートだけ送る）
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const BW_DAY_MAX = 12;         // B級ウォッチ「勝負候補」の通知は1日12件まで（多すぎると見なくなるため）
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

async function notify(title, body, tags, env = 'NTFY_TOPIC') {
  const topic = (process.env[env] || '').trim();
  if (!topic) { console.log(`[通知なし・${env}未設定]`, title, '|', body); return env === 'NTFY_TOPIC'; }
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

  // ---- 特別戦アラート（11/26 殿）：特別戦ページに載るレース（前日のAIで選んだもの＋展示で浮上したもの）で、
  //      展示とオリジナル展示が入って足スコアが確定したら通知する。オリ展が来ないまま締切5分前になったら、その時点で送る。
  try {
    sent.toku = sent.toku || [];
    vm.runInContext('races=__races', ctx);
    let k = 0;
    for (const r of races) {
      if (sent.toku.includes(r.id)) continue;
      const b = r.before;
      if (r.cancel || !b || !b.complete || !r.deadline) continue;   // 中止・順延のレースは送らない
      const [h, m] = r.deadline.split(':').map(Number);
      const left = h * 60 + m - nowMin;
      if (!process.env.ALERT_TEST && (r.result || left < 0)) continue;
      if (!b.ori && left > 5 && !process.env.ALERT_TEST) continue;          // 足スコアの確定（オリ展）を待つ
      ctx.__r = r;
      const x = vm.runInContext(`(()=>{let a0=null;try{a0=analyze({...__r,before:null,odds:null});}catch(e){}const a=analyze(__r);if(!a)return null;
        const pick=!!(a0&&tokuOK(__r,a0)),rise=!pick&&tokuOK(__r,a);if(!pick&&!rise)return null;
        const ink=a.ink?a.ink.km.slice(0,3).map(q=>q.waku+'号艇の'+q.km):[];
        const ashi=a.boats.filter(q=>q.ashi).sort((p,q)=>p.ashi.rank-q.ashi.rank).slice(0,3).map(q=>q.waku+'号艇'+(q.footGrade?'（足'+q.footGrade+'）':''));
        return {pick,rise,name:(__r.name||'').trim(),tobu0:a0?a0.one.tobu:null,tobu:a.one.tobu,man0:a0?a0.manP:null,man:a.manP,ink,ashi,lose:a.ink?a.ink.lose:null};})()`, ctx);
      if (!x) continue;
      const pc = v => v == null ? '-' : Math.round(v * 100) + '%';
      const title = `${x.rise ? '⬆ 展示で浮上・' : ''}特別戦 ${r.venue}${r.rno}R ${x.name}（締切${r.deadline}）`;
      const body = [
        `1号艇が飛ぶ ${pc(x.tobu0)} → ${pc(x.tobu)}（前日→展示後）`,
        `万舟期待 ${pc(x.man0)} → ${pc(x.man)}`,
        x.ink.length ? `インの負け方（上位）：${x.ink.join('・')}` : '',
        x.ashi.length ? `足スコア上位：${x.ashi.join('・')}` : '',
        b.ori ? '' : '※オリジナル展示はまだ（展示タイムまでで判定）',
      ].filter(Boolean).join('\n');
      if (await notify(title, body, 'trophy,speedboat')) { sent.toku.push(r.id); k++; }
      // 金城さん専用の通知先（NTFY_TOPIC_KIN）にも同じ内容を送る（11/27 殿）。未登録なら何もしない
      try { await notify(title, body, 'trophy,speedboat', 'NTFY_TOPIC_KIN'); } catch (e) {}
    }
    fs.writeFileSync(sentFile, JSON.stringify(sent));
    console.log(`特別戦アラート ${k}件`);
  } catch (e) { console.log('特別戦アラートでエラー（ほかの通知には影響なし）', String(e && e.message || e)); }

  // ---- B級ウォッチ「勝負候補」：今節の足の評価S・Aの B級選手が出走し、展示後・公式オッズで
  //      その選手を1着か2着に置いた3連単に期待値の基準を満たす組があり、2着以内の確率が20%以上のとき
  try {
    const enc = path.join(dataDir, 'enc', 'bwatch', today + '.json');
    const plainBW = path.join(plainDir, 'bwatch.json');
    if (fs.existsSync(enc) && process.env.APP_PASS) {
      require('child_process').execFileSync('python', [path.join(__dirname, 'crypt.py'), 'decrypt', enc, plainBW], { stdio: 'ignore' });
    }
    if (!fs.existsSync(plainBW)) { console.log('B級ウォッチの評価なし'); return; }
    const BWD = readJSON(plainBW);
    if (BWD.date !== today) { console.log('B級ウォッチの評価が今日の分ではない'); return; }
    ctx.__bw = BWD;
    vm.runInContext('BW=__bw', ctx);
    sent.bw = sent.bw || [];
    let m = 0;
    for (const [js, v] of Object.entries(BWD.venues)) {
      const vmap = Object.fromEntries(v.players.map(p => [p.toban, p]));
      for (const p of v.players) {
        if (!['S', 'A'].includes(p.grade)) continue;
        for (const [rno, w] of p.today || []) {
          const r = races.find(x => x.jcd === +js && x.rno === rno);
          if (!r || !r.before || !r.before.complete || !r.deadline) continue;
          const key = `${r.id}#${p.toban}`;
          if (sent.bw.some(e => e.key === key)) continue;
          if (sent.bw.length >= BW_DAY_MAX) continue;            // 1日の通知は多くても BW_DAY_MAX 件まで
          const [h, mi] = r.deadline.split(':').map(Number);
          if (!process.env.ALERT_TEST && (r.result || h * 60 + mi < nowMin)) continue;
          ctx.__r = r; ctx.__vmap = vmap; ctx.__w = w;
          const x = vm.runInContext(`(()=>{const x=bwRace(__r,__vmap,__w);if(!x)return null;
            const mk=Object.fromEntries(x.a.combos.map(c=>[c.k,c.pMk]));
            return {p1:x.p1,p2:x.p2,real:x.real,rec:x.rec.map(c=>({k:c.k,odds:c.odds,ev:c.ev,p:c.p,mk:mk[c.k]||0}))};})()`, ctx);
          if (!x || !x.real || !x.rec.length || x.p2 < 0.2) continue;
          const pc = v2 => Math.round(v2 * 100) + '%';
          const first = x.rec.filter(c => +c.k.split('-')[0] === w).reduce((a, c) => a + c.ev, 0);
          const second = x.rec.filter(c => +c.k.split('-')[1] === w).reduce((a, c) => a + c.ev, 0);
          const aim = first >= second ? '1着' : '2着';
          const reasons = [];
          const z = p.z || [];
          if (z[2] != null && z[2] >= 1) reasons.push('伸び足優秀');
          if (z[1] != null && z[1] >= 1) reasons.push('回り足優秀');
          if (z[0] != null && z[0] >= 1) reasons.push('一周が速い');
          if (z[3] != null && z[3] >= 1) reasons.push('展示が良い');
          if (!reasons.length) reasons.push(`今節の足 ${p.N}人中${p.rank}位`);
          if (w <= 3) reasons.push('好枠');
          const best = x.rec[0];
          if (best.mk > 0 && best.p / best.mk >= 1.5) reasons.push('人気薄');
          const title = `B級穴選手・勝負候補 ${r.venue}${r.rno}R（締切${r.deadline}）`;
          const body = [
            '【B級穴選手・勝負候補】',
            `会場：${r.venue}`,
            `レース：${r.rno}R（締切${r.deadline}）`,
            `選手：${p.name}（${p.cls}・${w}号艇）`,
            `今節評価：${p.grade}（今節の足 ${p.N}人中${p.rank}位・計測${p.n}走）`,
            `狙い：${aim}（1着 ${pc(x.p1)}・2着以内 ${pc(x.p2)}）`,
            `理由：${reasons.join('・')}`,
            `推奨3連単：${x.rec.map(c => `${c.k}（${c.odds}倍）`).join(' ')}`,
            `期待値：${best.ev.toFixed(2)}（最大）`,
          ].join('\n');
          if (await notify(title, body, 'dart,speedboat')) {
            sent.bw.push({ key, toban: p.toban, grade: p.grade, waku: w, p1: x.p1, p2: x.p2, rec: x.rec.map(c => [c.k, c.odds, +c.ev.toFixed(3)]), at: new Date(Date.now() + 9 * 3600e3).toISOString().slice(11, 16) });
            m++;
          }
        }
      }
    }
    fs.writeFileSync(sentFile, JSON.stringify(sent));
    console.log(`B級ウォッチ 勝負候補の通知 ${m}件`);
  } catch (e) { console.log('B級ウォッチの通知でエラー（イン飛びアラートには影響なし）', String(e && e.message || e)); }
})();
