// node feedback.mjs → results/feedback_summary.json + printed tables
// The answers to the 2026-11-17 review (eval/README.md "피드백 대응"): a skilled-operator baseline, twelve months of real
// 2025 weather with heating, and a sensitivity study for the calibration plan. Raw runs: build/results/fb/ (exp.mjs),
// plus the committed basic / sensor runs in build/results/. Works in build/ or eval/.
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
const RAW = (n) => [`results/${n}.json`, `../build/results/${n}.json`].find((p) => existsSync(p));
const load = (n) => { const p = RAW(n); if (!p) throw new Error('missing run ' + n); return JSON.parse(readFileSync(p, 'utf8')); };
const T975 = { 2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262 };
const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
const ci = (a) => { const n = a.length, m = mean(a), sd = Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / Math.max(1, n - 1)); return { mean: m, ci: (T975[n] || 1.96) * sd / Math.sqrt(n), n }; };
const r1 = (x) => Math.round(x * 10) / 10, r2 = (x) => Math.round(x * 1000) / 1000;   // r2 keeps 3 decimals so printed 1-decimal values are not rounded twice
const pct = (b, a) => (b > 0 ? 100 * (b - a) / b : 0);
const days = (v) => v.days.filter((d) => d.day >= 2).map((d) => ({ A: d.agent, B: d.baseline }));   // day 0 = warm-up

function kpis(v) {
  const D = days(v), avg = (f) => mean(D.map(f)), sum = (f) => D.reduce((s, d) => s + f(d), 0);
  const dr = D.filter((d) => d.B.drRequestedKWh > 0);
  return {
    n: D.length, costSave: ci(D.map((d) => pct(d.B.cost, d.A.cost))), energySave: r1(pct(avg((d) => d.B.energyKWh), avg((d) => d.A.energyKWh))),
    costA: r1(avg((d) => d.A.cost)), costB: r1(avg((d) => d.B.cost)), kwhA: Math.round(avg((d) => d.A.energyKWh)), kwhB: Math.round(avg((d) => d.B.energyKWh)),
    peakA: Math.round(avg((d) => d.A.peakKW)), peakB: Math.round(avg((d) => d.B.peakKW)), peakMaxA: Math.round(Math.max(...D.map((d) => d.A.peakKW))), peakMaxB: Math.round(Math.max(...D.map((d) => d.B.peakKW))),
    overMinA: sum((d) => d.A.minutesOverLimit), overMinB: sum((d) => d.B.minutesOverLimit),
    comfortA: r1(avg((d) => d.A.comfortPct)), comfortB: r1(avg((d) => d.B.comfortPct)), discA: Math.round(sum((d) => d.A.discomfortDegH)), discB: Math.round(sum((d) => d.B.discomfortDegH)),
    evA: r1(avg((d) => d.A.evMetPct)), evB: r1(avg((d) => d.B.evMetPct)), drA: dr.length ? Math.round(mean(dr.map((d) => d.A.drPct))) : null, drB: dr.length ? Math.round(mean(dr.map((d) => d.B.drPct))) : null,
  };
}
const fmt = (k) => ({ ...k, costSave: { mean: r2(k.costSave.mean), ci: r2(k.costSave.ci), n: k.costSave.n } });
const seedCI = (pre) => { const xs = []; for (let n = 1; n <= 10; n++) xs.push(mean(days(load(pre + n)).map((d) => pct(d.B.cost, d.A.cost)))); const c = ci(xs); return { mean: r2(c.mean), ci: r2(c.ci), perSeed: xs.map(r2) }; };

// 1 · baseline ladder incl. the skilled-operator BMS (?baseline=expert), fixed inputs (8 days) and 10 weather seeds
const ladder = {
  basic: { ...fmt(kpis(load('full'))), seeds: seedCI('seed_') },
  sensor: { ...fmt(kpis(load('sensor'))), seeds: seedCI('sensor_seed_') },
  expert: { ...fmt(kpis(load('fb/expert'))), seeds: seedCI('fb/expert_seed_') },
};
const expSeeds = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => kpis(load('fb/expert_seed_' + n)));
ladder.expert.seedKPIs = { comfortB: r1(mean(expSeeds.map((k) => k.comfortB))), comfortA: r1(mean(expSeeds.map((k) => k.comfortA))), peakA: Math.round(mean(expSeeds.map((k) => k.peakA))), peakB: Math.round(mean(expSeeds.map((k) => k.peakB))),
  overMinA: r1(mean(expSeeds.map((k) => k.overMinA))), overMinB: r1(mean(expSeeds.map((k) => k.overMinB))) };

