// node demo/record.mjs <work dir> [dry] [only=s1,s2]
// Records the demo scenes from the live dashboard (gateway on :5178) in a headless Chrome on :9444 at 1920x960.
// Each scene follows <work dir>/timeline.json (from demo/timeline.py): the page actions of a line run when its
// narration starts. Frames come from Page.startScreencast and are written as JPEGs with their arrival time, so
// demo/assemble.py can rebuild a constant 30 fps clip of exactly the scene's length.
// "dry" takes one screenshot per action instead of recording (to check the staging quickly).
// Start Chrome first:
//   chrome --headless=new --remote-debugging-port=9444 --user-data-dir=%TEMP%\mabems-demo-9444 --hide-scrollbars --mute-audio about:blank
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [work, ...rest] = process.argv.slice(2);
const dry = rest.includes('dry');
const only = new Set((rest.find((a) => a.startsWith('only=')) || 'only=').slice(5).split(',').filter(Boolean));
const TL = JSON.parse(readFileSync(join(work, 'timeline.json'), 'utf8'));
const BASE = 'http://127.0.0.1:5178/';
const W = 1920, H = 960;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const list = await (await fetch('http://127.0.0.1:9444/json')).json();
const ws = new WebSocket(list.find((p) => p.type === 'page').webSocketDebuggerUrl);
let id = 0; const pending = new Map(), handlers = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  else if (m.method) for (const h of handlers) h(m);
};
await new Promise((r) => (ws.onopen = r));
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.result && r.result.exceptionDetails) console.log('  ! js error:', JSON.stringify(r.result.exceptionDetails).slice(0, 300));
  return r.result && r.result.result ? r.result.result.value : undefined;
};
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });

// cursor, click ripple and spotlight drawn into the page (headless has no visible pointer)
const OVERLAY = `(() => {
  if (window.__demo) return 'ok';
  const st = document.createElement('style');
  st.textContent = \`#__cur{position:fixed;left:0;top:0;width:30px;height:30px;z-index:2147483647;pointer-events:none;transition:transform .75s cubic-bezier(.3,.7,.2,1);filter:drop-shadow(0 2px 3px rgba(0,0,0,.4))}
    .__rip{position:fixed;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;border:3px solid #7B6CF6;z-index:2147483646;pointer-events:none;animation:__rip .65s ease-out forwards}
    @keyframes __rip{to{transform:scale(3.4);opacity:0}}
    .__hl{position:fixed;z-index:2147483645;pointer-events:none;border:3px solid #7B6CF6;border-radius:14px;box-shadow:0 0 0 4000px rgba(18,14,40,.30),0 0 22px rgba(123,108,246,.75);transition:opacity .45s;opacity:0}
    #cineBar,.hint{display:none!important}\`;
  document.head.appendChild(st);
  for (const e of document.querySelectorAll('body *')) if (e.children.length < 3 && /더블클릭하면|조작법$/.test((e.textContent || '').trim()) && e.getBoundingClientRect().top > innerHeight * 0.8) e.style.display = 'none';
  const c = document.createElement('div'); c.id = '__cur';
  c.innerHTML = '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M5 2.5l14.5 8.6-6.6 1.5-3.6 6.4z" fill="#fff" stroke="#1d1b2c" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  let x = innerWidth * 0.62, y = innerHeight * 0.58;
  const put = () => { c.style.transform = 'translate(' + (x - 4) + 'px,' + (y - 3) + 'px)'; };
  put();
  const el = (s) => (typeof s === 'string' ? document.querySelector(s) : s);
  const mid = (e) => { const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
  window.__demo = {
    move(tx, ty) { x = tx; y = ty; put(); },
    moveTo(s) { const e = el(s); if (!e) return false; const [a, b] = mid(e); this.move(a, b); return true; },
    async click(s) {
      const e = el(s); if (!e) return false;
      e.scrollIntoView({ block: 'nearest' }); this.moveTo(e); await new Promise((r) => setTimeout(r, 800));
      const [a, b] = mid(e), rp = document.createElement('div'); rp.className = '__rip'; rp.style.left = a + 'px'; rp.style.top = b + 'px';
      document.body.appendChild(rp); setTimeout(() => rp.remove(), 750); e.click(); return true;
    },
    highlight(s, ms = 3000, pad = 6) {
      const e = el(s); if (!e) return false; const r = e.getBoundingClientRect(), h = document.createElement('div'); h.className = '__hl';
      Object.assign(h.style, { left: (r.left - pad) + 'px', top: (r.top - pad) + 'px', width: (r.width + 2 * pad) + 'px', height: (r.height + 2 * pad) + 'px' });
      document.body.appendChild(h); requestAnimationFrame(() => (h.style.opacity = 1));
      setTimeout(() => { h.style.opacity = 0; setTimeout(() => h.remove(), 500); }, ms); return true;
    },
    async typeAsk(text, cps = 13) {
      const inp = document.getElementById('aiInput'); await this.click(inp); inp.focus(); inp.value = '';
      for (const ch of text) { inp.value += ch; await new Promise((r) => setTimeout(r, 1000 / cps)); }
      await new Promise((r) => setTimeout(r, 350)); this.moveTo('#aiSend'); await new Promise((r) => setTimeout(r, 450));
      const form = document.getElementById('aiForm');   // submitting while an answer is pending would abort it
      for (let i = 0; i < 80 && form.classList.contains('busy'); i++) await new Promise((r) => setTimeout(r, 250));
      form.requestSubmit(); return true;
    },
    async scroll(s, px, ms) {
      const e = el(s); if (!e) return false; const y0 = e.scrollTop, t0 = performance.now();
      await new Promise((done) => { const step = (t) => { const k = Math.min(1, (t - t0) / ms); e.scrollTop = y0 + px * (k < .5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2); k < 1 ? requestAnimationFrame(step) : done(); }; requestAnimationFrame(step); });
      return true;
    },
  };
  return 'ok';
})()`;

