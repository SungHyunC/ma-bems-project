// node ft/scripts/eval_realq_page.mjs <out.json> [only=id,id]
// The ft/data/realq.json questions asked through the page itself: headless Chrome on :9333 opens the dashboard from the
// gateway (:5178), runs each context's scenario to its clock, and types every question into the AI tab's code path
// (MA_BEMS.ai.ask), so the page's own context building, chat/proposal routing and the gateway are all exercised.
// Start Chrome first:  chrome --headless=new --remote-debugging-port=9333 --user-data-dir=%TEMP%\mabems-cdp-9333 about:blank
// Checks match ft/scripts/eval_realq.py (the gateway-only version, used for the "before" run).
import { readFileSync, writeFileSync } from 'node:fs';
const [out = 'realq_page.json', onlyArg = ''] = process.argv.slice(2);
const only = new Set(onlyArg.replace(/^only=/, '').split(',').filter(Boolean));
const bank = JSON.parse(readFileSync(new URL('../data/realq.json', import.meta.url), 'utf8'));
const CLAIMS_DONE = /(껐습니다|꺼 ?드렸|꺼졌습니다|적용했습니다|적용되었습니다|적용 완료|변경했습니다|변경되었습니다|조정했습니다|조정되었습니다|올렸습니다|낮췄습니다|내렸습니다|설정했습니다|실행했습니다|완료했습니다|완료되었습니다|I have (turned|switched|set|changed|applied))/;
// where each context of the bank came from (ft/data/samples_train.jsonl): scenario query and clock
const WHERE = { N14: ['', '14:36'], N22: ['', '22:19'], DR: ['scn=dr', '16:31'], FAULT: ['scn=fault', '14:52'], WORST: ['scn=worst', '17:10'] };

const list = await (await fetch('http://127.0.0.1:9333/json')).json();
const ws = new WebSocket(list.find((p) => p.type === 'page').webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise((r) => (ws.onopen = r));
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true, timeout: 600000 });
  if (r.result && r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400));
  return r.result && r.result.result ? r.result.result.value : null;
};
await send('Page.enable');

function checks(item, text, chk, task, json) {
  const fails = [], hangul = (text.match(/[가-힣]/g) || []).length, letters = (text.match(/[A-Za-z가-힣]/g) || []).length;
  if (item.lang === 'en') { if (hangul > 0.1 * Math.max(1, letters)) fails.push('answered in Korean'); }
  else if (!hangul) fails.push('not in Korean');
  for (const rx of item.need || []) if (!new RegExp(rx).test(text)) fails.push(`missing /${rx}/`);
  for (const key of ['needAny', 'needAny2']) if (item[key] && !item[key].some((rx) => new RegExp(rx).test(text))) fails.push(`none of ${JSON.stringify(item[key])}`);
  for (const rx of item.forbid || []) { const m = (rx === 'claimsDone' ? CLAIMS_DONE : new RegExp(rx)).exec(text); if (m) fails.push(`forbidden "${m[0]}"`); }
  if (item.maxLines) { const n = text.split('\n').filter((l) => l.trim()).length; if (n > item.maxLines) fails.push(`${n} lines > ${item.maxLines}`); }
  if (chk && !chk.ok) fails.push('number check: ' + (chk.unmatched || []).join(', '));
  if (item.route && task !== item.route && !(item.route === 'propose' && task === 'command')) fails.push(`routed to ${task}, expected ${item.route}`);
  if (item.act && (task === 'propose' || task === 'command') && !((json && json.actions) || []).some((a) => new RegExp(item.act).test(`${a.type} ${a.target} ${a.value}`))) fails.push(`no action like /${item.act}/`);
  return fails;
}