// 2 · scenarios against the basic BMS (committed scn_* runs) and the expert BMS
const SCN = ['heatwave', 'cloudy', 'dr', 'tight', 'evrush', 'holiday', 'worst'];
const scenarios = Object.fromEntries(SCN.map((s) => [s, { basic: fmt(kpis(load('scn_' + s))), expert: fmt(kpis(load('fb/expert_scn_' + s))) }]));

// 3 · twelve months of real 2025 weather (?heat=1), each against the three baselines; annual = cost-weighted over the year
const WX = JSON.parse(readFileSync(existsSync('data/wx_sejong_2025_summary.json') ? 'data/wx_sejong_2025_summary.json' : '../eval/data/wx_sejong_2025_summary.json', 'utf8'));
const months = [], annual = {};
for (const bl of ['basic', 'sensor', 'expert']) annual[bl] = { costA: 0, costB: 0, kwhA: 0, kwhB: 0 };
for (const w of WX.months) {
  const mo = String(w.month).padStart(2, '0'), row = { month: w.month, weather: w };
  for (const bl of ['basic', 'sensor', 'expert']) {
    const k = kpis(load(`fb/sea_${mo}_${bl}`)); row[bl] = fmt(k);
    const a = annual[bl]; a.costA += k.costA * w.days; a.costB += k.costB * w.days; a.kwhA += k.kwhA * w.days; a.kwhB += k.kwhB * w.days;
  }
  months.push(row);
}
for (const bl in annual) { const a = annual[bl]; annual[bl] = { costSave: r1(pct(a.costB, a.costA)), energySave: r1(pct(a.kwhB, a.kwhA)), costA: Math.round(a.costA), costB: Math.round(a.costB) }; }
const seasonOf = (m) => (m <= 2 || m === 12 ? 'winter' : m <= 5 ? 'spring' : m <= 8 ? 'summer' : 'autumn');
const seasons = {};
for (const s of ['winter', 'spring', 'summer', 'autumn']) {
  const rows = months.filter((r) => seasonOf(r.month) === s); seasons[s] = {};
  for (const bl of ['basic', 'sensor', 'expert']) {
    let A = 0, B = 0; for (const r of rows) { A += r[bl].costA * r.weather.days; B += r[bl].costB * r.weather.days; }
    seasons[s][bl] = r1(pct(B, A));
  }
}

// 4 · sensitivity for the calibration plan: one parameter at a time (15 days, built-in summer weather) and two combined
// cases; G14 = hourly CV(RMSE) / NMBE of the nominal (uncalibrated) model's BMS-world import against this "building"
const hourly = (arr, d0, d1) => { const out = []; for (let h = d0 * 24; h < d1 * 24; h++) { let s = 0; for (let k = 0; k < 4; k++) s += arr[h * 4 + k] || 0; out.push(s / 4); } return out; };
const g14 = (pred, meas) => { const my = mean(meas), rmse = Math.sqrt(mean(meas.map((y, i) => (pred[i] - y) ** 2))); return { cvrmse: r1(100 * rmse / my), nmbe: r1(100 * mean(meas.map((y, i) => pred[i] - y)) / my) }; };
const ref = load('fb/sens_ref'), refK = kpis(ref), refH = hourly(ref.s15.b, 1, 15);
const SENS = [['plugX_0p8', '콘센트 −20%'], ['plugX_1p2', '콘센트 +20%'], ['lightX_0p8', '조명 −20%'], ['lightX_1p2', '조명 +20%'], ['hvacX_0p8', '공조 전력 −20%'], ['hvacX_1p2', '공조 전력 +20%'],
  ['leakX_0p7', '외피 열교환 −30%'], ['leakX_1p3', '외피 열교환 +30%'], ['spOff_m1', '설정온도 −1 °C'], ['spOff_1', '설정온도 +1 °C'], ['occ_0p8', '재실 −20%'], ['occ_1p2', '재실 +20%'],
  ['combo_lo', '복합(절감 불리): 콘센트 +20%, 조명 −15%, 공조 +20%, 외피 +30%, 재실 +20%'], ['combo_hi', '복합(절감 유리): 콘센트 −20%, 조명 +15%, 공조 −20%, 외피 −30%, 재실 −20%']];
