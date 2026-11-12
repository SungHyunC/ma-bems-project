// node analyze.mjs [--demandUSD=<$ per kW-month>] → results/summary.json (+ results/extra_summary.json once the
// robustness runs exist) and printed tables. Days 1–8 are scored (day 0 is the warm-up day).
// Works in build/ or eval/: raw run files are read from ./results/, else from ../build/results/.
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
const RAW = (n) => [`results/${n}.json`, `../build/results/${n}.json`].find((p) => existsSync(p));
const has = (n) => !!RAW(n);
const load = (n) => JSON.parse(readFileSync(RAW(n), 'utf8'));
// results/v1/: the committed results of the earlier default (coordinator v1), kept when coordinator v2 became the default
const RAW1 = (n) => [`results/v1/${n}.json`, `../build/results/v1/${n}.json`].find((p) => existsSync(p));
const has1 = (n) => !!RAW1(n);
const load1 = (n) => JSON.parse(readFileSync(RAW1(n), 'utf8'));
const ARG = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')));
const T975 = { 2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262 };
const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
const ci = (a) => { const n = a.length, m = mean(a), sd = Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / Math.max(1, n - 1)); return { mean: m, ci: (T975[n] || 1.96) * sd / Math.sqrt(n), sd, n }; };
const r1 = (x) => Math.round(x * 10) / 10, r2 = (x) => Math.round(x * 100) / 100;
const days = (v) => v.days.filter((d) => d.day >= 2).map((d) => ({ day: d.day - 1, A: d.agent, B: d.baseline, cur: d.currency }));
const pct = (b, a) => (b > 0 ? 100 * (b - a) / b : 0);

function kpis(v) {
  const D = days(v);
  const cs = D.map((d) => pct(d.B.cost, d.A.cost)), es = D.map((d) => pct(d.B.energyKWh, d.A.energyKWh)), ps = D.map((d) => pct(d.B.peakKW, d.A.peakKW));
  const sum = (f) => D.reduce((s, d) => s + f(d), 0), avg = (f) => mean(D.map(f)), max = (f) => Math.max(...D.map(f));
  const dr = D.filter((d) => d.B.drRequestedKWh > 0);
  return {
    name: v.name, n: D.length, currency: D[0].cur, costSave: ci(cs), energySave: ci(es), peakCut: ci(ps), _cs: cs,
    costA: avg((d) => d.A.cost), costB: avg((d) => d.B.cost), kwhA: avg((d) => d.A.energyKWh), kwhB: avg((d) => d.B.energyKWh),
    peakA: avg((d) => d.A.peakKW), peakB: avg((d) => d.B.peakKW), peakMaxA: max((d) => d.A.peakKW), peakMaxB: max((d) => d.B.peakKW), limit: v.peakLimit,
    overMinA: sum((d) => d.A.minutesOverLimit), overMinB: sum((d) => d.B.minutesOverLimit), overKWhA: sum((d) => d.A.overLimitKWh), overKWhB: sum((d) => d.B.overLimitKWh),
    comfortA: avg((d) => d.A.comfortPct), comfortB: avg((d) => d.B.comfortPct), discA: sum((d) => d.A.discomfortDegH), discB: sum((d) => d.B.discomfortDegH),
    evA: avg((d) => d.A.evMetPct), evB: avg((d) => d.B.evMetPct), pvA: avg((d) => d.A.pvSelfPct), pvB: avg((d) => d.B.pvSelfPct),
    co2Save: ci(D.map((d) => pct(d.B.co2Kg, d.A.co2Kg))), co2A: avg((d) => d.A.co2Kg), co2B: avg((d) => d.B.co2Kg),
    cyclesA: avg((d) => d.A.essCycles), cyclesB: avg((d) => d.B.essCycles), lfA: avg((d) => d.A.loadFactor), lfB: avg((d) => d.B.loadFactor),
    drDays: dr.length, drA: dr.length ? mean(dr.map((d) => d.A.drPct)) : null, drB: dr.length ? mean(dr.map((d) => d.B.drPct)) : null,
    vacA: avg((d) => d.A.vacantRoomKWh), vacB: avg((d) => d.B.vacantRoomKWh),
  };
}
const strip = (k) => { const o = { ...k }; delete o._cs; return o; };
const names = ['full', 'tuned', 'ablate_COORD', 'ablate_ESS', 'ablate_EV', 'ablate_ROOM', 'ablate_HVAC', 'ablate_LIGHT', 'kepco', 'bdg2'].filter(has);
const K = Object.fromEntries(names.map((n) => [n, kpis(load(n))]));

