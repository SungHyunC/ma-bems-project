"""Insert / replace marked blocks in MA-BEMS index.html (idempotent), then syntax-check the module.

    python -I inject.py            # writes index.html in place (backup kept in scratchpad/backup)

Each block: (name, kind, anchor, file). kind 'html' blocks go right before the anchor line, 'js' blocks
right after it. Re-running replaces the block between its BEGIN / END markers.
"""
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX = HERE.parent / 'index.html'
BLOCKS = [
    ('AI-UI', 'html', '<script type="module">\n', HERE / 'ai_ui.html'),
    ('AI', 'js', '\nlyApply(false);\n', HERE / 'ai_module.js'),
    ('TARIFF', 'js', '/* MA-AI:END */\n', HERE / 'tariff_module.js'),
    ('FDD', 'js', '/* MA-TARIFF:END */\n', HERE / 'fdd_module.js'),
    ('PROOF', 'js', '/* MA-FDD:END */\n', HERE / 'proof_module.js'),
    ('SCN', 'js', '/* MA-PROOF:END */\n', HERE / 'scn_module.js'),
]


# surgical edits of the original sources: (old, new); skipped once applied
REPLACE = [
    ("""function touAt(h) {
  h = ((h % 24) + 24) % 24;
  if (h >= 13 && h < 19) return TOU.peak;
  if ((h >= 8 && h < 13) || (h >= 19 && h < 22)) return TOU.mid;
  return TOU.off;
}
const minsToPeak = (h) => h < 13 ? (13 - h) * 60 : h >= 19 ? (37 - h) * 60 : 0;""",
     """// load-period hours (the KEPCO preset in section 7f swaps them); PK = the daily peak window
const TOU_HOURS = { peak: [[13, 19]], mid: [[8, 13], [19, 22]] };
const PK = { get s() { return TOU_HOURS.peak[0][0]; }, get e() { return TOU_HOURS.peak[0][1]; } };
function touAt(h) {
  h = ((h % 24) + 24) % 24;
  const inR = (rs) => rs.some(([a, b]) => h >= a && h < b);
  if (inR(TOU_HOURS.peak)) return TOU.peak;
  if (inR(TOU_HOURS.mid)) return TOU.mid;
  return TOU.off;
}
const minsToPeak = (h) => h < PK.s ? (PK.s - h) * 60 : h >= PK.e ? (24 + PK.s - h) * 60 : 0;"""),
    ("Math.max(0, soc - 0.3) * cap / Math.max(0.5, 19 - h)", "Math.max(0, soc - 0.3) * cap / Math.max(0.5, PK.e - h)"),
    ("""      } else if (h < 13) {
        if (soc < 0.9) { target = -Math.min(120, (0.92 - soc) * cap / Math.max(0.5, 13 - h)""",
     """      } else if (h < PK.s) {
        if (soc < 0.9) { target = -Math.min(120, (0.92 - soc) * cap / Math.max(0.5, PK.s - h)"""),
    ("      } else if (h >= 19 && soc > 0.22) {", "      } else if (h >= PK.e && soc > 0.22) {"),
    ("else if (env.h >= 19 && env.h < 20.5 && d.type !== 'dc') off = out.recover = Math.round((20.5 - env.h) / 1.5 * 10) / 10;",
     "else if (env.h >= PK.e && env.h < PK.e + 1.5 && d.type !== 'dc') off = out.recover = Math.round((PK.e + 1.5 - env.h) / 1.5 * 10) / 10;"),
    ("const PK = { get s() { return TOU_HOURS.peak[0][0]; }, get e() { return TOU_HOURS.peak[0][1]; } };",
     """const PK = { get s() { return TOU_HOURS.peak[0][0]; }, get e() { return TOU_HOURS.peak[0][1]; } };
// ablation switches for the evaluation (?ablate=COORD,ESS,EV,ROOM,HVAC,LIGHT): the agent model runs with those
// controllers replaced by the rule-based BMS's (COORD = agents act on their own plans, no negotiation)
const ABLATE = new Set((new URLSearchParams(location.search).get('ablate') || '').toUpperCase().split(',').filter(Boolean));"""),
    ("const ABLATE = new Set((new URLSearchParams(location.search).get('ablate') || '').toUpperCase().split(',').filter(Boolean));\n",
     """const ABLATE = new Set((new URLSearchParams(location.search).get('ablate') || '').toUpperCase().split(',').filter(Boolean));
{ const q = +new URLSearchParams(location.search).get('limit'); if (q >= 300 && q <= 3000) TOPO.peakLimit = q; }   // ?limit= stress test (kW)
"""),
    ('<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
     '<meta name="viewport" content="width=device-width, initial-scale=1">'),   # no safe-area padding: the iOS app would draw under its bar
    ("  addEventListener('error', (e) => show((ko ? '오류: ' : 'Error: ') + (e.message || e.type) + (e.filename ? ' (' + e.filename.split('/').pop() + ':' + e.lineno + ')' : '')));",
     "  addEventListener('error', (e) => { if (/ResizeObserver loop/.test(e.message || '')) return;   // benign layout notice, not an error\n    show((ko ? '오류: ' : 'Error: ') + (e.message || e.type) + (e.filename ? ' (' + e.filename.split('/').pop() + ':' + e.lineno + ')' : '')); });"),
    # ---- scenarios (?scn=...): one definition, then hooks in the weather, occupancy, EV and DR code ----
    ("{ const q = +new URLSearchParams(location.search).get('limit'); if (q >= 300 && q <= 3000) TOPO.peakLimit = q; }   // ?limit= stress test (kW)\n",
     """{ const q = +new URLSearchParams(location.search).get('limit'); if (q >= 300 && q <= 3000) TOPO.peakLimit = q; }   // ?limit= stress test (kW)
// scenarios: ?scn=heatwave|cloudy|dr|tight|evrush|holiday|fault|worst, or ?scn=custom with dT (°C), sun (0–1.2), occ (0–1.5),
// limit (kW), drAt (HH:MM), drShed (kW), drMin (min), ev (extra evening EVs), fault (stuck|drift|dropout). The same campus
// under other conditions; both controllers still get identical inputs, so each comparison stays like-for-like.
const SCN = (() => {
  const q = new URLSearchParams(location.search), id = (q.get('scn') || '').toLowerCase();
  const PRESET = {
    heatwave: { dT: 5 }, cloudy: { sun: 0.25 }, dr: { drAt: 960, drShed: 300, drMin: 60 }, tight: { limit: 850 },
    evrush: { ev: 6 }, holiday: { occ: 0.25 }, fault: { fault: 'stuck' },
    worst: { dT: 4, sun: 0.5, limit: 900, drAt: 960, drShed: 250, drMin: 60, ev: 4 },
  };
  const s = { id: '', dT: 0, sun: 1, occ: 1, ev: 0, limit: 0, drAt: -1, drShed: 0, drMin: 30, fault: '' };
  if (PRESET[id]) Object.assign(s, PRESET[id], { id });
  else if (id === 'custom') {
    const n = (k, lo, hi) => { const v = parseFloat(q.get(k)); return Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : null; };
    const set = (k, v) => { if (v !== null) s[k] = v; };
    s.id = 'custom';
    set('dT', n('dT', -8, 10)); set('sun', n('sun', 0, 1.2)); set('occ', n('occ', 0, 1.5)); set('limit', n('limit', 300, 3000));
    set('drShed', n('drShed', 50, 500)); set('drMin', n('drMin', 15, 120));
    const ev = n('ev', 0, 12); if (ev !== null) s.ev = Math.round(ev);
    const at = /^(\\d{1,2}):(\\d{2})$/.exec(q.get('drAt') || ''); if (at) s.drAt = Math.min(1439, +at[1] * 60 + +at[2]);
    if (['stuck', 'drift', 'dropout'].includes(q.get('fault'))) s.fault = q.get('fault');
  }
  if (s.limit) TOPO.peakLimit = s.limit;
  return s;
})();
"""),
    ("  if (c.wind) wind = Math.max(0, dsVal(c.wind, T));\n",
     """  if (c.wind) wind = Math.max(0, dsVal(c.wind, T));
  if (SCN.dT) tout += SCN.dT * (0.55 + 0.45 * Math.max(0, Math.cos(2 * Math.PI * (h - 15) / 24)));   // scenario: hotter, most of it in the afternoon
  if (SCN.sun !== 1) { irr *= SCN.sun; cloud = Math.min(1, cloud * SCN.sun); }                        // scenario: cloud cover
"""),
    ("  return c ? dsVal(c, T) : occupancy(type, ((((T % 1440) + 1440) % 1440) / 60));\n",
     """  const v = c ? dsVal(c, T) : occupancy(type, ((((T % 1440) + 1440) % 1440) / 60));
  return SCN.occ === 1 || type === 'dorm' ? v : Math.min(1, v * SCN.occ);   // scenario: holiday or crowded day (offices and labs)
"""),
    ("  for (let i = 0; i < 5; i++) add(1040 + r() * 210, 600 + r() * 120, 18 + r() * 24, 'ac');\n",
     """  for (let i = 0; i < 5; i++) add(1040 + r() * 210, 600 + r() * 120, 18 + r() * 24, 'ac');
  for (let i = 0; i < SCN.ev; i++) add(960 + r() * 120, 600 + r() * 120, 20 + r() * 25, 'ac');   // scenario: evening EV rush (arrivals 16–18 h)
"""),
    ("    Object.assign(dr, { active: true, start: T, end: T + 30, shed: 160 + Math.floor(rr() * 7) * 10, src, sumA: 0, sumB: 0, n: 0 });",
     "    const shed0 = 160 + Math.floor(rr() * 7) * 10;     // drawn even when a scenario fixes the shed, so later random draws stay the same\n"
     "    Object.assign(dr, { active: true, start: T, end: T + (SCN.drMin || 30), shed: SCN.drShed || shed0, src, sumA: 0, sumB: 0, n: 0 });"),
    ("    ctx.log('COORD', () => L(`DR event from ${drSource()}: shed ${shed} kW for 30 min (cap ${cap} kW, price ${pr}/kWh)`, `DR 이벤트 발령 (${drSource()}): 30분간 ${shed} kW 감축 (상한 ${cap} kW · 요금 ${pr}/kWh)`), 'dr', ['COORD']);",
     "    const dur = dr.end - dr.start;\n"
     "    ctx.log('COORD', () => L(`DR event from ${drSource()}: shed ${shed} kW for ${dur} min (cap ${cap} kW, price ${pr}/kWh)`, `DR 이벤트 발령 (${drSource()}): ${dur}분간 ${shed} kW 감축 (상한 ${cap} kW · 요금 ${pr}/kWh)`), 'dr', ['COORD']);"),
    ("  const planDR = (day) => { drNext = day * 1440 + 14 * 60 + Math.floor(rr() * 200); };",
     "  const planDR = (day) => { const at = 14 * 60 + Math.floor(rr() * 200); drNext = day * 1440 + (SCN.drAt >= 0 ? SCN.drAt : at); };   // scenario: a fixed DR time"),
    ("Sim.start(clamp(+(QS.get('t') || 10), 0.5, 23.9) * 60);   // fast-forward so charts have history\n",
     """Sim.start(clamp(+(QS.get('t') || 10), 0.5, 23.9) * 60);   // fast-forward so charts have history
if (QS.get('speed') !== null) Sim.command({ type: 'speed', value: Math.max(0, +QS.get('speed') || 0) });   // ?speed=0 starts paused (reproducible evaluation runs)
"""),
    ("    stepBuildings(a, env, occ, agentRoomRules); stepEV(a, env, sessions, evAllocate); stepGrid(a, env, essInner(a));",
     "    stepBuildings(a, env, occ, ABLATE.has('ROOM') ? baselineRoomRules : agentRoomRules); stepEV(a, env, sessions, ABLATE.has('EV') ? null : evAllocate); stepGrid(a, env, ABLATE.has('ESS') ? baselineESS(a, env) : essInner(a));"),
    ("""    const P = {}; for (const id in A) P[id] = A[id].prop || plans[id]?.(m, env);
    const dr = ctx.dr, limit""",
     """    const P = {}; for (const id in A) P[id] = A[id].prop || plans[id]?.(m, env);
    if (ABLATE.has('COORD')) { decision = { ess: P.ESS.target, hvacScale: 1, dim: P.LIGHT.dim, evDefer: P.EV.defer }; return; }   // ablation: no negotiation
    const dr = ctx.dr, limit"""),
    ("      for (const id in m.bld) { m.bld[id].spOffset = P.off[id] < 0 ? P.off[id] * s : P.off[id]; m.bld[id].optStart = P.opt[id]; }",
     "      for (const id in m.bld) { const ab = ABLATE.has('HVAC'); m.bld[id].spOffset = ab ? 0 : P.off[id] < 0 ? P.off[id] * s : P.off[id]; m.bld[id].optStart = ab ? false : P.opt[id]; }"),
    ("      m.ctl.dim = dim;", "      m.ctl.dim = ABLATE.has('LIGHT') ? 1 : dim;"),
    ("""function baselineESS(m, env) {
  const h = env.h, soc = m.ess.soc;
  if (h < 5 && soc < 0.9) return -120;""",
     """// ?baseline=tuned gives the BMS the demand limiting a well-tuned system would have (battery peak shaving to 96 % of
// the limit): the "tuned rule-based" rung of the evaluation's baseline ladder
const BASE_TUNED = new URLSearchParams(location.search).get('baseline') === 'tuned';
function baselineESS(m, env) {
  const h = env.h, soc = m.ess.soc;
  if (BASE_TUNED && soc > 0.1) { const over = (m.bldLoad + m.evKW - m.pv) - TOPO.peakLimit * 0.96; if (over > 0) return Math.min(TOPO.ess.maxKW, over + 8); }
  if (h < 5 && soc < 0.9) return -120;"""),
]