const sensitivity = { reference: { costSave: r2(refK.costSave.mean), kwhB: refK.kwhB, days: refK.n }, criteria: 'ASHRAE Guideline 14 (hourly): CV(RMSE) ≤ 30 %, |NMBE| ≤ 10 %',
  cases: SENS.map(([n, label]) => { const v = load('fb/sens_' + n), k = kpis(v); return { name: n, label, costSave: r2(k.costSave.mean), delta: r2(k.costSave.mean - refK.costSave.mean), kwhB: k.kwhB, kwhBChange: r1(pct(refK.kwhB, k.kwhB) * -1), ...g14(refH, hourly(v.s15.b, 1, 15)) }; }) };

const out = { generated: new Date().toISOString().slice(0, 10), ladder, scenarios, seasons: { source: WX.source, grid: WX.grid, months, annual, bySeason: seasons }, sensitivity };
mkdirSync('results', { recursive: true });
const dest = existsSync('../eval') && !existsSync('feedback.mjs') ? '../eval/results/feedback_summary.json' : 'results/feedback_summary.json';
writeFileSync(dest, JSON.stringify(out, null, 1));

// ---- printed tables ----
const cs = (k) => `${k.costSave.mean.toFixed(1)} ± ${k.costSave.ci.toFixed(1)}%`;
console.log('\n1 · 기준선 사다리 (8일, 입력 고정 | 시드 10회)');
for (const [n, k] of Object.entries(ladder)) console.log(`  ${n.padEnd(7)} ${cs(k).padEnd(14)} | ${k.seeds.mean.toFixed(1)} ± ${k.seeds.ci.toFixed(1)}%  peak ${k.peakA} vs ${k.peakB}  over ${k.overMinA}/${k.overMinB} min  comfort ${k.comfortA}/${k.comfortB}  disc ${k.discA}/${k.discB}  kWh ${k.energySave}%`);
console.log('\n2 · 시나리오 (기본 BMS | 숙련 BMS 대비 비용 절감, 최대 수전 A vs B, 한도 초과 분 A/B)');
for (const [s, r] of Object.entries(scenarios)) console.log(`  ${s.padEnd(9)} ${cs(r.basic).padEnd(14)} | ${cs(r.expert).padEnd(14)} peak ${r.expert.peakA} vs ${r.expert.peakB}  over ${r.expert.overMinA}/${r.expert.overMinB}  comfort ${r.expert.comfortA}/${r.expert.comfortB}`);
console.log('\n3 · 2025년 실제 기상 12개월 (heat=1) 비용 절감: 기본 | 센서 | 숙련,  쾌적 A / 기본 / 숙련');
for (const r of months) console.log(`  ${String(r.month).padStart(2)}월 ${String(r.weather.meanC).padStart(5)}°C  ${cs(r.basic).padEnd(13)} ${cs(r.sensor).padEnd(13)} ${cs(r.expert).padEnd(13)} comfort ${r.basic.comfortA}/${r.basic.comfortB}/${r.expert.comfortB}  peak ${r.basic.peakA} vs ${r.basic.peakB}/${r.expert.peakB}`);
console.log('  연간(비용 가중):', JSON.stringify(annual), '\n  계절:', JSON.stringify(seasons));
console.log('\n4 · 민감도 (기준 ' + sensitivity.reference.costSave + '%)');
for (const c of sensitivity.cases) console.log(`  ${c.label.padEnd(16)} ${c.costSave.toFixed(1).padStart(5)}% (${c.delta > 0 ? '+' : ''}${c.delta.toFixed(1)}%p)  BMS kWh ${c.kwhBChange > 0 ? '+' : ''}${c.kwhBChange}%  CV(RMSE) ${c.cvrmse}%  NMBE ${c.nmbe}%`);
console.log('\n→', dest);