// determinism: the same configuration twice must give identical daily costs
const f1 = load('full'), f2 = load('full_repeat');
const deterministic = days(f1).every((d, i) => Math.abs(d.A.cost - days(f2)[i].A.cost) < 1e-9 && Math.abs(d.B.cost - days(f2)[i].B.cost) < 1e-9);

// ablations: contribution = full saving − ablated saving, paired by day
const abl = {};
for (const n of names.filter((n) => n.startsWith('ablate_'))) abl[n.slice(7)] = ci(K.full._cs.map((x, i) => x - K[n]._cs[i]));

// ---- forecast accuracy: 1 h ahead (the target 15-min slot starts 60 min after the forecast is made), days 1–8 ----
// Benchmarks on the same slots: persistence = the last slot observed when the forecast is made (a−5); persistence60 =
// the slot starting one hour before the target (a−4) — still running when the forecast is made, so it sees 15 min the
// model cannot (the benchmark of the earlier report, kept for comparison); yesterday = the same slot the day before.
const accOf = (pairs) => { const n = pairs.length, my = mean(pairs.map((p) => p.y)); const rmse = Math.sqrt(mean(pairs.map((p) => (p.p - p.y) ** 2))); return { n, cvrmse: 100 * rmse / my, nmbe: 100 * mean(pairs.map((p) => p.p - p.y)) / my, rmse }; };
function fcEval(scored, actual) {
  const sc = Object.fromEntries(scored.map((s) => [s.abs, s])), Y = actual || {};
  const y = (a) => (Y[a] != null ? Y[a] : sc[a] ? sc[a].y : null);
  const S = Object.values(sc).filter((s) => s.abs >= 96 && s.abs < 9 * 96 && [5, 4, 96].every((k) => y(s.abs - k) != null));
  if (!S.length) return null;
  const model = accOf(S.map((s) => ({ y: s.y, p: s.p }))), persistence = accOf(S.map((s) => ({ y: s.y, p: y(s.abs - 5) })));
  const persistence60 = accOf(S.map((s) => ({ y: s.y, p: y(s.abs - 4) }))), yesterday = accOf(S.map((s) => ({ y: s.y, p: y(s.abs - 96) })));
  const perDay = [...new Set(S.map((s) => Math.floor(s.abs / 96)))].map((d) => accOf(S.filter((s) => Math.floor(s.abs / 96) === d).map((s) => ({ y: s.y, p: s.p }))).cvrmse);
  return { model, persistence, persistence60, yesterday, skill: 1 - model.rmse / persistence.rmse, skillVsYesterday: 1 - model.rmse / yesterday.rmse, dailyCV: ci(perDay) };
}
const forecast = { ...fcEval(f1.scored, f1.fcY), methods: [...new Set(f1.fcDaily.map((d) => d.sum))],
  definitions: { horizon: 'made at the start of slot a-4 from data through slot a-5; the target slot a starts 60 min later',
    persistence: 'slot a-5 (last observed)', persistence60: 'slot a-4 (not yet complete when the forecast is made)', yesterday: 'slot a-96' } };

// FDD: false alarms in normal operation (full run, no faults) and the drill (one fault every 3 h, oracle approvals)
function fddOf(dr) {
  const byType = {};
  for (const f of dr.inj) { const k = f.type, b = byType[k] || (byType[k] = { n: 0, det: 0, d: [], censored: 0 }); b.n++; if (f.detected) { b.det++; b.d.push(f.delay); } else if (dr.T - f.t0 < 600) b.censored++; }
  for (const k in byType) { const b = byType[k], d = b.d.sort((x, y) => x - y); Object.assign(b, { median: d[Math.floor((d.length - 1) / 2)], max: d[d.length - 1] }); delete b.d; }
  return { injected: dr.fdd.injected, detected: dr.fdd.detected, falseAlarms: dr.fdd.falseAlarms, precision: dr.fdd.precision, recall: dr.fdd.recall, byType };
}
const fdd = { normalFalseAlarms: f1.fddLog.filter((e) => !e.real).length, roomDays: f1.nRooms * Math.round(f1.T / 1440), rooms: f1.nRooms, drill: fddOf(load('drill')) };

