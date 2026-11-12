// Records the exact contexts the AI panel sends (chat/brief, propose, explain with a random selection) while the MA-BEMS
// simulator runs, every ~50 sim-minutes from 06:20 to 22:50. These are the inputs of the fine-tuning data.
// Needs headless Chrome on :9333 and the page from the gateway on :5178 (see eval_realq_page.mjs for the Chrome command).
//
//   v2:   node collect.mjs <out.jsonl> <rngSeed> <nRandom> [presets=1]
//   v2.2: node collect.mjs <out.jsonl> rng=<n> random=<n> [presets=1] [seeds=101-160] [modes=0.2] [kepco=0.1] [port=9333]
//         every condition gets its own ?seed=N from the range (occupancy, bookings, EVs, DR draws and day-to-day weather
//         change with it), so train and eval runs use disjoint seed ranges; a share of runs use the newer modes
//         (?coord=v2, ?baseline=sensor, ?faultImpact=1 with a fault) or the KEPCO tariff (₩, peak 15-21 h).
//         [skip=N] resumes after N finished conditions (same draws); samples are appended to <out> per condition
//   realq: node collect.mjs <out.json> realq
//         the five moments of ft/data/realq.json (no seed, as recorded) → {name: {cfg, clock, chat, propose}}
import { writeFileSync, appendFileSync } from 'node:fs';
const argv = process.argv.slice(2);
const out = argv[0] || 'samples.jsonl';
const kv = Object.fromEntries(argv.slice(1).filter((a) => a.includes('=')).map((a) => a.split(/=(.*)/s).slice(0, 2)));
const legacy = argv[1] !== undefined && /^\d+$/.test(argv[1]);
const REALQ = argv[1] === 'realq';
let seed = legacy ? +argv[1] : +(kv.rng || 1);
const nRandom = legacy ? +(argv[2] || 20) : +(kv.random || 20);
const presets = legacy ? (argv[3] || '1') : (kv.presets || '1');
const port = kv.port || '9333';
const skip = +(kv.skip || 0);
const rnd = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
const pick = (a) => a[Math.floor(rnd() * a.length)];
const r1 = (x) => Math.round(x * 10) / 10;

const configs = [];                                     // [query string, {kepco, at}]
if (REALQ) {                                            // where each realq context came from (eval_realq_page.mjs WHERE)
  for (const [name, q, at] of [['N14', '', '14:36'], ['N22', '', '22:19'], ['DR', 'scn=dr', '16:31'], ['FAULT', 'scn=fault', '14:52'], ['WORST', 'scn=worst', '17:10']]) configs.push([q, { name, at }]);
} else {
  if (presets === '1') for (const id of ['', 'heatwave', 'cloudy', 'dr', 'tight', 'evrush', 'holiday', 'fault', 'worst']) configs.push([id ? `scn=${id}` : '', {}]);
  for (let i = 0; i < nRandom; i++) {
    const p = { scn: 'custom', dT: Math.round(-3 + rnd() * 10), sun: r1(0.2 + rnd() * 0.9), occ: r1(0.2 + rnd() * 1.1), limit: pick([850, 900, 950, 1000, 1000, 1100]), ev: Math.floor(rnd() * 8) };
    if (rnd() < 0.5) { const m = 13 * 60 + Math.floor(rnd() * 20) * 15; Object.assign(p, { drAt: `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`, drShed: 150 + Math.floor(rnd() * 21) * 10, drMin: pick([30, 45, 60, 90]) }); }
    if (rnd() < 0.15) p.fault = pick(['stuck', 'drift', 'dropout']);
    configs.push([new URLSearchParams(p).toString(), {}]);
  }
  if (!legacy) {
    const [s0, s1] = String(kv.seeds || '101-160').split('-').map(Number);
    const pModes = +(kv.modes || 0.2), pKepco = +(kv.kepco || 0.1);
    configs.forEach((c, i) => {
      const extra = [`seed=${s0 + (i % (s1 - s0 + 1))}`];
      const u = rnd();
      if (u < pModes / 2) extra.push('coord=v2');
      else if (u < pModes) extra.push('baseline=sensor');
      if (/fault=/.test(c[0]) && rnd() < 0.5) extra.push('faultImpact=1');
      c[0] = [c[0], ...extra].filter(Boolean).join('&');
      if (rnd() < pKepco) c[1].kepco = 'summer';
    });
  }
}

