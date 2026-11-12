/* =====================================================================
   SECTION 7g — LOAD FORECAST + FAULT DETECTION (ported from the BEMS projects)
   ---------------------------------------------------------------------
   Forecast (BEMS backend/energy_management.py + New_BEMS twin regression): grid import per 15-min slot, made at the
     start of slot n from what is known then (observations through slot n-1), never from the future:
       weather    temperature = yesterday's observed profile + today's current difference to yesterday (fading over
                  ~4 h); irradiance = clear-sky curve × the clear-sky index of the last daylight slot (smart persistence)
       occupancy  the deterministic timetable profile occAt() (scheduled hours), not the realised people count
       lags       the same slot yesterday (observed), and the last observed slot's residual carried forward by the
                  residuals' autocorrelation at that lead time
     Ridge regression on the last 3 days of slots, refitted every slot (10 features; + the yesterday lag once a day of
     history exists); band = empirical 90 % of past 1-h-ahead errors. Accuracy is scored like ASHRAE Guideline 14
     (CV(RMSE), NMBE) on every 1-hour-ahead prediction (target slot starts 60 min after it is made). Until 2026-11 the
     regression read the actual weather at the target time (an oracle) and switched to a seasonal-naive model (yesterday ×
     recent ratio) by recent error; that switch made the 1-h error worse (11.0 % vs 8.2 % for the regression alone), and
     blending with it still did in the replay tests (+0.3 to +1 pp), so it was dropped.
     ?coord=v2 runs a second copy on the net load before the battery (load − PV) for the coordinator (NET_FC).
   FDD (BEMS simulator.py, New_BEMS hvac/comfort agents, multi-agent-bems monitor rules): a sensor layer
     (measured room temperature = truth + noise, or a fault: stuck / drift / dropout) sampled every 5 min.
     Virtual sensor = room setpoint + median tracking error of conditioned neighbours + learned room offset.
     stuck: 45 min without any change · dropout: 15 min missing · drift: the reading departs by > 1.6 °C for 15 min
     from both the neighbours (rP) and the room's own normal tracking (rA), judged only in rooms conditioned at a steady
     setpoint for 30 min, after 3 h of learning, and with at least one conditioned neighbour on the floor.
     Tuning history (8-day runs, 134 rooms): the first rule raised 150 false alarms in about 2 days; each condition above
     removed one cause (floating rooms, healthy neighbours of a bad sensor, cold start, setpoint steps, lone night rooms).
     Detections become approval cards (human in the loop, BEMS operating_policy): approve → virtual sensor
     replaces the reading and a repair is logged; dismiss → counted as a false alarm, room muted for 2 h.
     Evaluation switches: ?fddNoise=σ (Gaussian sensor noise, °C; default the original ±0.04 °C), ?fdd=off (no
     detection), ?faultImpact=1 (the VAV loops act on the readings: a faulty sensor misleads its room until FDD flags it,
     then the virtual sensor takes over; the rule-based BMS has no FDD and keeps the faulty reading).
   ===================================================================== */
