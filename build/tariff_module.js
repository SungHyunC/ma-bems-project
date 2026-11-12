/* ---------- KEPCO tariff + measured campus sample (ported from BEMS backend/tariff.py, BDG2 Fox site) ----------
   Two presets in the dataset dialog. Both load through the dialog's normal preview → Apply path, so the
   simulation rebases its cost counters to ₩ like any dataset with a price column. While a KEPCO dataset is
   active the load-period hours follow the 2026-06-01 edition (peak 15-21 h, mid 08-15 / 21-22 h), and the
   agents' pre-cooling, ESS discharge and recovery windows move with them (TOU_HOURS / PK in section 1). */
const KEPCO = {
  name: '한전 일반용전력(을) 고압A 선택 II', edition: '2026-06-01', demandKRWperKWmonth: 8320,
  rates: { summer: { off: 87.3, mid: 140.2, peak: 222.3 }, spring_fall: { off: 87.3, mid: 109.8, peak: 140.5 } },
  hours: { peak: [[15, 21]], mid: [[8, 15], [21, 22]] },             // 2026 summer / spring-fall hours (winter has two peak windows: not modelled)
  active: false, season: 'summer',
};
const TOU_DEFAULT = JSON.parse(JSON.stringify(TOU_HOURS));
function kepcoTier(h) { const inR = (rs) => rs.some(([a, b]) => h >= a && h < b); return inR(KEPCO.hours.peak) ? 'peak' : inR(KEPCO.hours.mid) ? 'mid' : 'off'; }
function kepcoSetHours(on) {
  KEPCO.active = !!on;
  const src = on ? KEPCO.hours : TOU_DEFAULT;
  TOU_HOURS.peak = src.peak.map((r) => r.slice()); TOU_HOURS.mid = src.mid.map((r) => r.slice());
}
Bus.on('dataset', (d) => { if (d && d.ok) kepcoSetHours(!!d.name && /한전|KEPCO/.test(d.name)); });
i18nAdd({
  en: { 'kp.btn': 'KEPCO tariff', 'kp.btn.title': 'KEPCO general service (B) high-voltage A, option II — 2026 edition, weekday prices in ₩/kWh', 'kp.summer': 'Summer (Jun–Aug)', 'kp.spring_fall': 'Spring / autumn (Mar–May, Sep–Oct)',
    'kp.name': 'KEPCO general (B) HV-A option II · 2026 · {s} weekday', 'kp.real': 'Measured campus (BDG2) + KEPCO',
    'kp.real.title': 'One measured summer weekday from four buildings of a US university campus (Building Data Genome 2, CC BY-SA 4.0), rescaled to the Helio buildings, with KEPCO 2026 summer prices',
    'kp.real.name': 'BDG2 Fox campus measured load (2017-07-12) + KEPCO 2026 summer', 'kp.real.err': 'Could not load the measured sample ({m}). Start the dashboard with server/mabems_server.py.' },
  ko: { 'kp.btn': '한전 요금표', 'kp.btn.title': '한전 일반용전력(을) 고압A 선택 II — 2026년판, 평일 요금(₩/kWh)', 'kp.summer': '여름철(6–8월)', 'kp.spring_fall': '봄·가을철(3–5, 9–10월)',
    'kp.name': '한전 일반용(을) 고압A 선택II · 2026 · {s} 평일', 'kp.real': '실측 캠퍼스(BDG2) + 한전 요금',
    'kp.real.title': '미국 대학 캠퍼스 4개 건물의 여름 평일 실측 부하(Building Data Genome 2, CC BY-SA 4.0)를 헬리오 캠퍼스 규모로 환산하고 한전 2026 여름 요금을 붙인 샘플',
    'kp.real.name': 'BDG2 Fox 캠퍼스 실측 부하(2017-07-12) + 한전 2026 여름 요금', 'kp.real.err': '실측 샘플을 불러오지 못했습니다({m}). server/mabems_server.py로 실행해 주세요.' },
});
function kepcoTable(season) {
  const R = KEPCO.rates[season] || KEPCO.rates.summer, rows = [];
  for (let q = 0; q < 96; q++) { const h = q / 4; rows.push([`2026-07-15 ${String(Math.floor(h)).padStart(2, '0')}:${String((q % 4) * 15).padStart(2, '0')}`, R[kepcoTier(h)]]); }   // 15-min steps: the sim interpolates between rows
  return { headers: ['timestamp', 'price (₩/kWh)'], rows, fmt: 'csv', meta: { file: `kepco-2026-${season}.csv`, enc: '' },
    preset: { name: t('kp.name', { s: t('kp.' + season) }), currency: '₩' } };
}
async function kepcoRealSample() {
  try {
    if (location.protocol === 'file:') throw new Error('file://');
    const r = await fetch('data/bdg2-fox-campus-2017-07-12.csv', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const T = dtFromCSV(await r.text());
    T.meta = { file: 'bdg2-fox-campus-2017-07-12.csv', enc: 'utf-8' }; T.preset = { name: t('kp.real.name'), currency: '₩' };
    dtSetTable(T);
  } catch (e) { dtStatus('err', t('kp.real.err', { m: e && e.message ? e.message : String(e) })); }
}
// ---------- shadow mode: a meter CSV (timestamp + building kW, 15-min / 30-min / hourly, ≥ 1 day) ----------
// Goes through the same dataset path as the BDG2 sample: the single kW series is rescaled to the campus size (shape kept),
// split over B1–B4 with the BDG2 sample's shares, priced with the KEPCO 2026 summer weekday table, and loaded into the
// dataset dialog (Apply feeds the live simulation). The savings are measured in a private second simulator (createLocalSim)
// that replays the series for one warm-up day plus every day of the file, agents against the rule-based BMS on the same
// input. It runs synchronously with the shared dataset / tariff globals swapped in and restored in `finally`, so the live
// simulation cannot be disturbed.
const SH = { maxDays: 14, maxBytes: 5 * 1048576, campusKW: 599.48, share: [0.1154, 0.2928, 0.1234, 0.4684], last: null, busy: false };
i18nAdd({
  en: { 'kp.sh': 'Shadow mode: meter CSV…', 'kp.sh.title': 'Load a CSV of building load (timestamp, kW; 15-min, 30-min or hourly; at least one day) and see what the agents would have saved against the rule-based BMS',
    'kp.sh.name': 'Shadow meter {f} + KEPCO 2026 summer', 'kp.sh.run': 'Simulating {n} day(s) of {f} with agents and the rule-based BMS…',
    'kp.sh.e.big': 'File too large ({mb} MB; limit {max} MB).', 'kp.sh.e.rows': 'Too few rows: a header line and at least two readings are needed.',
    'kp.sh.e.time': 'No timestamp column found. Put timestamps like 2025-07-12 00:15 in the first column.', 'kp.sh.e.kw': 'No kW column found. Name it "kW", "power" or "load".',
    'kp.sh.e.multi': 'Several numeric columns ({cols}) and none named kW/power/load. Keep one load column or name it "kW".',
    'kp.sh.e.badts': 'Line {line}: "{v}" is not a timestamp.', 'kp.sh.e.badnum': 'Line {line}: "{v}" is not a number (kW column "{col}").', 'kp.sh.e.neg': 'Line {line}: negative load ({v}). Export or net-metered values are not supported.',
    'kp.sh.e.dup': 'Duplicate timestamp {v}.', 'kp.sh.e.step': 'Reading interval is {n} min; use 15, 30 or 60 minutes.',
    'kp.sh.e.gaplong': 'Gap of {n} h before {v}; gaps over 3 h are not filled. Fix the file or split it.', 'kp.sh.e.gaps': '{pct}% of the readings are missing; at most 10% can be filled.',
    'kp.sh.e.short': 'Only {h} h of data; at least 1 day (24 h) is required.', 'kp.sh.e.flat': 'The load is zero or constant everywhere; nothing to simulate.', 'kp.sh.e.big2': 'Values above 10 000 000 kW: check the unit.',
    'kp.sh.e.run': 'Simulation failed ({m}).', 'kp.sh.e.build': 'Could not build the dataset: {m}',
    'kp.sh.w.nohdr': 'No header line: column 1 is read as the timestamp, column 2 as kW.', 'kp.sh.w.kwh': 'Column "{col}" is kWh: converted to kW for the {n}-min interval.',
    'kp.sh.w.fill': '{n} missing readings filled by interpolation.', 'kp.sh.w.trunc': 'Only the first {d} days are used.', 'kp.sh.w.scale': 'Rescaled to the campus size (mean {a} → {b} kW), shape kept; weekday KEPCO summer prices.',
    'kp.sh.h': 'Shadow result: {f}, {n} day(s) after one warm-up day', 'kp.sh.cost': 'Cost', 'kp.sh.peak': 'Highest import', 'kp.sh.comfort': 'Comfort', 'kp.sh.energy': 'Energy',
    'kp.sh.agents': 'Agents', 'kp.sh.bms': 'Rule BMS', 'kp.sh.saved': 'Saved {amt} ({pct}%) over the period against the rule-based BMS.', 'kp.sh.more': 'Costs more by {amt} ({pct}%) than the rule-based BMS over the period.',
    'kp.sh.note': 'Simulated with the campus model on this load shape, not a metered result. "Apply to simulation" above feeds the same series to the live run.' },
  ko: { 'kp.sh': '섀도 모드: 계량 CSV…', 'kp.sh.title': '건물 부하 CSV(시각, kW; 15분·30분·1시간 간격; 최소 1일)를 불러와 에이전트가 룰 기반 BMS 대비 얼마나 절감했을지 계산합니다',
    'kp.sh.name': '섀도 계량 {f} + 한전 2026 여름 요금', 'kp.sh.run': '{f}의 {n}일을 에이전트와 룰 기반 BMS로 시뮬레이션하는 중…',
    'kp.sh.e.big': '파일이 너무 큽니다({mb} MB, 한도 {max} MB).', 'kp.sh.e.rows': '행이 부족합니다: 머리글 한 줄과 측정값 두 개 이상이 필요합니다.',
    'kp.sh.e.time': '시각 열을 찾지 못했습니다. 첫 열에 2025-07-12 00:15 같은 시각을 넣어 주세요.', 'kp.sh.e.kw': 'kW 열을 찾지 못했습니다. 열 이름을 "kW", "power", "load" 중 하나로 해 주세요.',
    'kp.sh.e.multi': '숫자 열이 여러 개({cols})인데 kW/power/load 이름이 없습니다. 부하 열 하나만 두거나 이름을 "kW"로 바꿔 주세요.',
    'kp.sh.e.badts': '{line}번째 줄: "{v}"은(는) 시각이 아닙니다.', 'kp.sh.e.badnum': '{line}번째 줄: "{v}"은(는) 숫자가 아닙니다(kW 열 "{col}").', 'kp.sh.e.neg': '{line}번째 줄: 음수 부하({v}). 역송·순계량 값은 지원하지 않습니다.',
    'kp.sh.e.dup': '시각이 중복되었습니다: {v}.', 'kp.sh.e.step': '측정 간격이 {n}분입니다. 15분, 30분, 60분 중 하나여야 합니다.',
    'kp.sh.e.gaplong': '{v} 직전에 {n}시간 공백이 있습니다. 3시간 넘는 공백은 채우지 않습니다. 파일을 고치거나 나눠 주세요.', 'kp.sh.e.gaps': '측정값의 {pct}%가 비어 있습니다. 10%까지만 보간할 수 있습니다.',
    'kp.sh.e.short': '데이터가 {h}시간뿐입니다. 최소 1일(24시간)이 필요합니다.', 'kp.sh.e.flat': '부하가 전부 0이거나 일정해 시뮬레이션할 것이 없습니다.', 'kp.sh.e.big2': '1천만 kW를 넘는 값이 있습니다. 단위를 확인해 주세요.',
    'kp.sh.e.run': '시뮬레이션 실패({m}).', 'kp.sh.e.build': '데이터셋을 만들지 못했습니다: {m}',
    'kp.sh.w.nohdr': '머리글이 없어 1열을 시각, 2열을 kW로 읽었습니다.', 'kp.sh.w.kwh': '"{col}" 열은 kWh입니다. {n}분 간격에 맞춰 kW로 환산했습니다.',
    'kp.sh.w.fill': '비어 있던 측정값 {n}개를 보간했습니다.', 'kp.sh.w.trunc': '처음 {d}일만 사용합니다.', 'kp.sh.w.scale': '캠퍼스 규모에 맞게 환산(평균 {a} → {b} kW)하고 모양은 유지, 한전 여름 평일 요금을 적용했습니다.',
    'kp.sh.h': '섀도 결과: {f}, 준비 1일 뒤 {n}일', 'kp.sh.cost': '비용', 'kp.sh.peak': '최대 수전', 'kp.sh.comfort': '쾌적', 'kp.sh.energy': '에너지',
    'kp.sh.agents': '에이전트', 'kp.sh.bms': '룰 BMS', 'kp.sh.saved': '해당 기간 룰 기반 BMS보다 {amt}({pct}%) 절감했을 것입니다.', 'kp.sh.more': '해당 기간 룰 기반 BMS보다 {amt}({pct}%) 더 들었을 것입니다.',
    'kp.sh.note': '이 부하 모양에 캠퍼스 모델을 돌린 시뮬레이션이며 실측 결과가 아닙니다. 위의 "시뮬레이션에 적용"을 누르면 같은 데이터가 실시간 실행에도 들어갑니다.' },
});
const shErr = (key, p) => ({ err: { key: 'kp.sh.e.' + key, p: p || {} } });
function shadowParse(text, file) {
  text = String(text).replace(/^﻿/, '');
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 3) return shErr('rows');
  const cnt = (d) => lines[0].split(d).length;
  const delim = [',', ';', '\t'].sort((a, b) => cnt(b) - cnt(a))[0];
  const rows = dtSplitCSV(text, delim).map((r) => r.map((c) => c.trim()));
  const isTs = (v) => /^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|^\d{8}/.test(String(v)) && Number.isFinite(dtTime(v));
  const warn = [];
  const hasHeader = !isTs(rows[0][0]);
  if (!hasHeader) warn.push({ key: 'kp.sh.w.nohdr', p: {} });
  const head = hasHeader ? rows[0] : rows[0].map((_, i) => (i === 0 ? 'timestamp' : i === 1 ? 'kW' : 'col' + (i + 1)));
  const body = rows.slice(hasHeader ? 1 : 0), first = hasHeader ? 2 : 1;   // first = line number of body[0]
  if (body.length < 2) return shErr('rows');
  const dec = delim === ';' && body.slice(0, 50).some((r) => r.some((c) => /^-?\d+,\d+$/.test(c)));
  const frac = (c) => { const ok = body.filter((r) => r[c] !== undefined && r[c] !== '' && isTs(r[c])).length; return ok / body.length; };
  let tc = -1; for (let c = 0; c < Math.min(3, head.length); c++) if (frac(c) >= 0.9) { tc = c; break; }
  if (tc < 0) return shErr('time');
  const num = (c) => body.filter((r) => Number.isFinite(dtNum(r[c], dec))).length / body.length;
  const named = head.map((h, c) => (c !== tc && /(^|[^a-z])(kw|kwh|power|load|demand|elec)|전력|부하|사용량/i.test(h) ? c : -1)).filter((c) => c >= 0);
  const nums = head.map((_, c) => c).filter((c) => c !== tc && num(c) >= 0.5);
  let kc = named.length ? named.find((c) => num(c) >= 0.5) : -1;
  if (kc === undefined || kc < 0) {
    if (named.length) kc = named[0];
    else if (nums.length === 1) kc = nums[0];
    else if (nums.length > 1) return shErr('multi', { cols: nums.map((c) => head[c]).join(', ') });
    else return shErr('kw');
  }
  const col = head[kc] || 'kW', kwh = /kwh/i.test(col) && !/kw(?!h)/i.test(col.replace(/kwh/gi, ''));
  const pts = [], seen = new Set();
  for (let i = 0; i < body.length; i++) {
    const r = body[i], line = first + i, tv = r[tc], kv = r[kc];
    if (r.length < 2 && !tv) continue;
    const m = dtTime(tv); if (!isTs(tv)) return shErr('badts', { line, v: String(tv).slice(0, 30) });
    if (seen.has(m)) return shErr('dup', { v: String(tv).slice(0, 30) });
    seen.add(m);
    const missing = kv === undefined || kv === '' || /^(na|n\/a|nan|null|none|-|--)$/i.test(kv);
    if (missing) { pts.push([m, NaN]); continue; }
    const v = dtNum(kv, dec); if (!Number.isFinite(v)) return shErr('badnum', { line, v: String(kv).slice(0, 30), col });
    if (v < 0) return shErr('neg', { line, v: String(kv).slice(0, 20) });
    if (v > 1e7) return shErr('big2');
    pts.push([m, v]);
  }
  pts.sort((a, b) => a[0] - b[0]);
  const diffs = pts.slice(1).map((p, k) => p[0] - pts[k][0]).sort((a, b) => a - b), step = diffs.length ? diffs[diffs.length >> 1] : 0;
  if (![15, 30, 60].includes(step)) return shErr('step', { n: step });
  const span = pts[pts.length - 1][0] - pts[0][0] + step;
  if (span < 1440) return shErr('short', { h: fmt(span / 60, 1) });
  for (let k = 1; k < pts.length; k++) {                       // gaps: rows that are absent, and rows with an empty value
    const g = pts[k][0] - pts[k - 1][0];
    if (g > 180) return shErr('gaplong', { n: fmt(g / 60, 1), v: dtFmtMin(pts[k][0]) });
  }
  let run = null, runStart = 0;
  for (let k = 0; k <= pts.length; k++) {
    const bad = k < pts.length && Number.isNaN(pts[k][1]);
    if (bad && run === null) { run = k; runStart = pts[k][0]; }
    if (!bad && run !== null) { const len = pts[k - 1][0] - runStart + step * 2; if (len > 180) return shErr('gaplong', { n: fmt(len / 60, 1), v: dtFmtMin(pts[k] ? pts[k][0] : pts[k - 1][0]) }); run = null; }
  }
  const slots = Math.floor(span / step), have = pts.filter((p) => Number.isFinite(p[1])).length, miss = slots - have;
  if (miss / slots > 0.1) return shErr('gaps', { pct: fmt(100 * miss / slots, 0) });
  if (miss > 0) warn.push({ key: 'kp.sh.w.fill', p: { n: fmt(miss) } });
  let days = Math.floor(span / 1440), keep = pts;
  if (days > SH.maxDays) { days = SH.maxDays; keep = pts.filter((p) => p[0] < pts[0][0] + days * 1440); warn.push({ key: 'kp.sh.w.trunc', p: { d: days } }); }
  const k = kwh ? 60 / step : 1;
  if (kwh) warn.push({ key: 'kp.sh.w.kwh', p: { col, n: step } });
  const vals = keep.filter((p) => Number.isFinite(p[1])).map((p) => p[1] * k);
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  if (!(mean > 0) || Math.max(...vals) - Math.min(...vals) < 1e-9 * Math.max(1, mean)) return shErr('flat');
  const f = SH.campusKW / mean;
  warn.push({ key: 'kp.sh.w.scale', p: { a: fmt(mean, 1), b: fmt(SH.campusKW, 0) } });
  const ts = (m) => { const d = new Date(m * 60000), z = (x) => String(x).padStart(2, '0'); return `${d.getUTCFullYear()}-${z(d.getUTCMonth() + 1)}-${z(d.getUTCDate())} ${z(d.getUTCHours())}:${z(d.getUTCMinutes())}`; };
  const R = KEPCO.rates.summer, out = keep.map((p) => {
    const v = Number.isFinite(p[1]) ? p[1] * k * f : null, h = (((p[0] % 1440) + 1440) % 1440) / 60;
    return [ts(p[0]), ...SH.share.map((s) => (v === null ? '' : String(Math.round(v * s * 10) / 10))), String(R[kepcoTier(h)])];
  });
  return { T: { headers: ['timestamp', 'load_B1', 'load_B2', 'load_B3', 'load_B4', 'price (₩/kWh)'], rows: out, fmt: 'CSV', meta: { file, enc: 'utf-8' }, preset: { name: t('kp.sh.name', { f: file }), currency: '₩' } }, warn, days, file };
}
function shadowSim(D, days) {                                    // → the archived days (day 0 = warm-up), agents vs baseline
  const prevData = simData, prevKepco = KEPCO.active;
  try {
    kepcoSetHours(true);
    const bus = createBus(), sim = createLocalSim(bus); let snap = null;
    bus.on('tick', (s) => { snap = s; });
    sim.command({ type: 'dataset', data: D });
    sim.start(0);
    sim.command({ type: 'speed', value: 240 });                 // 60 one-minute steps per update
    const end = (days + 1) * 1440;
    while (snap.T < end) sim.update(0.25);
    return snap.metrics.days.slice(-(days + 1)).slice(1);
  } finally { simData = prevData; kepcoSetHours(prevKepco); }
}
function shadowRender() {
  const el = document.getElementById('kpShadowOut'); if (!el) return;
  const r = SH.last;
  if (!r) { el.style.display = 'none'; el.innerHTML = ''; return; }
  el.style.display = 'block';
  const box = (c, h) => `<div style="margin:8px 0;padding:8px 10px;border-radius:10px;border:1px solid var(--line);background:${c};font-size:12px;line-height:1.55">${h}</div>`;
  if (r.busy) { el.innerHTML = box('#fff', uiEsc(t('kp.sh.run', { n: r.days, f: r.file }))); return; }
  if (r.err) { el.innerHTML = box('rgba(179,38,30,.07)', `<span style="color:#B3261E">${uiEsc(t(r.err.key, r.err.p))}</span>`); return; }
  const D = r.days, sum = (k, f) => D.reduce((a, d) => a + d[k][f], 0), mean = (k, f) => sum(k, f) / D.length, mx = (k, f) => Math.max(...D.map((d) => d[k][f]));
  const cur = (D[0] && D[0].currency) || '₩', m = (v) => cur + fmt(v, cur === '₩' ? 0 : 2);
  const cA = sum('agent', 'cost'), cB = sum('baseline', 'cost'), diff = cB - cA, pct = cB > 0 ? 100 * Math.abs(diff) / cB : 0;
  const row = (lab, a, b) => `<tr><td>${uiEsc(lab)}</td><td style="text-align:right">${a}</td><td style="text-align:right">${b}</td></tr>`;
  el.innerHTML = box('#fff', `<b>${uiEsc(t('kp.sh.h', { f: r.file, n: D.length }))}</b>
    <table style="width:100%;border-collapse:collapse;margin:4px 0"><thead><tr><th></th><th style="text-align:right">${uiEsc(t('kp.sh.agents'))}</th><th style="text-align:right">${uiEsc(t('kp.sh.bms'))}</th></tr></thead><tbody>
    ${row(t('kp.sh.cost'), m(cA), m(cB))}${row(t('kp.sh.peak'), fmt(mx('agent', 'peakKW')) + ' kW', fmt(mx('baseline', 'peakKW')) + ' kW')}
    ${row(t('kp.sh.comfort'), fmt(mean('agent', 'comfortPct'), 1) + '%', fmt(mean('baseline', 'comfortPct'), 1) + '%')}${row(t('kp.sh.energy'), fmt(sum('agent', 'energyKWh')) + ' kWh', fmt(sum('baseline', 'energyKWh')) + ' kWh')}</tbody></table>
    <div><b>${uiEsc(t(diff >= 0 ? 'kp.sh.saved' : 'kp.sh.more', { amt: m(Math.abs(diff)), pct: fmt(pct, 1) }))}</b></div>
    ${r.warn.map((w) => `<div style="color:var(--ink-3)">${uiEsc(t(w.key, w.p))}</div>`).join('')}<div style="color:var(--ink-3)">${uiEsc(t('kp.sh.note'))}</div>`);
}
async function shadowLoad(file) {
  if (!file || SH.busy) return;
  if (file.size > SH.maxBytes) { SH.last = shErr('big', { mb: (file.size / 1048576).toFixed(1), max: SH.maxBytes / 1048576 }); shadowRender(); return; }
  let P;
  try { P = shadowParse(dtDecode(await file.arrayBuffer()).text, file.name); } catch (e) { P = shErr('build', { m: e && e.message ? e.message : String(e) }); }
  if (P.err) { SH.last = P; shadowRender(); return; }
  SH.busy = true; SH.last = { busy: true, days: P.days, file: file.name }; shadowRender();
  await new Promise((r) => setTimeout(r, 40));                   // let the 'running' line paint before the synchronous run
  try {
    dtSetTable(P.T);                                             // same preview → Apply path as the BDG2 sample
    const B = dtBuild();
    if (!B.D) { SH.last = shErr('build', { m: B.error || '?' }); return; }
    const days = shadowSim(B.D, P.days);
    SH.last = { days, warn: P.warn, file: file.name };
  } catch (e) { SH.last = shErr('run', { m: e && e.message ? e.message : String(e) }); }
  finally { SH.busy = false; shadowRender(); }
}

