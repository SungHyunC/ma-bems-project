// node analyze.mjs → results/summary.json + a printed table. Days 1–8 (day 0 is the warm-up day).
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
const load = (n) => JSON.parse(readFileSync(`results/${n}.json`, 'utf8'));
const T975 = { 2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262 };
const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
const ci = (a) => { const n = a.length, m = mean(a), sd = Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / Math.max(1, n - 1)); return { mean: m, ci: (T975[n] || 1.96) * sd / Math.sqrt(n), sd, n }; };
const r1 = (x) => Math.round(x * 10) / 10, r2 = (x) => Math.round(x * 100) / 100;
const days = (v) => v.days.filter((d) => d.day >= 2).map((d) => ({ day: d.day - 1, A: d.agent, B: d.baseline, cur: d.currency }));
const pct = (b, a) => (b > 0 ? 100 * (b - a) / b : 0);

function kpis(v) {
  const D = days(v);
  const cs = D.map((d) => pct(d.B.cost, d.A.cost)), es = D.map((d) => pct(d.B.energyKWh, d.A.energyKWh)), ps = D.map((d) => pct(d.B.peakKW, d.A.peakKW));
  const sum = (f) => D.reduce((s, d) => s + f(d), 0), avg = (f) => mean(D.map(f));
  const dr = D.filter((d) => d.B.drRequestedKWh > 0);
  return {
    name: v.name, n: D.length, currency: D[0].cur, costSave: ci(cs), energySave: ci(es), peakCut: ci(ps), _cs: cs,
    costA: avg((d) => d.A.cost), costB: avg((d) => d.B.cost), kwhA: avg((d) => d.A.energyKWh), kwhB: avg((d) => d.B.energyKWh),
    peakA: avg((d) => d.A.peakKW), peakB: avg((d) => d.B.peakKW), limit: v.peakLimit,
    overMinA: sum((d) => d.A.minutesOverLimit), overMinB: sum((d) => d.B.minutesOverLimit), overKWhA: sum((d) => d.A.overLimitKWh), overKWhB: sum((d) => d.B.overLimitKWh),
    comfortA: avg((d) => d.A.comfortPct), comfortB: avg((d) => d.B.comfortPct), discA: sum((d) => d.A.discomfortDegH), discB: sum((d) => d.B.discomfortDegH),
    evA: avg((d) => d.A.evMetPct), evB: avg((d) => d.B.evMetPct), pvA: avg((d) => d.A.pvSelfPct), pvB: avg((d) => d.B.pvSelfPct),
    co2Save: ci(D.map((d) => pct(d.B.co2Kg, d.A.co2Kg))), co2A: avg((d) => d.A.co2Kg), co2B: avg((d) => d.B.co2Kg),
    cyclesA: avg((d) => d.A.essCycles), cyclesB: avg((d) => d.B.essCycles), lfA: avg((d) => d.A.loadFactor), lfB: avg((d) => d.B.loadFactor),
    drDays: dr.length, drA: dr.length ? mean(dr.map((d) => d.A.drPct)) : null, drB: dr.length ? mean(dr.map((d) => d.B.drPct)) : null,
    vacA: avg((d) => d.A.vacantRoomKWh), vacB: avg((d) => d.B.vacantRoomKWh),
  };
}
const names = ['full', 'tuned', 'ablate_COORD', 'ablate_ESS', 'ablate_EV', 'ablate_ROOM', 'ablate_HVAC', 'ablate_LIGHT', 'kepco', 'bdg2'].filter((n) => existsSync(`results/${n}.json`));
const K = Object.fromEntries(names.map((n) => [n, kpis(load(n))]));

// determinism: the same configuration twice must give identical daily costs
const f1 = load('full'), f2 = load('full_repeat');
const deterministic = days(f1).every((d, i) => Math.abs(d.A.cost - days(f2)[i].A.cost) < 1e-9 && Math.abs(d.B.cost - days(f2)[i].B.cost) < 1e-9);

// ablations: contribution = full saving − ablated saving, paired by day
const abl = {};
for (const n of names.filter((n) => n.startsWith('ablate_'))) abl[n.slice(7)] = ci(K.full._cs.map((x, i) => x - K[n]._cs[i]));

