// node llm.mjs → results/llm.json: latency, tokens and guardrail outcome per AI-assistant task, local vs Claude,
// using the exact context the dashboard sends (MA_BEMS.ai.context) at a peak-hour state (day 1, 14:30).
import { writeFileSync, mkdirSync } from 'node:fs';
const list = await (await fetch('http://127.0.0.1:9333/json')).json();
const ws = new WebSocket(list.find((p) => p.type === 'page').webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise((r) => (ws.onopen = r));
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Page.navigate', { url: 'http://127.0.0.1:5178/index.html?lang=ko&t=0.5' });
await new Promise((r) => setTimeout(r, 1500));
const page = `(async () => {
  const W = (ms) => new Promise((r) => setTimeout(r, ms)), t0 = performance.now();
  while ((!window.MA_BEMS || !MA_BEMS.ai || !MA_BEMS.snapshot || document.getElementById('loading')) && performance.now() - t0 < 40000) await W(200);
  const M = MA_BEMS, S = M.Sim;
  S.command({ type: 'speed', value: 60 });
  while (M.snapshot.T < 1440 + 870) { for (let i = 0; i < 60; i++) S.update(1 / 60); await W(0); }
  S.command({ type: 'speed', value: 0 });
  M.selectById('building', 'B1'); await W(600);
  const Q = { brief: '지금 캠퍼스 운영 상황을 브리핑해 주세요.', chat: '지금 피크 위험은 어느 정도이고, ESS는 왜 지금처럼 동작하나요?', explain: '선택한 B1 건물 상태를 설명해 주세요.', propose: '피크·비용·쾌적을 개선할 제어 조치를 제안해 주세요.' };
  async function ask(task, tier) {
    const context = M.ai.context(task), body = { task, tier, messages: [{ role: 'user', content: Q[task] }], context };
    const t = performance.now(), res = await fetch('/api/llm/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const rd = res.body.getReader(), dec = new TextDecoder(); let buf = '', done = null, err = null, esc = [], first = null;
    for (;;) { const { value, done: d } = await rd.read(); if (d) break; buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf('\\n\\n')) >= 0) { const ch = buf.slice(0, i); buf = buf.slice(i + 2); let ev = '', data = '';
        for (const ln of ch.split('\\n')) { if (ln.startsWith('event: ')) ev = ln.slice(7); else if (ln.startsWith('data: ')) data += ln.slice(6); }
        if (!data) continue; const o = JSON.parse(data);
        if (ev === 'delta' && first == null) first = performance.now() - t;
        if (ev === 'done') done = o; else if (ev === 'error') err = o.message; else if (ev === 'escalate') esc.push(o.from + '→' + o.to + ': ' + o.reason); } }
    const acts = done && done.json && Array.isArray(done.json.actions) ? done.json.actions : null;
    return { task, tier, ctxChars: context.length, wallMs: Math.round(performance.now() - t), firstTokenMs: first && Math.round(first), err, esc,
      servedTier: done && done.tier, model: done && done.model, latencyMs: done && done.latency_ms, usage: done && done.usage,
      check: done && done.check ? { ok: done.check.ok, unmatched: done.check.unmatched } : null,
      actions: acts ? acts.map((a) => ({ type: a.type, target: a.target, valid: !!a.target && context.includes(String(a.target)) })) : null,
      text: done && done.text ? done.text.slice(0, 700) : null };
  }
  const out = [];
  for (const task of ['brief', 'chat', 'explain', 'propose']) { out.push(await ask(task, 'local')); out.push(await ask(task, 'api')); }
  out.push(Object.assign(await ask('brief', 'api'), { note: 'repeat (cache read)' }));
  out.push(Object.assign(await ask('chat', 'auto'), { note: 'default routing (local first)' }));
  return { at: M.snapshot.T, rows: out, status: await (await fetch('/api/llm/status')).json() };
})()`;
const r = await send('Runtime.evaluate', { expression: page, awaitPromise: true, returnByValue: true });
mkdirSync('results', { recursive: true });
const v = r.result && r.result.result ? r.result.result.value : null;
if (!v) { console.log('FAILED', JSON.stringify(r).slice(0, 1500)); process.exit(1); }
writeFileSync('results/llm.json', JSON.stringify(v, null, 1));
for (const x of v.rows) console.log(x.task.padEnd(8), x.tier.padEnd(6), '→', String(x.servedTier).padEnd(6), String(x.latencyMs).padStart(6), 'ms', 'first', x.firstTokenMs, JSON.stringify(x.usage), x.check ? (x.check.ok ? 'numbers✓' : 'numbers✗ ' + x.check.unmatched.join(',')) : '', x.actions ? 'actions ' + x.actions.length + ' valid ' + x.actions.filter((a) => a.valid).length : '', x.err || '', x.esc.join(' | '), x.note || '');
ws.close();