{
  const anchor = document.getElementById('dtTemplate');
  if (anchor) {
    const wrap = document.createElement('span'); wrap.className = 'kp-row';
    wrap.innerHTML = `<button id="kpBtn" class="btn" type="button"></button><select id="kpSeason" class="dt-in"><option value="summer"></option><option value="spring_fall"></option></select><button id="kpReal" class="btn" type="button"></button><button id="kpShadow" class="btn" type="button"></button><input id="kpShadowFile" type="file" accept=".csv,.txt,text/csv" hidden>`;
    anchor.parentNode.insertBefore(wrap, anchor.nextSibling);
    const texts = () => {
      document.getElementById('kpBtn').textContent = t('kp.btn'); document.getElementById('kpBtn').title = t('kp.btn.title');
      document.getElementById('kpReal').textContent = t('kp.real'); document.getElementById('kpReal').title = t('kp.real.title');
      document.getElementById('kpShadow').textContent = t('kp.sh'); document.getElementById('kpShadow').title = t('kp.sh.title'); shadowRender();
      const sel = document.getElementById('kpSeason'); sel.options[0].textContent = t('kp.summer'); sel.options[1].textContent = t('kp.spring_fall');
    };
    texts(); onLang(texts);
    document.getElementById('kpBtn').onclick = () => dtSetTable(kepcoTable(document.getElementById('kpSeason').value));
    document.getElementById('kpReal').onclick = kepcoRealSample;
    const out = document.createElement('div'); out.id = 'kpShadowOut'; out.style.display = 'none'; wrap.parentNode.insertBefore(out, wrap.nextSibling);
    document.getElementById('kpShadow').onclick = () => document.getElementById('kpShadowFile').click();
    document.getElementById('kpShadowFile').addEventListener('change', (e) => { const f = e.target.files && e.target.files[0]; e.target.value = ''; shadowLoad(f); });
  }
}
