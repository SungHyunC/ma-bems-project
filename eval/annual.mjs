// node annual.mjs → results/annual_summary.json + printed tables
// A year at KEPCO prices (eval/README.md, "연중 요금·주말"): twelve months of real 2025 weather with a calendar (weekends,
// holidays) and the KEPCO seasonal tariff (make_kepco_data.py), against the three rule-based baselines, in two heating cases:
//   heatPump        ?heat=1: the campus heats with electric heat pumps (EHP), so heating is on the electricity bill
//   noElectricHeat  no heating in the model: the electricity bill of a campus heated by gas or district heat
// plus every day a weekday (basic BMS, heat pumps) to separate the effect of weekends.
// Energy charge = the simulated ₩ cost (mean of the scored days × days in the month). Demand charge = 8,320 ₩/kW·month ×
// the billing demand, which KEPCO sets to the highest 15-min demand of December, January, February, July, August,
// September and the current month (the year 2025 stands for the trailing twelve months). Demand counts in mid- and
// peak-period slots only (Sundays and holidays are off-peak all day); `all` gives the same with every slot.
// Raw runs: build/results/fb/kc_*, kg_*, kn_* (exp.mjs). Works in build/ or eval/.
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
const RAW = (n) => [`results/${n}.json`, `../build/results/${n}.json`].find((p) => existsSync(p));
const load = (n) => { const p = RAW(n); if (!p) throw new Error('missing run ' + n); return JSON.parse(readFileSync(p, 'utf8')); };
const DATA = (f) => JSON.parse(readFileSync(existsSync(`data/${f}`) ? `data/${f}` : `../eval/data/${f}`, 'utf8'));
const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
const r1 = (x) => Math.round(x * 10) / 10, r3 = (x) => Math.round(x * 1000) / 1000;
const pct = (b, a) => (b > 0 ? 100 * (b - a) / b : 0);
const T975 = { 25: 2.064, 26: 2.06, 27: 2.056, 28: 2.052, 29: 2.048, 30: 2.045 };
const META = DATA('kepco_2025_summary.json'), DEMAND = META.demandKRWperKWmonth;
const DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const BILL_MONTHS = [12, 1, 2, 7, 8, 9];
const BL = ['basic', 'sensor', 'expert'];

function tierAt(tou, code, h) {   // KEPCO metering: Saturday peak → mid, Sundays / public holidays all off-peak
  const inR = (rs) => rs.some(([a, b]) => h >= a && h < b);
  let t = inR(tou.peak) ? 'peak' : inR(tou.mid) ? 'mid' : 'off';
  if (code === 2) t = 'off'; else if (code === 1 && t === 'peak') t = 'mid';
  return t;
}
function monthRun(name, month, file) {
  const v = load(name), ds = DATA(file), days = ds.calendar ? ds.calendar.days : new Array(DAYS[month - 1]).fill(0);
  const D = v.days.filter((d) => d.day >= 2).map((d) => ({ A: d.agent, B: d.baseline }));   // day 0 (the 1st) is the warm-up
  const cs = D.map((d) => pct(d.B.cost, d.A.cost)), m = mean(cs), sd = Math.sqrt(cs.reduce((s, x) => s + (x - m) ** 2, 0) / (cs.length - 1));
  // 15-min demand from s15 (slot k = minutes 15k+1 … 15k+15), scored days only
  const peak = (arr, billable) => {
    let mx = 0;
    for (let k = 96; k < arr.length; k++) {
      const day = Math.floor(k / 96), h = (k % 96) / 4;
      if (day >= days.length) break;
      if (billable && tierAt(ds.tou, days[day], h) === 'off') continue;
      if (arr[k] > mx) mx = arr[k];
    }
    return mx;
  };
  const n = DAYS[month - 1];
  return {
    days: D.length, costSave: { mean: r3(m), ci: r3((T975[cs.length] || 2.0) * sd / Math.sqrt(cs.length)) },
    energyA: Math.round(mean(D.map((d) => d.A.cost)) * n), energyB: Math.round(mean(D.map((d) => d.B.cost)) * n),
    kwhA: Math.round(mean(D.map((d) => d.A.energyKWh)) * n), kwhB: Math.round(mean(D.map((d) => d.B.energyKWh)) * n),
    co2A: Math.round(mean(D.map((d) => d.A.co2Kg)) * n), co2B: Math.round(mean(D.map((d) => d.B.co2Kg)) * n),
    peakA: Math.round(peak(v.s15.a, true)), peakB: Math.round(peak(v.s15.b, true)), peakAllA: Math.round(peak(v.s15.a, false)), peakAllB: Math.round(peak(v.s15.b, false)),
    comfortA: r1(mean(D.map((d) => d.A.comfortPct))), comfortB: r1(mean(D.map((d) => d.B.comfortPct))),
    discA: Math.round(D.reduce((s, d) => s + d.A.discomfortDegH, 0)), discB: Math.round(D.reduce((s, d) => s + d.B.discomfortDegH, 0)),
  };
}
function yearOf(prefix, baselines, fileOf) {
  const months = [];
  for (let mo = 1; mo <= 12; mo++) {
    const row = { month: mo };
    for (const bl of baselines) row[bl] = monthRun(`fb/${prefix}_${String(mo).padStart(2, '0')}_${bl}`, mo, fileOf(mo));
    months.push(row);
  }
  const annual = {};
  for (const bl of baselines) {
    const R = months.map((r) => r[bl]), sum = (f) => R.reduce((s, x) => s + f(x), 0);
    const billing = (side, key) => {   // KEPCO billing demand per month and the year's demand charge
      const cap = Math.max(...BILL_MONTHS.map((mo) => months[mo - 1][bl][key + side]));
      const per = months.map((r) => Math.max(cap, r[bl][key + side]));
      return { perMonth: per, charge: per.reduce((s, x) => s + x * DEMAND, 0), max: Math.max(...per) };
    };
    const dA = billing('A', 'peak'), dB = billing('B', 'peak'), aA = billing('A', 'peakAll'), aB = billing('B', 'peakAll');
    const eA = sum((x) => x.energyA), eB = sum((x) => x.energyB);
    annual[bl] = {
      energyA: eA, energyB: eB, energySave: r1(pct(eB, eA)), energySaveKRW: eB - eA,
      kwhA: sum((x) => x.kwhA), kwhB: sum((x) => x.kwhB), kwhSave: r1(pct(sum((x) => x.kwhB), sum((x) => x.kwhA))),
      co2TonA: r1(sum((x) => x.co2A) / 1000), co2TonB: r1(sum((x) => x.co2B) / 1000), co2Save: r1(pct(sum((x) => x.co2B), sum((x) => x.co2A))),
      billingDemandA: dA.max, billingDemandB: dB.max, demandA: dA.charge, demandB: dB.charge, demandSaveKRW: dB.charge - dA.charge,
      totalA: eA + dA.charge, totalB: eB + dB.charge, totalSave: r1(pct(eB + dB.charge, eA + dA.charge)), totalSaveKRW: eB + dB.charge - eA - dA.charge,
      allSlots: { billingDemandA: aA.max, billingDemandB: aB.max, demandSaveKRW: aB.charge - aA.charge },
      comfortA: r1(sum((x) => x.comfortA * x.days) / sum((x) => x.days)), comfortB: r1(sum((x) => x.comfortB * x.days) / sum((x) => x.days)),
    };
  }
  return { months, annual };
}

