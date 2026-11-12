// node exp.mjs <name> "<query>" [days=9] [dataset=''|kepco|bdg2] [drillEveryMin=0]
// drillEveryMin > 0: inject a sensor fault every N min from day 1 01:30 and act as an oracle operator (approve real alarms,
// dismiss false ones, every 5 min); < 0: operator only, no injections (e.g. with scn=fault); 0: neither.
// Steps the MA-BEMS simulator exactly 1 sim-minute per Sim.update() call (agents negotiate every 15 sim-min, so
// bigger steps would skip rounds), independent of rendering, and saves daily KPIs + forecast (scored 1-h-ahead
// predictions and the actual slot values) + per-DR-event import + FDD results. The query takes the URL switches
// (scn, limit, ablate, baseline=tuned|sensor, seed, dr=off, coord=v2, drNotice, faultImpact, fdd=off, fddNoise).
import { writeFileSync, mkdirSync } from 'node:fs';
const [name, query = '', days = '9', dataset = '', drill = '0'] = process.argv.slice(2);
const P = { days: +days, dataset, drill: +drill, seed: 11 };
const list = await (await fetch('http://127.0.0.1:9333/json')).json();
const ws = new WebSocket(list.find((p) => p.type === 'page').webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise((r) => (ws.onopen = r));
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
// a hidden page gets its timers throttled (about one per minute after 5 min), which turns a 3-s run into many minutes:
// keep the page in front and focused. Results never depend on timing (every update is exactly one sim-minute).
await send('Page.bringToFront');
await send('Emulation.setFocusEmulationEnabled', { enabled: true });
await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: `http://127.0.0.1:5178/index.html?lang=ko&t=0.5&speed=0${query ? '&' + query : ''}` });
await new Promise((r) => setTimeout(r, 1500));