// page actions named in demo/script.json
const ACT = {
  cine: `document.getElementById('cineBtn').click()`,
  stopCine: `(document.getElementById('cineStop') && !document.getElementById('cineBar').classList.contains('hide')) ? document.getElementById('cineStop').click() : 0`,
  home: `__demo.click('#navDock [data-nav="home"]')`,   // the nav dock's reset-view button (camera back to the campus overview)
  hlKpis: `__demo.moveTo('#kpis'), __demo.highlight('#kpis', 6500, 8)`,
  hlCompare: `(async () => { __demo.highlight('#kpis .kpi:nth-child(4)', 3200, 8); __demo.moveTo('#kpis .kpi:nth-child(4)'); await new Promise((r) => setTimeout(r, 3600)); __demo.highlight('#modeSeg', 3000, 6); __demo.moveTo('#modeSeg'); })()`,
  hlAgents: `__demo.moveTo('#agents'), __demo.highlight('#agents', 5200, 8)`,
  hlLog: `__demo.moveTo('#log'), __demo.highlight('#log', 6500, 6)`,
  selectB1: `__demo.move(innerWidth * 0.44, innerHeight * 0.48), MA_BEMS.selectById('building', 'B1', { fly: true })`,
  selectZone: `MA_BEMS.selectById('zone', 'B1-F5', { fly: false })`,
  clearSel: `MA_BEMS.select(null, { fly: true })`,
  openScn: `__demo.click('#scnBtn')`,
  hlAlerts: `__demo.moveTo('#drBanner'), __demo.highlight('#drBanner', 4200, 8)`,
  aiLocal: `(() => { const s = document.getElementById('aiTier'); s.value = 'local'; s.dispatchEvent(new Event('change')); return s.value; })()`,
  openAI: `__demo.click('#aiBtn')`,
  askExpensive: `__demo.click('#aiMsgs [data-ask="오늘 가장 비싼 시간대는?"]')`,
  askBuilding: `__demo.typeAsk('어느 건물이 제일 많이 써?')`,
  askLights: `__demo.typeAsk('빈 방 조명 꺼 줘')`,
  applyFirst: `(() => { const g = [...document.querySelectorAll('#aiMsgs .ai-props')].pop(); const b = g && g.querySelector('button[data-i]'); return b ? __demo.click(b) : false; })()`,
  openEvidence: `(async () => { await __demo.click('#insightsBtn'); await new Promise((r) => setTimeout(r, 1500)); return __demo.click('#evTab-proof'); })()`,
  scrollEvidence: `(() => { const p = document.getElementById('evPane-proof'); let e = p; while (e && e.scrollHeight <= e.clientHeight + 5) e = e.parentElement; return e ? __demo.scroll(e, 520, 3600) : false; })()`,
  closeModal: `__demo.click('.ev-x')`,
};

