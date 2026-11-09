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
{
  const anchor = document.getElementById('dtTemplate');
  if (anchor) {
    const wrap = document.createElement('span'); wrap.className = 'kp-row';
    wrap.innerHTML = `<button id="kpBtn" class="btn" type="button"></button><select id="kpSeason" class="dt-in"><option value="summer"></option><option value="spring_fall"></option></select><button id="kpReal" class="btn" type="button"></button>`;
    anchor.parentNode.insertBefore(wrap, anchor.nextSibling);
    const texts = () => {
      document.getElementById('kpBtn').textContent = t('kp.btn'); document.getElementById('kpBtn').title = t('kp.btn.title');
      document.getElementById('kpReal').textContent = t('kp.real'); document.getElementById('kpReal').title = t('kp.real.title');
      const sel = document.getElementById('kpSeason'); sel.options[0].textContent = t('kp.summer'); sel.options[1].textContent = t('kp.spring_fall');
    };
    texts(); onLang(texts);
    document.getElementById('kpBtn').onclick = () => dtSetTable(kepcoTable(document.getElementById('kpSeason').value));
    document.getElementById('kpReal').onclick = kepcoRealSample;
  }
}