// ---- demand charge (not in the simulated cost): billing peak = the highest daily peak of the scored days ----
// KEPCO general service (B) HV-A option II, 2026-06-01 edition: ₩8,320 per kW per month (tariff_module.js,
// KEPCO.demandKRWperKWmonth; also deck/project/slides/impact.html). It applies to the ₩ runs (kepco, bdg2). The repo has
// no $ demand rate, so the $ runs report it only with --demandUSD=<$ per kW-month>. Month = 30 simulated weekdays.
const DEMAND_KRW = 8320, DEMAND_USD = ARG.demandUSD != null && Number.isFinite(+ARG.demandUSD) ? +ARG.demandUSD : null;
function demand(v, rate) {
  const D = days(v), pkA = Math.max(...D.map((d) => d.A.peakKW)), pkB = Math.max(...D.map((d) => d.B.peakKW));
  const eA = 30 * mean(D.map((d) => d.A.cost)), eB = 30 * mean(D.map((d) => d.B.cost));
  const o = { currency: D[0].cur, rate, billingPeakA: pkA, billingPeakB: pkB, energyPerMonthA: eA, energyPerMonthB: eB, saveEnergyOnlyPct: pct(eB, eA) };
  if (rate == null) return Object.assign(o, { note: 'no demand rate for this currency in the repo: pass --demandUSD=<rate per kW-month>' });
  return Object.assign(o, { demandPerMonthA: pkA * rate, demandPerMonthB: pkB * rate, demandSavingPerMonth: (pkB - pkA) * rate, saveWithDemandPct: pct(eB + pkB * rate, eA + pkA * rate) });
}
const demandCharge = { source: 'KEPCO 2026-06-01 general service (B) HV-A option II: 8,320 KRW per kW-month (build/tariff_module.js)', usdRate: DEMAND_USD,
  runs: Object.fromEntries(names.filter((n) => ['full', 'tuned', 'kepco', 'bdg2'].includes(n)).map((n) => { const v = load(n), c = days(v)[0].cur; return [n, demand(v, c === '₩' ? DEMAND_KRW : DEMAND_USD)]; })) };

const st = f1.stats, agentsPerDay = { rounds: st.rounds / 9, messages: st.messages / 9, conflicts: st.conflicts / 9, decisions: st.decisions / 9, drEvents: st.drEvents, peakGuard: st.peakGuardActions, pvMAPE: st.pvForecastMAPE };
const out = { generated: new Date().toISOString(), defaultCoordinator: 'v2 (coord=v1 reproduces results/v1/)', method: '1 sim-minute steps, 9 simulated days, days 1-8 scored (day 0 warm-up), paired agent vs rule-based BMS on identical weather/occupancy',
  deterministic, K: Object.fromEntries(Object.entries(K).map(([k, v]) => [k, strip(v)])), abl, forecast, fdd, demandCharge, agentsPerDay };
mkdirSync('results', { recursive: true });
writeFileSync('results/summary.json', JSON.stringify(out, null, 1));

const f = (c) => `${r1(c.mean)} ± ${r1(c.ci)}`;
console.log('deterministic:', deterministic);
console.log('config            cost%          energy%        peak%          peakA/B/limit   overMin A/B   comfort A/B    EV A/B        PV A/B       DR A/B (days)');
for (const n of names) { const k = K[n]; console.log(n.padEnd(17), f(k.costSave).padEnd(14), f(k.energySave).padEnd(14), f(k.peakCut).padEnd(14), `${Math.round(k.peakA)}/${Math.round(k.peakB)}/${k.limit}`.padEnd(15), `${k.overMinA}/${k.overMinB}`.padEnd(13), `${r1(k.comfortA)}/${r1(k.comfortB)}`.padEnd(14), `${r1(k.evA)}/${r1(k.evB)}`.padEnd(13), `${r1(k.pvA)}/${r1(k.pvB)}`.padEnd(12), k.drDays ? `${r1(k.drA)}/${r1(k.drB)} (${k.drDays})` : '-'); }
console.log('ablation contribution (pp of cost saving):', Object.entries(abl).map(([k, c]) => `${k} ${f(c)}`).join(' | '));
const fcs = (a) => `${r1(a.cvrmse)}% / ${r1(a.nmbe)}%`;
console.log(`forecast 1 h ahead, CV(RMSE) / NMBE (n=${forecast.model.n}): model ${fcs(forecast.model)} | persistence ${fcs(forecast.persistence)} | persistence60 ${fcs(forecast.persistence60)} | yesterday ${fcs(forecast.yesterday)} | skill vs persistence ${r2(forecast.skill)}, vs yesterday ${r2(forecast.skillVsYesterday)}`);
console.log('fdd:', JSON.stringify(fdd));
for (const [n, d] of Object.entries(demandCharge.runs)) console.log(`demand charge ${n}: billing peak ${Math.round(d.billingPeakA)}/${Math.round(d.billingPeakB)} kW, saving energy-only ${r1(d.saveEnergyOnlyPct)}%` + (d.rate != null ? `, with demand ${r1(d.saveWithDemandPct)}% (${d.currency}${Math.round(d.demandSavingPerMonth).toLocaleString('en-US')}/month)` : ` (${d.note})`));
console.log('agents/day:', JSON.stringify(agentsPerDay), 'cost A/B full:', Math.round(K.full.costA), Math.round(K.full.costB), K.full.currency, '| kepco', Math.round(K.kepco.costA), Math.round(K.kepco.costB), K.kepco.currency);

