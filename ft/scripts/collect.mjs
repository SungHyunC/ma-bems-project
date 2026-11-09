// node collect.mjs <out.jsonl> <seed> <nRandom> [presets=1]
// Runs the MA-BEMS simulator (headless Chrome on :9333, page from the gateway on :5178) under the scenario presets and
// random custom conditions, and records the exact contexts the AI panel sends (chat/brief, propose, explain with a
// random selection) every ~50 sim-minutes from 06:20 to 22:50. These are the inputs of the fine-tuning data.
import { writeFileSync } from 'node:fs';
const [out = 'samples.jsonl', seedArg = '1', nRandom = '20', presets = '1'] = process.argv.slice(2);
let seed = +seedArg;
const rnd = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
const pick = (a) => a[Math.floor(rnd() * a.length)];
const r1 = (x) => Math.round(x * 10) / 10;

const configs = [];
if (presets === '1') for (const id of ['', 'heatwave', 'cloudy', 'dr', 'tight', 'evrush', 'holiday', 'fault', 'worst']) configs.push(id ? `scn=${id}` : '');
for (let i = 0; i < +nRandom; i++) {
  const p = { scn: 'custom', dT: Math.round(-3 + rnd() * 10), sun: r1(0.2 + rnd() * 0.9), occ: r1(0.2 + rnd() * 1.1), limit: pick([850, 900, 950, 1000, 1000, 1100]), ev: Math.floor(rnd() * 8) };
  if (rnd() < 0.5) { const m = 13 * 60 + Math.floor(rnd() * 20) * 15; Object.assign(p, { drAt: `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`, drShed: 150 + Math.floor(rnd() * 21) * 10, drMin: pick([30, 45, 60, 90]) }); }
  if (rnd() < 0.15) p.fault = pick(['stuck', 'drift', 'dropout']);
  configs.push(new URLSearchParams(p).toString());
}

const list = await (await fetch('http://127.0.0.1:9333/json')).json();
const ws = new WebSocket(list.find((p) => p.type === 'page').webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise((r) => (ws.onopen = r));
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');

const lines = [];
for (const [ci, q] of configs.entries()) {
  await send('Page.navigate', { url: `http://127.0.0.1:5178/index.html?lang=ko&t=6&speed=0${q ? '&' + q : ''}` });
  await new Promise((r) => setTimeout(r, 1200));
  const expr = `(async () => {
    const W = (ms) => new Promise((r) => setTimeout(r, ms)), t0 = performance.now();
    while ((!window.MA_BEMS || !MA_BEMS.ai || !MA_BEMS.snapshot || document.getElementById('loading')) && performance.now() - t0 < 40000) await W(200);
    if (!window.MA_BEMS || !MA_BEMS.ai) return { error: 'boot timeout' };
    const M = MA_BEMS, S = M.Sim; let seed = ${Math.floor(rnd() * 1e9)};
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
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  const v = r.result && r.result.result ? r.result.result.value : null;
  if (!v || v.error) { console.log('config', ci, 'FAILED', JSON.stringify(r).slice(0, 300)); continue; }
  for (const s of v.samples) lines.push(JSON.stringify({ cfg: q, scenario: v.scenario, ...s }));
  console.log(`config ${ci + 1}/${configs.length} ${q || 'normal'}: ${v.samples.length} samples`);
}
writeFileSync(out, lines.join('\n') + '\n');
console.log('wrote', lines.length, 'samples to', out);
ws.close();