const page = `(async () => {
  const P = ${JSON.stringify(P)};
  const W = (ms) => new Promise((r) => setTimeout(r, ms));
  const Y = () => new Promise((r) => { const c = new MessageChannel(); c.port1.onmessage = () => r(); c.port2.postMessage(0); });   // yield, not throttled
  const t0 = performance.now();
  while ((!window.MA_BEMS || !MA_BEMS.snapshot || !MA_BEMS.fdd || document.getElementById('loading')) && performance.now() - t0 < 40000) await W(200);
  if (!window.MA_BEMS || !MA_BEMS.fdd) return { error: 'boot timeout' };
  const M = MA_BEMS, S = M.Sim;
  S.command({ type: 'speed', value: 0 });
  let ds = null;
  if (P.dataset) {
    document.getElementById(P.dataset === 'bdg2' ? 'kpReal' : 'kpBtn').click();
    for (let i = 0; i < 60 && document.getElementById('dtApply').disabled; i++) await W(100);
    document.getElementById('dtApply').click(); await W(800);
    ds = { dataset: M.snapshot.dataset && M.snapshot.dataset.name, currency: M.snapshot.currency };
  }
  let seed = P.seed; const rnd = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const kinds = [['stuck', 0], ['drift', 0.05], ['dropout', 0], ['drift', 0.01]];
  const endT = P.days * 1440 + 1, scored = {}, fcDaily = [], inj = [], fcY = {}, net = M.forecast.net ? { scored: {}, y: {} } : null;
  const grab = () => {                                       // forecast scores + actual slot values (the module keeps a few days)
    for (const s of M.forecast.scored()) scored[s.abs] = s;
    if (M.forecast.actuals) Object.assign(fcY, M.forecast.actuals());
    if (net) { for (const s of M.forecast.net.scored()) net.scored[s.abs] = s; Object.assign(net.y, M.forecast.net.actuals()); }
  };
  // DR events seen minute by minute: reference, mean import during the event, and the highest import in the hour before /
  // after it (pre-cooling, rebound), for both controllers
  const drEv = []; let lastT = -1, ev = null; const hist = [];
  M.Bus.on('tick', (s) => {
    if (s.T === lastT) return; lastT = s.T;
    hist.push([s.T, s.gridAgent, s.gridBase]); if (hist.length > 61) hist.shift();
    if (s.dr.active && !ev) { const pre = hist.slice(0, -1); ev = { start: s.dr.start, end: s.dr.end, shed: s.dr.shed, ref: s.dr.ref, n: 0, sA: 0, sB: 0, maxA: 0, maxB: 0, preMaxA: Math.max(...pre.map((h) => h[1])), preMaxB: Math.max(...pre.map((h) => h[2])), after: 0 }; drEv.push(ev); }
    if (ev && s.dr.active) { ev.n++; ev.sA += s.gridAgent; ev.sB += s.gridBase; ev.maxA = Math.max(ev.maxA, s.gridAgent); ev.maxB = Math.max(ev.maxB, s.gridBase); }
    else if (ev) { if (ev.after === 0) { ev.postMaxA = 0; ev.postMaxB = 0; } ev.after++; ev.postMaxA = Math.max(ev.postMaxA, s.gridAgent); ev.postMaxB = Math.max(ev.postMaxB, s.gridBase); if (ev.after >= 60) ev = null; }
  });
  let lastDay = Math.floor(M.snapshot.T / 1440), nextInj = 1440 + 90, k = 0;
  const wall = performance.now();
  while (M.snapshot.T < endT) {
    S.command({ type: 'speed', value: 60 });
    for (let i = 0; i < 120 && M.snapshot.T < endT; i++) {
      S.update(1 / 60);
      const T = M.snapshot.T;
      if (P.drill && T % 5 === 0) {
        const al = M.fdd.alarms();
        for (const r in al) if (al[r].state === 'pending') M.fdd.decide(r, !!al[r].real);   // oracle operator: approve real, dismiss false
        if (P.drill > 0 && T >= nextInj) {
          const rooms = M.snapshot.rooms.map((q) => q.id).filter((rid) => !al[rid]);
          const rid = rooms[Math.floor(rnd() * rooms.length)], [type, rate] = kinds[k++ % kinds.length];
          if (M.fdd.inject(rid, type, { rate })) inj.push({ room: rid, type: rate === 0.01 ? 'drift-slow' : type, rate, t0: T });
          nextInj += P.drill;
        }
      }
    }
    S.command({ type: 'speed', value: 0 });
    const d = Math.floor(M.snapshot.T / 1440);
    if (d !== lastDay) { fcDaily.push({ day: d - 1, acc: M.forecast.accuracy(), sum: M.forecast.summary() && M.forecast.summary().method }); grab(); lastDay = d; }
    await Y();
  }
  grab();
  const snap = M.snapshot, log = M.fdd.log();
  for (const e of drEv) { e.meanA = e.sA / Math.max(1, e.n); e.meanB = e.sB / Math.max(1, e.n); delete e.sA; delete e.sB; }
  for (const f of inj) { const hit = log.find((e) => e.room === f.room && e.real && e.T >= f.t0); f.detected = !!hit; f.delay = hit ? hit.T - f.t0 : null; f.as = hit ? hit.type : null; }
  return { name: ${JSON.stringify(name)}, query: ${JSON.stringify(query)}, ds, scenario: M.scenario, ablation: M.ablation, baselineTuned: M.baselineTuned, options: M.options || null,
    wallSec: Math.round((performance.now() - wall) / 1000),
    T: snap.T, days: snap.metrics.days, stats: snap.metrics.stats, peakLimit: snap.peakLimit, nRooms: snap.rooms.length,
    fcDaily, scored: Object.values(scored), fcY, net: net ? { scored: Object.values(net.scored), y: net.y } : null, drEvents: drEv, fdd: M.fdd.stats(), fddLog: log, inj };
})()`;
const r = await send('Runtime.evaluate', { expression: page, awaitPromise: true, returnByValue: true });
mkdirSync('results', { recursive: true });
const v = r.result && r.result.result ? r.result.result.value : null;
if (!v) { console.log('FAILED', JSON.stringify(r).slice(0, 1500)); process.exit(1); }
writeFileSync(`results/${name}.json`, JSON.stringify(v));
console.log(name, 'T=', v.T, 'days=', v.days && v.days.length, 'wall', v.wallSec, 's', v.error || '', v.ds ? JSON.stringify(v.ds) : '');
ws.close();