// =================================================================================================================
// extra_summary.json: the robustness study (strong BMS, DR off, seeds, coordinator v1 vs v2, FDD noise and fault energy)
// =================================================================================================================
const SEEDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
const SCN6 = ['normal', 'heatwave', 'cloudy', 'dr', 'tight', 'worst'], SCN9 = ['normal', 'heatwave', 'cloudy', 'dr', 'tight', 'evrush', 'holiday', 'fault', 'worst'], LIMS = [850, 800];
const X = { generated: out.generated, method: out.method + '; CIs over days use t (n=8); across seeds t (n=10) on the per-run means', note: 'built by analyze.mjs from the run files listed in commands' };
const brief = (k) => k && { costSave: k.costSave, energySave: k.energySave, peakA: k.peakA, peakB: k.peakB, peakMaxA: k.peakMaxA, peakMaxB: k.peakMaxB, limit: k.limit,
  overMinA: k.overMinA, overMinB: k.overMinB, overKWhA: k.overKWhA, overKWhB: k.overKWhB, comfortA: k.comfortA, comfortB: k.comfortB, discA: k.discA, discB: k.discB,
  drDays: k.drDays, drA: k.drA, drB: k.drB, evA: k.evA, evB: k.evB, costA: k.costA, costB: k.costB, kwhA: k.kwhA, kwhB: k.kwhB, vacA: k.vacA, vacB: k.vacB };
const kOf = (n) => (has(n) ? kpis(load(n)) : null);
const kOf1 = (n) => (has1(n) ? kpis(load1(n)) : null);
// reference-free DR view: mean import during the events (scored days) and the highest import in the hour after them
function drView(v) {
  const E = (v.drEvents || []).filter((e) => e.start >= 1440 && e.start < 9 * 1440 && e.n);
  return E.length ? { events: E.length, meanImportA: mean(E.map((e) => e.meanA)), meanImportB: mean(E.map((e) => e.meanB)), reboundMaxA: mean(E.map((e) => e.postMaxA ?? 0)), refA: mean(E.map((e) => e.ref)) } : null;
}
if (has('sensor')) X.sensorBMS = { query: 'baseline=sensor', vsDefaultBMS: brief(K.full), vsSensorBMS: brief(kOf('sensor')) };
if (has('dr_off')) X.drOff = { query: 'dr=off', withDR: brief(K.full), withoutDR: brief(kOf('dr_off')) };

// seeds: one value per run (mean over its 8 scored days), then mean ± t-CI over the 10 runs
function seedSet(prefix, hs = has, ld = load) {
  const runs = SEEDS.map((s) => `${prefix}${s}`).filter(hs); if (runs.length < 2) return null;
  const k = runs.map((n) => kpis(ld(n))), c = (g) => ci(k.map(g));
  return { runs: runs.length, costSave: c((x) => x.costSave.mean), energySave: c((x) => x.energySave.mean), peakCut: c((x) => x.peakCut.mean),
    peakA: c((x) => x.peakA), peakB: c((x) => x.peakB), peakMaxA: c((x) => x.peakMaxA), peakMaxB: c((x) => x.peakMaxB), overMinA: c((x) => x.overMinA), overMinB: c((x) => x.overMinB),
    overKWhA: c((x) => x.overKWhA), overKWhB: c((x) => x.overKWhB), comfortA: c((x) => x.comfortA), comfortB: c((x) => x.comfortB), discA: c((x) => x.discA), discB: c((x) => x.discB),
    drA: c((x) => x.drA ?? 0), drB: c((x) => x.drB ?? 0), evA: c((x) => x.evA), perRunCostSave: k.map((x) => r2(x.costSave.mean)) };
}
X.seeds = { note: 'default = coordinator v2 (results/v1/ holds the v1 runs; see v1vsV2). ?seed=N re-seeds occupancy, bookings, EV sessions and DR draws and adds day-to-day weather (±2 °C daily offset, cloudiness 0.65–1.0)',
  agentsVsDefaultBMS: seedSet('seed_'), agentsVsSensorBMS: seedSet('sensor_seed_'), v2VsDefaultBMS: seedSet('v2_seed_') };