const ready = `(async () => { const t0 = performance.now();
  while ((!window.MA_BEMS || !MA_BEMS.snapshot || !MA_BEMS.ai || document.getElementById('loading')) && performance.now() - t0 < 60000) await new Promise((r) => setTimeout(r, 250));
  return !!(window.MA_BEMS && MA_BEMS.snapshot); })()`;
const act = (name) => { if (!ACT[name]) { console.log('  ! unknown action', name); return Promise.resolve(); } return js(ACT[name]); };

for (const sc of TL.scenes) {
  if (only.size && !only.has(sc.id)) continue;
  console.log(`[${sc.id}] ${sc.duration}s`);
  if (sc.url) {
    await send('Page.navigate', { url: BASE + sc.url });
    await sleep(1500);
    console.log('  ready', await js(ready));
    await sleep(3500);                                     // let the 3D scene and the first charts settle
  }
  await js(OVERLAY);
  for (const a of sc.setup) { await act(a); await sleep(400); }
  await sleep(900);
  const dir = join(work, 'frames', sc.id); mkdirSync(dir, { recursive: true });
  const frames = []; let n = 0, t0 = 0;
  const timers = [];
  const cues = [];
  for (const ln of sc.lines) {
    for (const a of ln.do) cues.push([ln.start, a]);
    for (const [dt, a] of ln.after) cues.push([ln.start + dt, a]);
  }
  if (dry) {
    let k = 0;
    for (const [at, a] of cues.sort((p, q) => p[0] - q[0])) {
      await act(a); await sleep(1800);
      const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 70 });
      writeFileSync(join(dir, `dry_${String(++k).padStart(2, '0')}_${a}.jpg`), Buffer.from(shot.result.data, 'base64'));
    }
    const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 70 });
    writeFileSync(join(dir, `dry_end.jpg`), Buffer.from(shot.result.data, 'base64'));
    continue;
  }
  const onFrame = (m) => {
    if (m.method !== 'Page.screencastFrame') return;
    const now = Date.now() / 1000;
    if (!t0) t0 = now;
    const file = `f${String(++n).padStart(5, '0')}.jpg`;
    writeFileSync(join(dir, file), Buffer.from(m.params.data, 'base64'));
    frames.push({ file, t: +(now - t0).toFixed(3) });
    send('Page.screencastFrameAck', { sessionId: m.params.sessionId });
  };
  handlers.push(onFrame);
  await send('Page.startScreencast', { format: 'jpeg', quality: 88, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
  const start = Date.now();
  for (const [at, a] of cues) timers.push(setTimeout(() => act(a), at * 1000));
  await sleep(sc.duration * 1000 + 400);
  timers.forEach(clearTimeout);
  await send('Page.stopScreencast');
  handlers.splice(handlers.indexOf(onFrame), 1);
  const span = (Date.now() - start) / 1000;
  writeFileSync(join(dir, 'frames.json'), JSON.stringify({ duration: sc.duration, frames }, null, 0));
  console.log(`  ${frames.length} frames in ${span.toFixed(1)} s (${(frames.length / span).toFixed(1)} fps)`);
}
ws.close();