const FDD = { rooms: {}, faults: {}, bfaults: {}, alarms: {}, log: [], k: -1, stats: { injected: 0, detected: 0, falseAlarms: 0, delays: [], byType: {} } };
i18nAdd({
  en: {
    'fc.legend': 'Forecast (90 %)', 'fc.chip': 'Forecast max {kw} kW at {t}', 'fc.risk': 'Peak risk {t} · {kw} kW ({p} %)',
    'fdd.title': 'Fault detection — needs your decision', 'fdd.stuck': 'temperature sensor stuck', 'fdd.drift': 'temperature sensor drifting', 'fdd.dropout': 'temperature sensor not reporting',
    'fdd.alert': '{room}: {what}', 'fdd.sub': 'measured {m} · virtual {v} · detected after {d} min', 'fdd.sub2': 'measured {m} · virtual {v} · flagged at {t}',
    'fdd.act.stuck': 'Use the virtual sensor for control and send a technician', 'fdd.act.drift': 'Use the virtual sensor for control and recalibrate', 'fdd.act.dropout': 'Use the zone average and check the network link',
    'fdd.approve': 'Approve', 'fdd.dismiss': 'Not a fault', 'fdd.ok': 'Approved: {room} now runs on the virtual sensor; repair logged.', 'fdd.no': 'Marked as a false alarm: {room} muted for 2 h.',
    'fdd.inject': 'Sensor fault drill (demo)', 'fdd.inj.stuck': 'Stuck', 'fdd.inj.drift': 'Drift', 'fdd.inj.dropout': 'Dropout', 'fdd.injected': 'Injected a {what} fault in {room} — watch the detector.',
    'fdd.state.ok': 'Sensor OK', 'fdd.state.virtual': 'Virtual sensor in use', 'fdd.state.flag': 'Fault suspected',
  },
  ko: {
    'fc.legend': '예측(90% 범위)', 'fc.chip': '예측 최대 {kw} kW · {t}', 'fc.risk': '피크 위험 {t} · {kw} kW ({p}%)',
    'fdd.title': '이상 감지 — 승인이 필요합니다', 'fdd.stuck': '온도 센서 고착 의심', 'fdd.drift': '온도 센서 드리프트 의심', 'fdd.dropout': '온도 센서 응답 없음',
    'fdd.alert': '{room}: {what}', 'fdd.sub': '측정 {m} · 가상 센서 {v} · 감지까지 {d}분', 'fdd.sub2': '측정 {m} · 가상 센서 {v} · {t} 감지',
    'fdd.act.stuck': '가상 센서로 제어 입력을 대체하고 점검을 요청합니다', 'fdd.act.drift': '가상 센서로 대체하고 센서 보정을 요청합니다', 'fdd.act.dropout': '존 평균으로 대체하고 통신 점검을 요청합니다',
    'fdd.approve': '승인', 'fdd.dismiss': '고장 아님', 'fdd.ok': '승인됨: {room}은 가상 센서로 제어하며 수리 요청을 기록했습니다.', 'fdd.no': '오경보로 표시: {room} 알림을 2시간 쉽니다.',
    'fdd.inject': '센서 고장 훈련(시연용)', 'fdd.inj.stuck': '고착', 'fdd.inj.drift': '드리프트', 'fdd.inj.dropout': '끊김', 'fdd.injected': '{room}에 {what} 고장을 주입했습니다 — 감지되는지 지켜보세요.',
    'fdd.state.ok': '센서 정상', 'fdd.state.virtual': '가상 센서 사용 중', 'fdd.state.flag': '고장 의심',
  },
});
const fcHM = (slot) => `${String(Math.floor(slot / 4) % 24).padStart(2, '0')}:${String((slot % 4) * 15).padStart(2, '0')}`;