// forecast without the oracle on the seeded weather: per-run CV(RMSE), then mean ± CI
{
  const runs = SEEDS.map((s) => `seed_${s}`).filter(has).map(load).map((v) => fcEval(v.scored, v.fcY)).filter(Boolean);
  if (runs.length > 1) X.seeds.forecast = { runs: runs.length, model: ci(runs.map((r) => r.model.cvrmse)), persistence: ci(runs.map((r) => r.persistence.cvrmse)),
    persistence60: ci(runs.map((r) => r.persistence60.cvrmse)), yesterday: ci(runs.map((r) => r.yesterday.cvrmse)), modelNMBE: ci(runs.map((r) => r.model.nmbe)) };
}

// coordinator v1 vs v2 (same BMS baseline, so differences are the agents' own)
function v12(n1, n2) {                                  // n1: file in results/v1/ (coordinator v1), n2: default run (coordinator v2)
  if (!has1(n1) || !has(n2)) return null;
  const a = load1(n1), b = load(n2), k1 = kpis(a), k2 = kpis(b);
  return { v1: n1, v2: n2, limit: k1.limit, costSaveV1: k1.costSave, costSaveV2: k2.costSave, costSaveDiff: ci(k2._cs.map((x, i) => x - k1._cs[i])),
    peakMeanV1: k1.peakA, peakMeanV2: k2.peakA, peakMaxV1: k1.peakMaxA, peakMaxV2: k2.peakMaxA, peakMeanBMS: k1.peakB, peakMaxBMS: k1.peakMaxB,
    overMinV1: k1.overMinA, overMinV2: k2.overMinA, overKWhV1: k1.overKWhA, overKWhV2: k2.overKWhA, overMinBMS: k1.overMinB, overKWhBMS: k1.overKWhB,
    comfortV1: k1.comfortA, comfortV2: k2.comfortA, discV1: k1.discA, discV2: k2.discA, drPctV1: k1.drA, drPctV2: k2.drA, evV1: k1.evA, evV2: k2.evA,
    drV1: drView(a), drV2: drView(b) };
}
X.coordinator = { note: 'v2 = the default (DR notice 60 min, forecast-aware battery, cost-based allocation); v1 = ?coord=v1, read from results/v1/ (committed before the switch)',
  scenarios: Object.fromEntries([...SCN9.map((s) => [s, v12(`scn_${s}`, `scn_${s}`)]), ...LIMS.map((l) => [`limit${l}`, v12(`lim${l}_full`, `lim${l}_full`)])].filter(([, x]) => x)) };
{
  const pairs = SEEDS.filter((s) => has1(`seed_${s}`) && has(`seed_${s}`)).map((s) => [kpis(load1(`seed_${s}`)), kpis(load(`seed_${s}`))]);
  if (pairs.length > 1) {
    const d = (g) => ci(pairs.map(([a, b]) => g(b) - g(a)));
    X.coordinator.seeds = { runs: pairs.length, note: 'paired by seed: v2 minus v1', costSave: d((k) => k.costSave.mean), peakMean: d((k) => k.peakA), peakMax: d((k) => k.peakMaxA),
      overMin: d((k) => k.overMinA), overKWh: d((k) => k.overKWhA), comfort: d((k) => k.comfortA), disc: d((k) => k.discA), drPct: d((k) => k.drA ?? 0) };
  }
}
if (has('full')) { const v = load('full'); if (v.net) X.coordinator.netLoadForecast = fcEval(v.net.scored, v.net.y); }
X.coordinator.v1RunFiles = has('v2_scn_normal') ? 'explicit coord=v2 runs (v2_*.json) are kept and equal the default runs' : undefined;

