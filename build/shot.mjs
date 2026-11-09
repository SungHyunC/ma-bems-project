// node shot.mjs <port> <url> <out.png> <waitMs> [js] — navigate the first page target, run js after boot, screenshot
import { writeFileSync } from 'node:fs';
const [port, url, out, wait = 4000, js = ''] = process.argv.slice(2);
const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const ws = new WebSocket(list.find((p) => p.type === 'page').webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise((r) => (ws.onopen = r));
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: +(process.env.W || 1440), height: +(process.env.H || 900), deviceScaleFactor: +(process.env.DSF || 1), mobile: false });
await send('Page.navigate', { url }); await new Promise((r) => setTimeout(r, 1500));
const r = await send('Runtime.evaluate', { expression: `(async () => { const t0 = performance.now(); await new Promise(r => setTimeout(r, 600)); while ((!document.getElementById('scene') || document.getElementById('loading')) && performance.now() - t0 < 30000) await new Promise(r => setTimeout(r, 200)); ${js}; await new Promise(r => setTimeout(r, ${+wait})); return document.getElementById('err') ? document.getElementById('err').textContent : ''; })()`, awaitPromise: true, returnByValue: true });
const shot = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
console.log(out, 'err:', JSON.stringify(r.result && r.result.exceptionDetails ? r.result.exceptionDetails.exception && r.result.exceptionDetails.exception.description : r.result && r.result.result ? r.result.result.value : r).slice(0, 400));
ws.close();