// ---------- forecast ----------
function fcRidge(rows, lam) {                               // ridge regression, normal equations + Gauss-Jordan
  const n = rows[0].x.length, A = Array.from({ length: n }, () => new Array(n).fill(0)), b = new Array(n).fill(0);
  for (const s of rows) for (let i = 0; i < n; i++) { b[i] += s.x[i] * s.y; for (let j = 0; j < n; j++) A[i][j] += s.x[i] * s.x[j]; }
  for (let i = 1; i < n; i++) A[i][i] += lam;               // intercept unpenalised
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    [A[c], A[p]] = [A[p], A[c]]; [b[c], b[p]] = [b[p], b[c]];
    const d = A[c][c] || 1e-9;
    for (let j = 0; j < n; j++) A[c][j] /= d; b[c] /= d;
    for (let r = 0; r < n; r++) if (r !== c) { const f = A[r][c]; if (f) { for (let j = 0; j < n; j++) A[r][j] -= f * A[c][j]; b[r] -= f * b[c]; } }
  }
  return b;
}
const fcDot = (w, x) => { let s = 0; for (let i = 0; i < w.length; i++) s += w[i] * x[i]; return s; };
// one forecaster per series: valueOf(snapshot) → kW (grid import for the dashboard, net load for coordinator v2)
function fcMake(valueOf) {
  const F = { y: {}, wx: {}, cur: null, rows: [], preds: {}, scored: [], err: [], wA: null, wB: null, res: {}, acf: [], k: 1, band: null, out: null };
  const csAt = (a) => clearSkyIrr(((((a * 15 + 7.5) % 1440) + 1440) % 1440) / 60);
  function wxHat(a, n) {                                    // weather of slot a as known at the start of slot n
    const L = F.wx[n - 1]; if (!L) return null;
    const yd = F.wx[a - 96], ydL = F.wx[n - 1 - 96];
    const tout = yd && ydL ? yd.tout + (L.tout - ydL.tout) * Math.exp(-(a - n + 1) / 16) : L.tout;
    return { tout, irr: csAt(a) * F.k };
  }
  function feat(a, w) {
    const T = a * 15 + 7.5, h = (((T % 1440) + 1440) % 1440) / 60, tier = touAt(h).tier;
    return [1, w.tout, w.irr / 1000, occAt('office', T), occAt('lab', T), occAt('dorm', T), tier === 'peak' ? 1 : 0, tier === 'mid' ? 1 : 0,
      Math.sin(2 * Math.PI * h / 24), Math.cos(2 * Math.PI * h / 24), F.y[a - 96]];
  }
  const base = (x) => (F.wB && Number.isFinite(x[10]) ? fcDot(F.wB, x) : F.wA ? fcDot(F.wA, x) : null);
  function fit() {
    const R = F.rows.slice(-288);
    F.wA = R.length >= 8 ? fcRidge(R.map((r) => ({ x: r.x.slice(0, 10), y: r.y })), 2) : null;
    const R1 = R.filter((r) => Number.isFinite(r.x[10]));
    F.wB = R1.length >= 48 ? fcRidge(R1, 2) : null;
    F.res = {}; const E = [];                               // base-model residuals of the last 2 days, autocorrelation by lag
    for (const r of F.rows.slice(-192)) { const p = base(r.x); if (p != null) { F.res[r.a] = r.y - p; E.push(r.a); } }
    for (let h = 1; h <= 100; h++) {
      let sxy = 0, sxx = 0;
      for (const a of E) { const u = F.res[a - h]; if (u != null) { sxy += F.res[a] * u; sxx += u * u; } }
      F.acf[h] = sxx > 0 ? clamp(sxy / sxx, 0, 0.99) : 0;
    }
  }
  function predict(a, n) {
    const w = wxHat(a, n); if (!w) return null;
    let p = base(feat(a, w)); if (p == null) return null;
    const e = F.res[n - 1]; if (e != null) p += (F.acf[a - n + 1] || 0) * e;
    return Math.max(0, p);
  }
  function close(c) {
    const y = c.sum / c.n, wx = { tout: c.tout / c.n, irr: c.irr / c.n };
    F.y[c.abs] = y; F.wx[c.abs] = wx;
    const cs = csAt(c.abs); if (cs > 50) F.k = clamp(wx.irr / cs, 0, 1.2);
    F.rows.push({ a: c.abs, x: feat(c.abs, wx), y }); if (F.rows.length > 700) F.rows.splice(0, F.rows.length - 700);
    const p = F.preds[c.abs];                               // score the 1-h-ahead prediction made for this slot
    if (p != null) {
      F.err.push(p - y); if (F.err.length > 64) F.err.shift();
      F.scored.push({ abs: c.abs, y, p }); if (F.scored.length > 500) F.scored.splice(0, F.scored.length - 500);
      delete F.preds[c.abs];
    }
    for (const k in F.y) if (+k < c.abs - 4 * 96) { delete F.y[k]; delete F.wx[k]; }
  }
  function issue(n, T) {                                    // rest-of-day forecast + the scored 1-h-ahead prediction
    const day0 = Math.floor(T / 1440) * 96, fut = new Array(96).fill(null);
    for (let a = n + 1; a < day0 + 96; a++) fut[a - day0] = predict(a, n);
    const a1 = n + 4, p1 = a1 < day0 + 96 ? fut[a1 - day0] : predict(a1, n);
    if (p1 != null) F.preds[a1] = p1;
    const errs = F.err.map(Math.abs).sort((x, y) => x - y);
    F.band = errs.length >= 6 ? errs[Math.floor(0.9 * (errs.length - 1))] : null;
    F.out = { n, fut, day0, band: F.band };
  }
  F.record = (s) => {
    const abs = Math.floor(s.T / 15);
    if (F.cur && F.cur.abs !== abs) {
      if (s.T - F.cur.t1 <= 15) close(F.cur);               // a slot cut short by a jump (the boot fast-forward) is dropped
      fit(); issue(abs, s.T);
    }
    if (!F.cur || F.cur.abs !== abs) F.cur = { abs, sum: 0, n: 0, tout: 0, irr: 0, t1: s.T };
    const c = F.cur; c.sum += valueOf(s); c.n++; c.tout += s.env.tout; c.irr += s.env.irr; c.t1 = s.T;
  };
  return F;
}
const FC = fcMake((s) => s.grid);
const FCN = COORD_V2 ? fcMake((s) => s.load - s.pv) : null;  // net load before the battery, for the v2 coordinator
if (FCN) NET_FC = () => FCN.out;
function fcRecord(s) { FC.record(s); if (FCN) FCN.record(s); }
function fcAccuracy() {
  const S = FC.scored.slice(-96); if (S.length < 8) return null;
  const n = S.length, mean = S.reduce((a, s) => a + s.y, 0) / n;
  const rmse = Math.sqrt(S.reduce((a, s) => a + (s.p - s.y) ** 2, 0) / n), bias = S.reduce((a, s) => a + (s.p - s.y), 0) / n;
  const mape = S.reduce((a, s) => a + Math.abs(s.p - s.y) / Math.max(1, s.y), 0) / n * 100;
  return { n, cvrmse: rmse / Math.max(1, mean) * 100, nmbe: bias / Math.max(1, mean) * 100, mape, rmse };
}
function fcSummary() {
  const s = lastSnap; if (!s || !FC.out) return null;
  const nowSlot = Math.floor(s.clock / 15), f = FC.out.fut;
  let mx = -1, at = -1; for (let i = nowSlot + 1; i < Math.min(96, nowSlot + 17); i++) if (f[i] != null && f[i] > mx) { mx = f[i]; at = i; }
  const acc = fcAccuracy();
  return { method: 'regression on forecast weather, occupancy timetable and yesterday (no future data)', next4hMaxKW: mx >= 0 ? Math.round(mx) : null, next4hMaxAt: at >= 0 ? fcHM(at) : null,
    next4hMaxPctOfLimit: mx >= 0 ? Math.round(mx / s.peakLimit * 100) : null, band90KW: FC.band != null ? Math.round(FC.band) : null,
    accuracy1hAhead: acc ? { cvrmsePct: +acc.cvrmse.toFixed(1), nmbePct: +acc.nmbe.toFixed(1), mapePct: +acc.mape.toFixed(1), samples: acc.n } : null };
}
// chart overlay: wrap the 24-h chart renderer (its scale is recomputed here exactly as in renderChart)
{
  const _rc = renderChart;
  renderChart = function (s) {
    _rc(s);
    if (!s || !FC.out) return;
    const cv = $('loadChart'), w = cv.clientWidth, h = cv.clientHeight; if (!w) return;
    const g = cv.getContext('2d'), grid = s.hist('grid'), pv = s.hist('pv'), ess = s.hist('ess'), base = s.histBase('grid'), L = s.peakLimit;
    const top = Math.max(L * 1.3, ...grid.map((v, i) => (v || 0) + (pv[i] || 0) + (ess[i] || 0)).filter(Number.isFinite), ...base.filter(Number.isFinite)) * 1.04;
    const PL = 30, ch = h - 16 - 4, cw = w - PL - 2, X = (i) => PL + i / 96 * cw, Y = (v) => 4 + ch - Math.min(v, top) / top * ch, f = FC.out.fut, b = FC.out.band;
    if (b) { g.fillStyle = 'rgba(59,130,246,.13)'; g.beginPath(); let st = false; const up = [], dn = [];
      f.forEach((v, i) => { if (v != null) { up.push([X(i + 0.5), Y(v + b)]); dn.push([X(i + 0.5), Y(Math.max(0, v - b))]); } });
      if (up.length > 1) { up.forEach(([x, y], k) => (k ? g.lineTo(x, y) : g.moveTo(x, y))); dn.reverse().forEach(([x, y]) => g.lineTo(x, y)); g.closePath(); g.fill(); st = true; } }
    g.strokeStyle = '#3B82F6'; g.lineWidth = 1.6; g.setLineDash([3, 3]); g.beginPath(); let on = false;
    f.forEach((v, i) => { if (v == null) { on = false; return; } const x = X(i + 0.5), y = Y(v); on ? g.lineTo(x, y) : g.moveTo(x, y); on = true; });
    g.stroke(); g.setLineDash([]);
  };
  const lg = document.querySelector('#chartCard .legend');
  if (lg) { const sp = document.createElement('span'); sp.innerHTML = `<i class="dash" style="border-color:#3B82F6"></i><span data-i18n="fc.legend">${uiEsc(t('fc.legend'))}</span>`; lg.appendChild(sp); }
}