const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const ws = new WebSocket(list.find((p) => p.type === 'page').webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise((r) => (ws.onopen = r));
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');

const BOOT = `const W = (ms) => new Promise((r) => setTimeout(r, ms)), t0 = performance.now();
    while ((!window.MA_BEMS || !MA_BEMS.ai || !MA_BEMS.snapshot || document.getElementById('loading')) && performance.now() - t0 < 40000) await W(200);
    if (!window.MA_BEMS || !MA_BEMS.ai) return { error: 'boot timeout' };`;
// KEPCO preset: the page's own buttons, as build/exp.mjs does (KEPCO button → Apply), then check the currency switched
const KEPCO = (season) => `{ const b = document.getElementById('kpBtn'), sel = document.getElementById('kpSeason');
    if (!b) return { error: 'no KEPCO button in this page' };
    if (sel) sel.value = '${season}';
    b.click();
    for (let i = 0; i < 60 && document.getElementById('dtApply').disabled; i++) await W(100);
    document.getElementById('dtApply').click(); await W(800);
    for (let i = 0; i < 30 && MA_BEMS.snapshot.currency !== '₩'; i++) await W(100);
    if (MA_BEMS.snapshot.currency !== '₩') return { error: 'KEPCO preset not applied' }; }`;

const lines = [], realq = {};
if (!REALQ && !skip) writeFileSync(out, '');
for (const [ci, [q, opt]] of configs.entries()) {
  const runSeed = Math.floor(rnd() * 1e9);              // drawn for every condition, so skip= keeps the same draws
  if (ci < skip) continue;
  await send('Page.navigate', { url: `http://127.0.0.1:5178/index.html?lang=ko&t=6&speed=0${q ? '&' + q : ''}` });
  await new Promise((r) => setTimeout(r, 1200));
  let expr;
  if (REALQ) {
    const [hh, mm] = opt.at.split(':').map(Number);
    expr = `(async () => { ${BOOT}
      const M = MA_BEMS, S = M.Sim, day0 = Math.floor(M.snapshot.T / 1440);
      S.command({ type: 'speed', value: 60 });
      for (let target = 6 * 60 + 20; target <= ${hh * 60 + mm}; target += 15) {   // the same minute steps as eval_realq_page.mjs
        while (M.snapshot.T % 1440 < target && Math.floor(M.snapshot.T / 1440) === day0) S.update(1 / 60);
        await W(0);
      }
      while (M.snapshot.T % 1440 < ${hh * 60 + mm}) S.update(1 / 60);
      S.command({ type: 'speed', value: 0 });
      M.select(null, { fly: false });
      return { scenario: M.scenario, clock: M.snapshot.clock, chat: M.ai.context('chat'), propose: M.ai.context('propose') };
    })()`;
  } else {
    expr = `(async () => { ${BOOT}
      ${opt.kepco ? KEPCO(opt.kepco) : ''}
      const M = MA_BEMS, S = M.Sim; let seed = ${runSeed};
      const rnd = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
      S.command({ type: 'speed', value: 60 });
      const out = [], day0 = Math.floor(M.snapshot.T / 1440);
      for (let target = 6 * 60 + 20; target <= 22 * 60 + 50; target += 45 + Math.floor(rnd() * 15)) {
        while (M.snapshot.T % 1440 < target && Math.floor(M.snapshot.T / 1440) === day0) S.update(1 / 60);
        const s = M.snapshot, kinds = ['building', 'zone', 'room', 'room'], kind = kinds[Math.floor(rnd() * kinds.length)];
        const ids = kind === 'building' ? Object.keys(s.buildings) : kind === 'zone' ? s.zones.map((z) => z.id) : s.rooms.filter((r) => r.name !== 'Cold room').map((r) => r.id);
        const sel = ids[Math.floor(rnd() * ids.length)];
        const rec = { clock: s.clock, chat: M.ai.context('chat'), propose: M.ai.context('propose') };
        M.selectById(kind, sel, { fly: false });
        const ex = M.ai.context('explain');
        if (ex.includes('"selected"')) rec.explain = { kind, id: sel, ctx: ex };
        M.select(null, { fly: false });
        out.push(rec);
        await W(0);
      }
      S.command({ type: 'speed', value: 0 });
      return { scenario: M.scenario, samples: out };
    })()`;
  }
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true, timeout: 600000 });
  const v = r.result && r.result.result ? r.result.result.value : null;
  const cfg = q + (opt.kepco ? '#kepco=' + opt.kepco : '');
  if (!v || v.error) { console.log('config', ci, cfg, 'FAILED', JSON.stringify(v && v.error ? v : r).slice(0, 300)); continue; }
  if (REALQ) { realq[opt.name] = { cfg: q, clock: v.clock, scenario: v.scenario, chat: v.chat, propose: v.propose }; console.log(`${opt.name} ${v.clock} ${q || 'normal'}`); continue; }
  const chunk = v.samples.map((s) => JSON.stringify({ cfg, scenario: v.scenario, ...s }));
  lines.push(...chunk);
  appendFileSync(out, chunk.join('\n') + '\n');
  console.log(`config ${ci + 1}/${configs.length} ${cfg || 'normal'}: ${v.samples.length} samples`);
}
if (REALQ) { writeFileSync(out, JSON.stringify(realq)); console.log('wrote', Object.keys(realq).length, 'realq contexts to', out); }
else console.log('wrote', lines.length, 'samples to', out);
ws.close();