// FDD under sensor noise σ = 0.3 °C, and the energy a sensor fault costs when the room loops act on the readings
const fddX = {};
if (has('n03_full')) { const v = load('n03_full'); fddX.noise03 = { sigma: 0.3, normalFalseAlarms: v.fddLog.filter((e) => !e.real).length, roomDays: v.nRooms * Math.round(v.T / 1440) }; }
if (has('n03_drill')) fddX.noise03.drill = fddOf(load('n03_drill'));
if (has('n03_fault')) { const v = load('n03_fault'); fddX.noise03.scnFault = { log: v.fddLog, ...v.fdd }; }
if (has('fi_ref')) {
  const ref = load('fi_ref'), tot = (v, m, k) => v.days.reduce((s, d) => s + d[m][k], 0);
  const imp = (n) => { if (!has(n)) return null; const v = load(n);
    return { query: v.query, operator: n.endsWith('_op') || n === 'fi_drill', injected: v.fdd.injected, detected: v.fdd.detected, falseAlarms: v.fdd.falseAlarms,
      extraKWhAgent: tot(v, 'agent', 'energyKWh') - tot(ref, 'agent', 'energyKWh'), extraKWhBMS: tot(v, 'baseline', 'energyKWh') - tot(ref, 'baseline', 'energyKWh'),
      extraCostAgent: tot(v, 'agent', 'cost') - tot(ref, 'agent', 'cost'), extraDiscomfortAgent: tot(v, 'agent', 'discomfortDegH') - tot(ref, 'agent', 'discomfortDegH'),
      extraDiscomfortBMS: tot(v, 'baseline', 'discomfortDegH') - tot(ref, 'baseline', 'discomfortDegH'), delays: v.inj.length ? fddOf(v).byType : v.fddLog.filter((e) => e.real).map((e) => e.delay) }; };
  fddX.faultImpact = { note: 'all 9 simulated days vs ?faultImpact=1 without faults (identical to the default run); operator = oracle approves real alarms / dismisses false ones every 5 min, an approved sensor is repaired 30 min later; the BMS world keeps every fault',
    refEqualsDefault: JSON.stringify(ref.days) === JSON.stringify(f1.days),
    runs: Object.fromEntries(['fi_stuck_op', 'fi_stuck_off', 'fi_stuck_noop', 'fi_drift_op', 'fi_drift_off', 'fi_drift_noop', 'fi_dropout_op', 'fi_dropout_off', 'fi_drill', 'fi_drill_off'].map((n) => [n, imp(n)]).filter(([, x]) => x)) };
}
X.fdd = fddX;
X.forecast = { full: forecast, note: 'grid import, 1 h ahead, without future weather (see summary.json forecast.definitions)' };
X.demandCharge = demandCharge;
// ---- coordinator v1 (results/v1/, the committed runs of the earlier default) vs v2 (the default now) ----
// Same BMS and inputs in both, so every difference is the agents' own. Every block pairs files of the same name.
{
  const pair = (n, brief_ = brief) => (has1(n) && has(n) ? { v1: brief_(kOf1(n)), v2: brief_(kOf(n)), costSaveDiff: ci(kOf(n)._cs.map((x, i) => x - kOf1(n)._cs[i])) } : null);
  const ablSet = (get, hs) => { const f = get('full'); if (!f) return null; const o = {};
    for (const n of ['ROOM', 'ESS', 'HVAC', 'LIGHT', 'EV', 'COORD']) if (hs(`ablate_${n}`)) o[n] = ci(f._cs.map((x, i) => x - get(`ablate_${n}`)._cs[i])); return o; };
  const lims = (get, hs) => [900, 850, 800].filter((l) => hs(`lim${l}_full`) && hs(`lim${l}_coord`)).map((l) => ({ limit: l, full: get(`lim${l}_full`).overKWhA, noCoord: get(`lim${l}_coord`).overKWhA, fullMin: get(`lim${l}_full`).overMinA, noCoordMin: get(`lim${l}_coord`).overMinA }));
  const fddOf1 = (ld, hs) => hs('full') && hs('drill') ? { normalFalseAlarms: ld('full').fddLog.filter((e) => !e.real).length, drill: (({ injected, detected, falseAlarms, precision, recall }) => ({ injected, detected, falseAlarms, precision, recall }))(fddOf(ld('drill'))) } : null;
  const grid = (ld, hs) => hs('full') ? (({ model, persistence, yesterday }) => ({ model, persistence, yesterday }))(fcEval(ld('full').scored, ld('full').fcY)) : null;
  X.v1vsV2 = { note: 'v1 = ?coord=v1, read from results/v1/ (the runs committed before the default switched); v2 = the default, read from results/. Same BMS, same inputs: differences are the agents\' own. costSaveDiff = v2 − v1 in saving points, paired by day.',
    headline: pair('full'), tuned: pair('tuned'), sensor: pair('sensor'), drOff: pair('dr_off'), kepco: pair('kepco'), bdg2: pair('bdg2'),
    ablation: { v1: ablSet(kOf1, has1), v2: ablSet(kOf, has), note: 'contribution = full saving − ablated saving (pp, paired by day). Under v2, ablate=COORD removes the negotiation / cost-based allocation only: the forecast-aware battery and the DR pre-cool stay inside the agents\' plans.' },
    limits: { v1: lims(kOf1, has1), v2: lims(kOf, has), note: 'over-limit kWh / minutes over 8 days, with the coordinator and with ablate=COORD' },
    scenarios: Object.fromEntries(SCN9.map((x) => [x, pair(`scn_${x}`)]).filter(([, v]) => v)),
    seeds: { default: { v1: seedSet('seed_', has1, load1), v2: seedSet('seed_') }, sensor: { v1: seedSet('sensor_seed_', has1, load1), v2: seedSet('sensor_seed_') } },
    fdd: { v1: fddOf1(load1, has1), v2: fddOf1(load, has) }, forecastGrid: { v1: grid(load1, has1), v2: grid(load, has) } };
}
// defaults unchanged: committed runs of the earlier default (results/v1/) vs new runs of ?coord=v1 (daily KPIs, both controllers)
{
  const maxDiff = (a, b) => { let m = 0; a.days.forEach((d, i) => { for (const w of ['agent', 'baseline']) for (const k in d[w]) { const x = d[w][k], y = b.days[i][w][k]; if (typeof x === 'number') m = Math.max(m, Math.abs(x - y)); } }); return m; };
  const P = [['scn_normal', 'v1_full'], ['full', 'v1_full'], ['full_repeat', 'v1_full'], ['scn_heatwave', 'v1_scn_heatwave'], ['scn_cloudy', 'v1_scn_cloudy'], ['scn_dr', 'v1_scn_dr'], ['scn_tight', 'v1_scn_tight'],
    ['scn_worst', 'v1_scn_worst'], ['lim850_full', 'v1_lim850'], ['lim800_full', 'v1_lim800']].filter(([a, b]) => has1(a) && has(b));
  X.defaultsUnchanged = { note: 'old = run files in results/v1/ (committed before the default switched to v2); new = the same configuration re-run with coord=v1 (results/v1_*.json); max |difference| over every daily KPI of both controllers', pairs: P.map(([a, b]) => ({ old: a, new: b, maxDiff: maxDiff(load1(a), load(b)) })) };
}
// the run table: [name, query, dataset, drill]. Default queries have no coord switch (coordinator v2); the v1 table is the same with coord=v1.
const RUNS = [['full', ''], ['full_repeat', ''], ['tuned', 'baseline=tuned'], ...['ROOM', 'ESS', 'HVAC', 'LIGHT', 'EV', 'COORD'].map((a) => [`ablate_${a}`, `ablate=${a}`]),
  ['kepco', '', 'kepco'], ['bdg2', '', 'bdg2'], ['drill', '', '', 180],
  ...[900, 850, 800].flatMap((l) => [[`lim${l}_full`, `limit=${l}`], [`lim${l}_coord`, `limit=${l}&ablate=COORD`]]),
  ...SCN9.map((x) => [`scn_${x}`, x === 'normal' ? '' : `scn=${x}`]),
  ['sensor', 'baseline=sensor'], ['dr_off', 'dr=off'],
  ...SEEDS.flatMap((x) => [[`seed_${x}`, `seed=${x}`], [`sensor_seed_${x}`, `baseline=sensor&seed=${x}`]]),
  ['n03_full', 'fddNoise=0.3'], ['n03_drill', 'fddNoise=0.3', '', 180], ['n03_fault', 'fddNoise=0.3&scn=fault'],
  ['fi_ref', 'faultImpact=1'],
  ['fi_stuck_op', 'faultImpact=1&scn=fault', '', -1], ['fi_stuck_off', 'faultImpact=1&scn=fault&fdd=off'], ['fi_stuck_noop', 'faultImpact=1&scn=fault'],
  ['fi_drift_op', 'faultImpact=1&scn=custom&fault=drift', '', -1], ['fi_drift_off', 'faultImpact=1&scn=custom&fault=drift&fdd=off'], ['fi_drift_noop', 'faultImpact=1&scn=custom&fault=drift'],
  ['fi_dropout_op', 'faultImpact=1&scn=custom&fault=dropout', '', -1], ['fi_dropout_off', 'faultImpact=1&scn=custom&fault=dropout&fdd=off'],
  ['fi_drill', 'faultImpact=1', '', 180], ['fi_drill_off', 'faultImpact=1&fdd=off', '', 180]];