// ---------- sensor layer + FDD ----------
const FDD_Q = new URLSearchParams(location.search);
const FDD_ON = FDD_Q.get('fdd') !== 'off';                  // ?fdd=off: the sensor layer runs, nothing is ever flagged
// ?fddNoise=σ: Gaussian sensor noise with standard deviation σ °C (Box–Muller on a deterministic hash, so runs repeat);
// default: the original uniform ±0.04 °C (σ ≈ 0.023 °C). With ?seed the hash is re-seeded too.
const FDD_SIGMA = (() => { const v = parseFloat(FDD_Q.get('fddNoise')); return Number.isFinite(v) && v >= 0 ? v : null; })();
const fddHash = (i, k, j) => { const x = Math.sin(i * 127.1 + k * 311.7 + j * 74.7 + (SEED === null ? 0 : (SEED % 9973) * 0.6180339)) * 43758.5453; return x - Math.floor(x); };
const fddNoise = FDD_SIGMA === null && SEED === null
  ? (i, k) => { let x = Math.sin(i * 127.1 + k * 311.7) * 43758.5453; return (x - Math.floor(x) - 0.5) * 0.08; }
  : FDD_SIGMA === null ? (i, k) => (fddHash(i, k, 1) - 0.5) * 0.08
    : (i, k) => FDD_SIGMA * Math.sqrt(-2 * Math.log(Math.max(1e-12, fddHash(i, k, 1)))) * Math.cos(2 * Math.PI * fddHash(i, k, 2));