// forecast accuracy (1-h-ahead, 15-min slots) vs persistence (value 1 h earlier), days 1–8
const sc = Object.fromEntries(f1.scored.map((s) => [s.abs, s]));
const slots = Object.values(sc).filter((s) => s.abs >= 96 && s.abs < 9 * 96 && sc[s.abs - 4]);
const acc = (pairs) => { const n = pairs.length, my = mean(pairs.map((p) => p.y)); const rmse = Math.sqrt(mean(pairs.map((p) => (p.p - p.y) ** 2))); return { n, cvrmse: 100 * rmse / my, nmbe: 100 * mean(pairs.map((p) => p.p - p.y)) / my, rmse }; };
const fModel = acc(slots.map((s) => ({ y: s.y, p: s.p }))), fPers = acc(slots.map((s) => ({ y: s.y, p: sc[s.abs - 4].y })));
const perDayCV = [...new Set(slots.map((s) => Math.floor(s.abs / 96)))].map((d) => acc(slots.filter((s) => Math.floor(s.abs / 96) === d).map((s) => ({ y: s.y, p: s.p }))).cvrmse);
const forecast = { model: fModel, persistence: fPers, skill: 1 - fModel.rmse / fPers.rmse, dailyCV: ci(perDayCV), methods: f1.fcDaily.map((d) => d.sum) };

// FDD: false alarms in normal operation (full run, no faults) and the drill (one fault every 3 h, oracle approvals)
const dr = load('drill');
const byType = {};
for (const f of dr.inj) { const k = f.type, b = byType[k] || (byType[k] = { n: 0, det: 0, d: [], censored: 0 }); b.n++; if (f.detected) { b.det++; b.d.push(f.delay); } else if (dr.T - f.t0 < 600) b.censored++; }
for (const k in byType) { const b = byType[k], d = b.d.sort((x, y) => x - y); Object.assign(b, { median: d[Math.floor((d.length - 1) / 2)], max: d[d.length - 1] }); delete b.d; }
const fdd = { normalFalseAlarms: f1.fddLog.filter((e) => !e.real).length, roomDays: f1.nRooms * Math.round(f1.T / 1440), rooms: f1.nRooms,
  drill: { injected: dr.fdd.injected, detected: dr.fdd.detected, falseAlarms: dr.fdd.falseAlarms, precision: dr.fdd.precision, recall: dr.fdd.recall, byType } };

const st = f1.stats, agentsPerDay = { rounds: st.rounds / 9, messages: st.messages / 9, conflicts: st.conflicts / 9, decisions: st.decisions / 9, drEvents: st.drEvents, peakGuard: st.peakGuardActions, pvMAPE: st.pvForecastMAPE };
const out = { generated: new Date().toISOString(), method: '1 sim-minute steps, 9 simulated days, days 1-8 scored (day 0 warm-up), paired agent vs rule-based BMS on identical weather/occupancy', deterministic, K, abl, forecast, fdd, agentsPerDay };
for (const k in out.K) delete out.K[k]._cs;
writeFileSync('results/summary.json', JSON.stringify(out, null, 1));

const f = (c) => `${r1(c.mean)} ± ${r1(c.ci)}`;
console.log('deterministic:', deterministic);
console.log('config            cost%          energy%        peak%          peakA/peakB/limit   overMin A/B   comfort A/B    EV A/B        PV A/B       DR A/B (days)');
for (const n of names) { const k = K[n]; console.log(n.padEnd(17), f(k.costSave).padEnd(14), f(k.energySave).padEnd(14), f(k.peakCut).padEnd(14), `${Math.round(k.peakA)}/${Math.round(k.peakB)}/${k.limit}`.padEnd(19), `${k.overMinA}/${k.overMinB}`.padEnd(13), `${r1(k.comfortA)}/${r1(k.comfortB)}`.padEnd(14), `${r1(k.evA)}/${r1(k.evB)}`.padEnd(13), `${r1(k.pvA)}/${r1(k.pvB)}`.padEnd(12), k.drDays ? `${r1(k.drA)}/${r1(k.drB)} (${k.drDays})` : '-'); }
console.log('ablation contribution (pp of cost saving):', Object.entries(abl).map(([k, c]) => `${k} ${f(c)}`).join(' | '));
console.log('forecast:', JSON.stringify({ cv: r1(fModel.cvrmse), nmbe: r1(fModel.nmbe), persCV: r1(fPers.cvrmse), skill: r2(forecast.skill), n: fModel.n, dailyCV: f(forecast.dailyCV) }));
console.log('fdd:', JSON.stringify(fdd));
console.log('agents/day:', JSON.stringify(agentsPerDay), 'cost A/B full:', Math.round(K.full.costA), Math.round(K.full.costB), K.full.currency, '| kepco', Math.round(K.kepco.costA), Math.round(K.kepco.costB), K.kepco.currency);