const E = 'node --experimental-websocket exp.mjs';   // Node 20 needs the flag; run in build/ (Chrome CDP on :9333, page server on :5178)
const cmd = (name, q, ds = '', drill = 0) => `${E} ${name} "${q}" 9` + (ds || drill ? ` "${ds}"` : '') + (drill ? ` ${drill}` : '');
X.commands = [
  ...RUNS.map(([n, q, ds, dr]) => cmd(n, q, ds, dr)),
  // explicit coordinator switches: v2 = the default (kept as separate files), v1 = the earlier coordinator
  `${E} v1_full "coord=v1" 9`,
  ...SEEDS.map((x) => `${E} v2_seed_${x} "coord=v2&seed=${x}" 9`),
  `${E} v2_scn_normal "coord=v2" 9`,
  ...SCN6.filter((x) => x !== 'normal').flatMap((x) => [`${E} v1_scn_${x} "coord=v1&scn=${x}" 9`, `${E} v2_scn_${x} "coord=v2&scn=${x}" 9`]),
  ...LIMS.flatMap((l) => [`${E} v1_lim${l} "coord=v1&limit=${l}" 9`, `${E} v2_lim${l} "coord=v2&limit=${l}" 9`]),
  'node analyze.mjs                      (optional: --demandUSD=<$ per kW-month> for the $ runs)',
  'node make_scn.mjs',
];
// the runs of results/v1/ (committed before the default switched): the same table with coord=v1, written to results/v1/<name>.json
X.commandsV1 = [
  ...RUNS.map(([n, q, ds, dr]) => cmd(`v1/${n}`, ['coord=v1', q].filter(Boolean).join('&'), ds, dr)),
  ...SCN6.filter((x) => x !== 'normal').map((x) => cmd(`v1/v1_scn_${x}`, `coord=v1&scn=${x}`)),
  ...LIMS.map((l) => cmd(`v1/v1_lim${l}`, `coord=v1&limit=${l}`)),
];
const extraReady = has('sensor') || has('seed_1') || has('v2_scn_normal');
if (extraReady) {
  writeFileSync('results/extra_summary.json', JSON.stringify(X, null, 1));
  const S = X.seeds, g = (c) => (c ? `${r1(c.mean)} ± ${r1(c.ci)}` : '-');
  console.log('\nextra_summary.json');
  if (X.sensorBMS) { const k = X.sensorBMS.vsSensorBMS; console.log(`sensor BMS: cost ${g(k.costSave)}% | peak ${Math.round(k.peakA)}/${Math.round(k.peakB)} kW | comfort ${r1(k.comfortA)}/${r1(k.comfortB)} | DR ${r1(k.drA)}/${r1(k.drB)}%`); }
  if (X.drOff) console.log(`dr=off: cost ${g(X.drOff.withoutDR.costSave)}% (with DR ${g(X.drOff.withDR.costSave)}%)`);
  for (const [k, s] of Object.entries({ default: S.agentsVsDefaultBMS, sensor: S.agentsVsSensorBMS, v2: S.v2VsDefaultBMS })) if (s) console.log(`seeds ${k.padEnd(7)} cost ${g(s.costSave)}% | peak ${g(s.peakA)}/${g(s.peakB)} kW | max ${g(s.peakMaxA)} | comfort ${g(s.comfortA)}/${g(s.comfortB)} | over-limit kWh ${g(s.overKWhA)}`);
  if (S.forecast) console.log(`seeds forecast CV: model ${g(S.forecast.model)} | persistence ${g(S.forecast.persistence)} | yesterday ${g(S.forecast.yesterday)}`);
  console.log('v1 vs v2       cost% v1 → v2        peak mean   peak max    over-limit min   over-limit kWh   comfort     DR %');
  for (const [s, c] of Object.entries(X.coordinator.scenarios)) console.log(`${s.padEnd(14)} ${g(c.costSaveV1).padEnd(9)} → ${g(c.costSaveV2).padEnd(9)} ${Math.round(c.peakMeanV1)}→${Math.round(c.peakMeanV2)}   ${Math.round(c.peakMaxV1)}→${Math.round(c.peakMaxV2)}   ${c.overMinV1}→${c.overMinV2}`.padEnd(88) + `${Math.round(c.overKWhV1)}→${Math.round(c.overKWhV2)}`.padEnd(17) + `${r1(c.comfortV1)}→${r1(c.comfortV2)}   ${c.drPctV1 == null ? '-' : Math.round(c.drPctV1) + '→' + Math.round(c.drPctV2)}`);
  if (X.coordinator.seeds) { const d = X.coordinator.seeds; console.log(`seeds v2−v1: cost ${g(d.costSave)} pp | peak mean ${g(d.peakMean)} kW | peak max ${g(d.peakMax)} kW | over-limit kWh ${g(d.overKWh)} | comfort ${g(d.comfort)} pp`); }
  const sg = (x) => (x >= 0 ? '+' : '−') + Math.abs(Math.round(x));
  if (fddX.faultImpact) for (const [n, x] of Object.entries(fddX.faultImpact.runs)) console.log(`${n.padEnd(15)} ${sg(x.extraKWhAgent)} kWh agent (${sg(x.extraDiscomfortAgent)} °C·h) | BMS ${sg(x.extraKWhBMS)} kWh | detected ${x.detected}/${x.injected}, false ${x.falseAlarms}`);
  console.log('defaults unchanged:', X.defaultsUnchanged.pairs.map((p) => `${p.old}→${p.new} ${p.maxDiff}`).join(', '));
}