function fddMeasure(R, i, k, T) {
  const f = FDD.faults[R.id];
  if (f && !f.repaired) {
    if (f.type === 'stuck') return f.v0;
    if (f.type === 'dropout') return NaN;
    if (f.type === 'drift') return R.T + (f.rate || 0.05) * (T - f.t0) + fddNoise(i, k);   // °C per minute (default 3 °C/h)
  }
  return R.T + fddNoise(i, k);
}
// drift threshold (°C between the reading and the virtual sensor); ?fdddrift= overrides it for the evaluation runs
const FDD_DRIFT_C = +(new URLSearchParams(location.search).get('fdddrift') || 1.6);
function fddSample(s) {
  const k = Math.floor(s.T / 5); if (k === FDD.k) return; FDD.k = k;
  const rooms = s.rooms || [], byZone = {};
  rooms.forEach((R, i) => {
    const st = FDD.rooms[R.id] || (FDD.rooms[R.id] = { buf: [], off: 0, miss: 0, dev: 0, cool: 0 });
    const spMoved = st.sp != null && Math.abs(R.sp - st.sp) > 0.3;   // setpoint step (morning start, pre-cool, relax): the room lags it
    const m = fddMeasure(R, i, k, s.T); st.last = m; st.sp = R.sp;
    st.buf.push(m); if (st.buf.length > 12) st.buf.shift();
    st.miss = Number.isFinite(m) ? 0 : st.miss + 1;
    st.cool = R.hvacMode === 'cooling' && !spMoved ? st.cool + 1 : 0;   // 5-min samples since conditioning (re)started at a steady setpoint
    (byZone[R.id.replace(/-R\d+$/, '')] ||= []).push(R);
  });
  // Drift is judged only while a room is being conditioned and has settled (30 min): then its temperature should
  // track the setpoint like its conditioned neighbours do. Floating (setback / off) rooms and start-up transients
  // follow occupancy and sun rather than the setpoint, and comparing them was the main source of false alarms.
  for (const zid in byZone) {
    const list = byZone[zid];
    for (const R of list) {
      const st = FDD.rooms[R.id];
      const nb = list.filter((q) => q !== R && FDD.rooms[q.id].cool >= 6 && Number.isFinite(FDD.rooms[q.id].last) && !FDD.alarms[q.id])
        .map((q) => FDD.rooms[q.id].last - q.sp).sort((a, b) => a - b), n = nb.length;
      const e = n ? (n % 2 ? nb[(n - 1) / 2] : (nb[n / 2 - 1] + nb[n / 2]) / 2) : 0;   // median tracking error of settled, conditioned neighbours
      st.offA ??= 0; st.ring ??= [];
      st.virt = R.sp + e + st.off;
      const settled = st.cool >= 6 && Number.isFinite(st.last);
      // two residuals: against the neighbours (rP) and against the room's own normal setpoint tracking (rA). A bad
      // sensor departs from both; a healthy room next to a bad sensor departs only from rP, and a plant that cannot
      // hold every room (hot afternoon) moves rA but not rP. Flag only when both agree.
      const rP = settled ? st.last - st.virt : 0, rA = settled ? st.last - (R.sp + st.offA) : 0;
      // commissioning: the first 3 h of conditioned operation only learn (fast) and never alarm. Without it, rooms
      // whose normal bias exceeds the threshold (e.g. a top-floor office running 1.8 °C cool) alarmed in the first hours.
      const learning = (st.seen || 0) < 36;
      if (settled && !FDD.alarms[R.id]) {                   // learn the normal biases; nearly frozen while a residual grows
        st.seen = (st.seen || 0) + 1;
        st.off += (learning ? 0.1 : Math.abs(rP) < 0.8 ? 0.05 : 0.01) * ((st.last - (R.sp + e)) - st.off);
        st.offA += (learning ? 0.1 : Math.abs(rA) < 0.8 ? 0.05 : 0.01) * ((st.last - R.sp) - st.offA);
        st.ring.push([st.off, st.offA]); if (st.ring.length > 96) st.ring.shift();   // 8 h of learned biases, for rollback after a repair
      }
      // needs at least one conditioned neighbour as a reference: a room cooled alone at night (one occupant) sits well
      // below its cooling setpoint because a cooling-only system cannot warm it, and without peers that looks like drift
      st.dev = settled && !learning && n >= 1 && Math.abs(rP) > FDD_DRIFT_C && Math.abs(rA) > FDD_DRIFT_C && rP * rA > 0 ? st.dev + 1 : 0;
      if (FDD.alarms[R.id] || (st.mute && s.T < st.mute)) continue;
      const b = st.buf.filter(Number.isFinite);
      let type = null;
      if (st.miss >= 3) type = 'dropout';
      else if (st.buf.length >= 9 && b.length >= 9 && Math.max(...b.slice(-9)) - Math.min(...b.slice(-9)) < 0.005) type = 'stuck';
      else if (st.dev >= 3) type = 'drift';
      if (type && FDD_ON) fddRaise(R, type, s);
    }
  }
  for (const id in FDD.faults) {
    const f = FDD.faults[id];
    if (f.repairAt && s.T >= f.repairAt) {
      f.repaired = true; delete FDD.faults[id]; delete FDD.alarms[id];
      const st = FDD.rooms[id];                              // repaired sensor: roll the learned biases back to before the fault
      if (st) { if (st.pre) [st.off, st.offA] = st.pre; Object.assign(st, { dev: 0, buf: [], pre: null, mute: s.T + 30 }); }
      renderSide(true);
    }
  }
}
function fddRaise(R, type, s) {
  const f = FDD.faults[R.id], st = FDD.rooms[R.id];
  const real = !!(f && !f.repaired), delay = real ? Math.round(s.T - f.t0) : null;
  if (st && st.ring && st.ring.length) st.pre = st.ring[0].slice();   // biases from up to 8 h before the alarm
  FDD.alarms[R.id] = { id: 'fdd:' + R.id, room: R.id, type, at: s.T, delay, real, meas: st.last, virt: st.virt, state: 'pending' };
  if (real) { FDD.stats.detected++; FDD.stats.delays.push(delay); const bt = FDD.stats.byType[f.type] || (FDD.stats.byType[f.type] = { injected: 0, detected: 0, delays: [] }); bt.detected++; bt.delays.push(delay); f.detected = true; }
  else FDD.stats.falseAlarms++;
  FDD.log.push({ T: s.T, room: R.id, type, real, delay });
  renderSide(true);
}
function fddInject(roomId, type, opt) {
  const s = lastSnap, R = s && (s.rooms || []).find((q) => q.id === roomId); if (!R || FDD.faults[roomId]) return false;
  const st = FDD.rooms[roomId];
  FDD.faults[roomId] = { type, t0: s.T, v0: st && Number.isFinite(st.last) ? st.last : R.T, repaired: false, rate: opt && +opt.rate > 0 ? +opt.rate : 0 };
  if (FAULT_IMPACT) FDD.bfaults[roomId] = { type, t0: s.T, rate: FDD.faults[roomId].rate, v0: null };   // the same sensor in the BMS world
  FDD.stats.injected++; (FDD.stats.byType[type] || (FDD.stats.byType[type] = { injected: 0, detected: 0, delays: [] })).injected++;
  return true;
}
function fddDecide(roomId, ok) {
  const a = FDD.alarms[roomId], s = lastSnap; if (!a || !s) return;
  if (ok) { a.state = 'virtual'; const f = FDD.faults[roomId]; if (f) f.repairAt = s.T + 30; else { delete FDD.alarms[roomId]; } toast(t('fdd.ok', { room: fddName(roomId) }), 'var(--teal)'); }
  else { delete FDD.alarms[roomId]; if (FDD.rooms[roomId]) FDD.rooms[roomId].mute = s.T + 120; if (FDD.faults[roomId]) delete FDD.faults[roomId]; toast(t('fdd.no', { room: fddName(roomId) }), 'var(--amber)'); }
  renderSide(true);
}
// card subtitle: the delay is only known for drill faults (ground truth); otherwise show when it was flagged
function fddSub(a) {
  const m = Number.isFinite(a.meas) ? a.meas.toFixed(1) + ' °C' : '—', v = (a.virt || 0).toFixed(1) + ' °C';
  return a.delay != null ? t('fdd.sub', { m, v, d: a.delay }) : t('fdd.sub2', { m, v, t: `${String(Math.floor((a.at % 1440) / 60)).padStart(2, '0')}:${String(a.at % 60).padStart(2, '0')}` });
}
function fddName(id) { const r = typeof INT_ROOM !== 'undefined' && INT_ROOM[id]; return r ? `${LANG === 'ko' ? r.nameKo || r.name : r.name} (${id})` : id; }
function fddStatsView() {
  const S = FDD.stats, d = S.delays.slice().sort((a, b) => a - b), med = d.length ? d[Math.floor((d.length - 1) / 2)] : null;
  return { injected: S.injected, detected: S.detected, falseAlarms: S.falseAlarms, recall: S.injected ? S.detected / S.injected : null,
    precision: S.detected + S.falseAlarms ? S.detected / (S.detected + S.falseAlarms) : null, medianDelayMin: med, byType: S.byType };
}
function fddSummary() {
  const open = Object.values(FDD.alarms).map((a) => ({ room: a.room, type: a.type, state: a.state, measuredC: Number.isFinite(a.meas) ? +a.meas.toFixed(1) : null, virtualC: +(a.virt || 0).toFixed(1), detectedAfterMin: a.delay }));
  const v = fddStatsView();
  return { openAlarms: open, drillStats: { injected: v.injected, detected: v.detected, falseAlarms: v.falseAlarms, medianDelayMin: v.medianDelayMin } };
}
// alerts list + toast: FDD alarms first
{
  const _ra = renderAlerts;
  renderAlerts = function (s) {
    if (!s) return _ra(s);
    const extra = Object.values(FDD.alarms).filter((a) => a.state === 'pending').map((a) => ({ id: a.id, level: 'warn', text: t('fdd.alert', { room: fddName(a.room), what: t('fdd.' + a.type) }),
      sub: fddSub(a), target: { kind: 'room', id: a.room } }));
    return _ra(extra.length ? Object.assign(Object.create(s), { alerts: extra.concat(s.alerts || []) }) : s);
  };
}
// side panel: approval cards on top, drill buttons on a selected room
{
  const body = document.getElementById('sideBody');
  if (body) { const box = document.createElement('div'); box.id = 'fddCards'; body.insertBefore(box, body.firstChild); }
  const _rs = renderSide;
  renderSide = function (full) {
    _rs(full);
    const box = document.getElementById('fddCards'); if (!box) return;
    const pend = Object.values(FDD.alarms);
    box.innerHTML = pend.length ? `<div class="fdd-h">${uiEsc(t('fdd.title'))}</div>` + pend.map((a) => `<div class="fdd-card ${a.state}"><b>${uiEsc(fddName(a.room))}</b><span>${uiEsc(t('fdd.' + a.type))}</span>
      <small>${uiEsc(fddSub(a))}</small>
      <small class="fdd-act">→ ${uiEsc(t('fdd.act.' + a.type))}</small>
      ${a.state === 'pending' ? `<div class="fdd-btns"><button class="btn on" data-ok="${uiEsc(a.room)}">${uiEsc(t('fdd.approve'))}</button><button class="btn" data-no="${uiEsc(a.room)}">${uiEsc(t('fdd.dismiss'))}</button></div>` : `<small class="ai-ok">✓ ${uiEsc(t('fdd.state.virtual'))}</small>`}</div>`).join('') : '';
    if (full && selection.kind === 'room') {
      const ex = document.getElementById('sideExtra'), st = FDD.rooms[selection.id], a = FDD.alarms[selection.id];
      if (ex && !ex.querySelector('.fdd-drill')) ex.insertAdjacentHTML('beforeend', `<div class="fdd-drill"><div class="sec"><b>${uiEsc(t('fdd.inject'))}</b><span>${uiEsc(t(a ? (a.state === 'virtual' ? 'fdd.state.virtual' : 'fdd.state.flag') : 'fdd.state.ok'))}${st && Number.isFinite(st.last) ? ` · ${st.last.toFixed(1)} °C` : ''}</span></div>
        <div class="fdd-btns">${['stuck', 'drift', 'dropout'].map((k) => `<button class="btn" data-inj="${k}">${uiEsc(t('fdd.inj.' + k))}</button>`).join('')}</div></div>`);
    }
  };
  document.getElementById('side').addEventListener('click', (e) => {
    const ok = e.target.closest('[data-ok]'), no = e.target.closest('[data-no]'), inj = e.target.closest('[data-inj]');
    if (ok) fddDecide(ok.dataset.ok, true);
    else if (no) fddDecide(no.dataset.no, false);
    else if (inj && selection.kind === 'room') { if (fddInject(selection.id, inj.dataset.inj)) toast(t('fdd.injected', { room: fddName(selection.id), what: t('fdd.inj.' + inj.dataset.inj) }), 'var(--violet)'); }
  });
}
// ?faultImpact=1: the VAV loop of a room acts on its sensor. A faulty sensor (stuck at v0, drifting, or dropped out with
// the last reading held) misleads the loop until FDD flags the room; from then on the loop runs on the virtual sensor
// (also after a false alarm). The rule-based BMS has no FDD: its loop keeps the faulty reading and nobody repairs it.
// The loop sees the sensor's error added to the air temperature (the reading tracks the operative temperature R.T).
function fddSensed(f, v0, S, R, T) {
  if (f.type === 'drift') return S.Ta + (f.rate || 0.05) * (T - f.t0);
  return S.Ta + (v0 - R.T);                                  // stuck / dropout: a frozen reading
}
if (FAULT_IMPACT) roomSense = (m, i, S, R, T) => {
  const id = R.id;
  if (m.kind === 'agent') {
    if (FDD.alarms[id]) { const st = FDD.rooms[id]; return st && Number.isFinite(st.virt) ? S.Ta + (st.virt - R.T) : S.Ta; }
    const f = FDD.faults[id];
    return f && !f.repaired ? fddSensed(f, f.v0, S, R, T) : S.Ta;
  }
  const f = FDD.bfaults[id]; if (!f) return S.Ta;
  if (f.v0 === null) f.v0 = R.T;                             // what the BMS world's sensor read when it failed
  return fddSensed(f, f.v0, S, R, T);
};
Bus.on('tick', (s) => { try { fcRecord(s); fddSample(s); } catch (e) { console.warn('[fc/fdd]', e); } });
// chart header: forecast max / peak risk for the next 4 h
onFrame(() => {
  const s = lastSnap; if (!s || !FC.out) return;
  FC.acc = (FC.acc || 0) + 1; if (FC.acc % 30) return;
  const sm = fcSummary(); if (!sm || sm.next4hMaxKW == null) return;
  const el = $('chartNow'); if (!el) return;
  const risk = sm.next4hMaxPctOfLimit >= 92, txt = t(risk ? 'fc.risk' : 'fc.chip', { kw: fmt(sm.next4hMaxKW), t: sm.next4hMaxAt, p: sm.next4hMaxPctOfLimit });
  el.title = txt; el.dataset.fc = txt;
  let chip = document.getElementById('fcChip');
  if (!chip) { chip = document.createElement('span'); chip.id = 'fcChip'; el.parentNode.insertBefore(chip, el); }
  chip.textContent = txt; chip.className = risk ? 'risk' : '';
});
// test / demo hooks, attached once window.MA_BEMS exists (it is created at the end of the module)
setTimeout(() => { if (window.MA_BEMS) Object.assign(window.MA_BEMS, {
  fdd: { inject: fddInject, stats: fddStatsView, alarms: () => FDD.alarms, decide: fddDecide, log: () => FDD.log.slice() },
  forecast: { summary: fcSummary, accuracy: fcAccuracy, scored: () => FC.scored.map((s) => ({ ...s })), actuals: () => ({ ...FC.y }),
    net: FCN ? { scored: () => FCN.scored.map((s) => ({ ...s })), actuals: () => ({ ...FCN.y }) } : null },
  ablation: [...ABLATE], baselineTuned: BASE_TUNED,
  options: { seed: SEED, drOff: DR_OFF, baselineSensor: BASE_SENSOR, coordV2: COORD_V2, drNotice: DR_NOTICE, faultImpact: FAULT_IMPACT, fdd: FDD_ON, fddNoise: FDD_SIGMA } }); }, 0);