const results = [], contexts = {};
const groups = {};
for (const it of bank.items) if (!only.size || only.has(it.id)) (groups[it.ctx] = groups[it.ctx] || []).push(it);
for (const [ctx, items] of Object.entries(groups)) {
  const [q, clock] = WHERE[ctx], [hh, mm] = clock.split(':').map(Number);
  await send('Page.navigate', { url: `http://127.0.0.1:5178/index.html?lang=ko&t=6&speed=0${q ? '&' + q : ''}` });
  await new Promise((r) => setTimeout(r, 1200));
  const ready = await evaluate(`(async () => {
    const W = (ms) => new Promise((r) => setTimeout(r, ms)), t0 = performance.now();
    while ((!window.MA_BEMS || !MA_BEMS.ai || !MA_BEMS.ai.ask || !MA_BEMS.snapshot || document.getElementById('loading')) && performance.now() - t0 < 40000) await W(200);
    if (!window.MA_BEMS || !MA_BEMS.ai || !MA_BEMS.ai.ask) return 'boot timeout';
    const M = MA_BEMS, S = M.Sim, day0 = Math.floor(M.snapshot.T / 1440);
    S.command({ type: 'speed', value: 60 });
    for (let target = 6 * 60 + 20; target <= ${hh * 60 + mm}; target += 15) {   // same path as collect.mjs: minute steps
      while (M.snapshot.T % 1440 < target && Math.floor(M.snapshot.T / 1440) === day0) S.update(1 / 60);
      await W(0);
    }
    while (M.snapshot.T % 1440 < ${hh * 60 + mm}) S.update(1 / 60);
    S.command({ type: 'speed', value: 0 });
    for (let i = 0; i < 50 && !(await M.ai.online()); i++) await W(200);
    return 'ok ' + M.snapshot.clock;
  })()`);
  console.log(`[${ctx}] ${ready}`);
  contexts[ctx] = await evaluate('MA_BEMS.ai.context("chat")');
  for (const item of items) {
    const turns = (item.history || []).map((h) => h.content).concat([item.q]);
    const t0 = Date.now();
    let r;
    try {
      r = await evaluate(`(async () => { const A = MA_BEMS.ai; A.reset(); let last = null;
        for (const t of ${JSON.stringify(turns)}) last = await A.ask(t, { tier: 'local' });
        return last; })()`);
    } catch (e) { r = { error: String(e.message || e) }; }
    const sec = (Date.now() - t0) / 1000;
    const text = r && !r.error ? (r.task === 'propose' || r.task === 'command' ? [r.json && r.json.summary, ...((r.json && r.json.actions) || []).map((a) => `${a.type} ${a.target} ${a.value}: ${a.expected_effect || ''} / ${a.reason || ''}`)].filter(Boolean).join('\n') : r.text || '') : '';
    const fails = !r || r.error ? ['error: ' + (r && r.error)] : checks(item, text, r.check, r.task, r.json);
    const rec = { id: item.id, cat: item.cat, ctx, q: item.q, expect: item.expect || '', task: r && r.task, answer: text, pass: !fails.length, fails, seconds: +sec.toFixed(1),
      model: r && r.model, tier: r && r.tier, check: r && r.check, valid: r && r.valid };
    results.push(rec);
    console.log(`${rec.pass ? 'ok  ' : 'FAIL'} ${item.id.padEnd(14)} ${sec.toFixed(1).padStart(5)}s ${(r && r.task) || ''} ${fails.join('; ').slice(0, 150)}`);
  }
}
const n = results.length, by = {};
for (const r of results) { const c = by[r.cat] || (by[r.cat] = [0, 0]); c[0] += r.pass ? 1 : 0; c[1]++; }
const secs = results.map((r) => r.seconds).sort((a, b) => a - b);
const summary = { n, pass: results.filter((r) => r.pass).length, by_cat: by, median_s: secs[Math.floor(n / 2)] };
writeFileSync(out, JSON.stringify({ summary, results, contexts }, null, 1));
console.log(`pass ${summary.pass}/${n}, median ${summary.median_s}s -> ${out}`);
ws.close();
