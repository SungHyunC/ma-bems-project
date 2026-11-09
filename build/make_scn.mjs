// node make_scn.mjs → KPIs of the scenario runs (results/scn_*.json from exp.mjs) written into scn_module.js
// (SCN_RESULTS) and results/scn_summary.json, plus a printed table. Same method as analyze.mjs: days 1–8 scored.
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
const T975 = { 2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262 };
const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
const ci = (a) => { const n = a.length, m = mean(a), sd = Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / Math.max(1, n - 1)); return { mean: +m.toFixed(4), ci: +((T975[n] || 1.96) * sd / Math.sqrt(n)).toFixed(4) }; };
const pct = (b, a) => (b > 0 ? 100 * (b - a) / b : 0);
const r = (x, d = 1) => Math.round(x * 10 ** d) / 10 ** d;
const IDS = ['normal', 'heatwave', 'cloudy', 'dr', 'tight', 'evrush', 'holiday', 'fault', 'worst'];
const runs = {};
for (const id of IDS) {
  const v = JSON.parse(readFileSync(`results/scn_${id}.json`, 'utf8'));
  const D = v.days.filter((d) => d.day >= 2).map((d) => ({ A: d.agent, B: d.baseline }));   // day index 1 = warm-up day 0 archived at midnight
  const avg = (f) => mean(D.map(f)), dr = D.filter((d) => d.B.drRequestedKWh > 0);
  const out = {
    n: D.length, limit: v.peakLimit, costSave: ci(D.map((d) => pct(d.B.cost, d.A.cost))), energySave: ci(D.map((d) => pct(d.B.energyKWh, d.A.energyKWh))),
    costA: r(avg((d) => d.A.cost), 0), costB: r(avg((d) => d.B.cost), 0), peakA: r(avg((d) => d.A.peakKW), 0), peakB: r(avg((d) => d.B.peakKW), 0),
    overMinA: r(avg((d) => d.A.minutesOverLimit)), overMinB: r(avg((d) => d.B.minutesOverLimit)), overKWhA: r(avg((d) => d.A.overLimitKWh)), overKWhB: r(avg((d) => d.B.overLimitKWh)),
    comfortA: r(avg((d) => d.A.comfortPct)), comfortB: r(avg((d) => d.B.comfortPct)),
    drA: dr.length ? r(mean(dr.map((d) => d.A.drPct)), 0) : null, drB: dr.length ? r(mean(dr.map((d) => d.B.drPct)), 0) : null,
    evA: r(avg((d) => d.A.evMetPct), 0), evB: r(avg((d) => d.B.evMetPct), 0), pvA: r(avg((d) => d.A.pvSelfPct), 0), pvB: r(avg((d) => d.B.pvSelfPct), 0),
    vacA: r(avg((d) => d.A.vacantRoomKWh), 0), vacB: r(avg((d) => d.B.vacantRoomKWh), 0), scenario: v.scenario,
  };
  if (id === 'fault') {
    const st = v.fdd || {}, by = (st.byType && st.byType.stuck) || {};
    out.injected = st.injected || 0; out.detected = st.detected || 0; out.falseAlarms = st.falseAlarms || 0;
    out.delay = by.delays && by.delays.length ? by.delays[0] : null;
  }
  runs[id] = out;
}
const res = { date: new Date().toISOString().slice(0, 10), days: 8, runs };
writeFileSync('results/scn_summary.json', JSON.stringify(res, null, 1));
const mod = !existsSync('scn_module.js') ? '' : readFileSync('scn_module.js', 'utf8').replace(/\/\*SCN_RESULTS\*\/[\s\S]*?\/\*END\*\//, `/*SCN_RESULTS*/${JSON.stringify(res)}/*END*/`);
if (existsSync('scn_module.js')) writeFileSync('scn_module.js', mod);   // the dashboard module lives in the build folder
console.log('scenario   cost save        peak A/B kW   over-limit min/day A/B   comfort A/B   DR A/B   EV A/B   PV A/B   empty kWh A/B');
for (const id of IDS) {
  const k = runs[id];
  console.log(`${id.padEnd(9)} ${String(r(k.costSave.mean)).padStart(5)} ±${String(r(k.costSave.ci)).padEnd(5)}   ${String(k.peakA).padStart(5)}/${String(k.peakB).padEnd(5)}   ${String(k.overMinA).padStart(6)}/${String(k.overMinB).padEnd(6)}            ${k.comfortA}/${k.comfortB}   ${k.drA ?? '-'}/${k.drB ?? '-'}   ${k.evA}/${k.evB}   ${k.pvA}/${k.pvB}   ${k.vacA}/${k.vacB}` + (id === 'fault' ? `   fdd ${k.detected}/${k.injected} delay ${k.delay}` : ''));
}