def markers(name, kind):
    return ('<!-- MA-%s:BEGIN -->\n' % name, '<!-- MA-%s:END -->\n' % name) if kind == 'html' else ('/* MA-%s:BEGIN */\n' % name, '/* MA-%s:END */\n' % name)


def main():
    src = INDEX.read_text(encoding='utf-8')
    (HERE / 'backup').mkdir(exist_ok=True)
    shutil.copy(INDEX, HERE / 'backup' / ('index.%s.html' % time.strftime('%H%M%S')))
    for old, new in REPLACE:
        if new in src:
            continue
        if src.count(old) == 0 and new.splitlines()[0] in src:
            continue                                      # applied earlier (a later edit changed lines inside it)
        if src.count(old) != 1:
            sys.exit('replacement target found %d times: %s' % (src.count(old), old[:60]))
        src = src.replace(old, new)
    for name, kind, anchor, path in BLOCKS:
        if not path.exists():
            continue
        begin, end = markers(name, kind)
        body = begin + path.read_text(encoding='utf-8').rstrip('\n') + '\n' + end
        if begin in src:
            src = re.sub(re.escape(begin) + r'.*?' + re.escape(end), lambda m: body, src, count=1, flags=re.S)
            continue
        if src.count(anchor) != 1:
            sys.exit('anchor for %s found %d times' % (name, src.count(anchor)))
        i = src.index(anchor)
        src = src[:i] + body + src[i:] if kind == 'html' else src[:i + len(anchor)] + body + src[i + len(anchor):]
    INDEX.write_text(src, encoding='utf-8')
    m = re.search(r'^<script type="module">\n(.*?)^</script>', src, re.S | re.M)
    chk = HERE / 'module.check.mjs'
    chk.write_text(m.group(1), encoding='utf-8')
    r = subprocess.run(['node', '--check', str(chk)], capture_output=True, text=True)
    print('SYNTAX_OK' if r.returncode == 0 else r.stderr[-2000:], len(src))


if __name__ == '__main__':
    main()