const heatPump = yearOf('kc', BL, (mo) => `kepco_2025_${String(mo).padStart(2, '0')}.json`);
const noElectricHeat = yearOf('kg', BL, (mo) => `kepco_2025_${String(mo).padStart(2, '0')}.json`);
const weekdayOnly = yearOf('kn', ['basic'], (mo) => `kepco_2025_${String(mo).padStart(2, '0')}_weekday.json`);
const out = {
  generated: new Date().toISOString().slice(0, 10),
  tariff: { name: META.tariff, energyChargesFrom: META.energyChargesFrom, loadPeriods: META.loadPeriods, rates: META.ratesKRWperKWh, demandKRWperKWmonth: DEMAND, weekendMetering: META.weekendMetering },
  calendar: { holidays: META.holidays2025, temporaryHolidays: META.temporaryHolidays2025, offDayOccupancy: 'offices and labs at 25 % of a weekday (dorm unchanged); no meetings; 1 + 1 EV commuters instead of 6 + 4; no utility DR; the BMS office schedule off' },
  notIncluded: ['기후환경요금', '연료비조정요금', '전력산업기반기금', '부가가치세', 'semester breaks (방학)', 'gas or district-heat cost in the noElectricHeat case'],
  heatPump, noElectricHeat, weekdayOnly: { basic: weekdayOnly.annual.basic, months: weekdayOnly.months.map((r) => ({ month: r.month, costSave: r.basic.costSave })) },
};
mkdirSync('results', { recursive: true });
const dest = existsSync('annual.mjs') ? 'results/annual_summary.json' : '../eval/results/annual_summary.json';
writeFileSync(dest, JSON.stringify(out, null, 1));

const won = (x) => (x / 1e6).toFixed(1) + '백만';
for (const [title, Y] of [['전기 히트펌프 난방 (heat=1)', heatPump], ['전기 난방 없음 (가스·지역난방)', noElectricHeat]]) {
  console.log(`\n== ${title}: 월별 전력량요금 절감 (기본 | 센서 | 숙련), 15분 최대수요 kW 에이전트 vs 기본`);
  for (const r of Y.months) console.log(`  ${String(r.month).padStart(2)}월  ${BL.map((b) => (r[b].costSave.mean.toFixed(1) + '±' + r[b].costSave.ci.toFixed(1)).padStart(9)).join(' ')}   ${r.basic.peakA} vs ${r.basic.peakB}   쾌적 ${r.basic.comfortA}/${r.basic.comfortB}/${r.expert.comfortB}`);
  for (const b of BL) { const a = Y.annual[b]; console.log(`  연간 vs ${b.padEnd(6)} 전력량요금 ${won(a.energyA)} vs ${won(a.energyB)} (${a.energySave}%, ${won(a.energySaveKRW)}) · 요금적용전력 ${a.billingDemandA} vs ${a.billingDemandB} kW · 기본요금 절감 ${won(a.demandSaveKRW)} · 합계 ${a.totalSave}% (${won(a.totalSaveKRW)}) · kWh ${a.kwhSave}%`); }
}
const w = weekdayOnly.annual.basic, c = heatPump.annual.basic;
console.log(`\n== 주말 효과 (기본 BMS, 히트펌프): 모든 날 평일 ${w.energySave}% → 주말·공휴일 반영 ${c.energySave}% (전력량요금)`);
console.log('→', dest);
