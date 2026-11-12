/* =====================================================================
   SECTION 7i — SCENARIOS  (insights tab "시나리오" + top-bar button)
   ---------------------------------------------------------------------
   Presets and a custom builder for the conditions the campus runs under. A scenario reloads the page
   with ?scn=… (parsed into SCN before the simulator starts) and restarts the day at 10:00; both
   controllers still get identical inputs. Each card says what changes, what the agents do about it
   (their actual rules), where to look, and what 9-day headless runs measured (SCN_RESULTS, written by
   scratchpad make_scn.mjs: 1 sim-minute steps, days 1–8 scored, same method as the evidence tab).
   ===================================================================== */
const SCN_RESULTS = /*SCN_RESULTS*/{"date":"2026-11-09","days":8,"runs":{"normal":{"n":8,"limit":1000,"costSave":{"mean":16.6998,"ci":0.247},"energySave":{"mean":9.3629,"ci":0.1232},"costA":2956,"costB":3548,"peakA":959,"peakB":1170,"overMinA":0,"overMinB":249.5,"overKWhA":0,"overKWhB":270.9,"comfortA":99.9,"comfortB":100,"drA":142,"drB":7,"evA":100,"evB":100,"pvA":100,"pvB":100,"vacA":944,"vacB":2002,"scenario":{"id":"","dT":0,"sun":1,"occ":1,"ev":0,"limit":0,"drAt":-1,"drShed":0,"drMin":30,"fault":""}},"heatwave":{"n":8,"limit":1000,"costSave":{"mean":13.692,"ci":0.9808},"energySave":{"mean":8.0732,"ci":0.1194},"costA":3658,"costB":4238,"peakA":1346,"peakB":1392,"overMinA":256.3,"overMinB":734,"overKWhA":548.1,"overKWhB":2339.1,"comfortA":99.7,"comfortB":99.3,"drA":44,"drB":8,"evA":100,"evB":100,"pvA":100,"pvB":100,"vacA":1473,"vacB":2583,"scenario":{"id":"heatwave","dT":5,"sun":1,"occ":1,"ev":0,"limit":0,"drAt":-1,"drShed":0,"drMin":30,"fault":""}},"cloudy":{"n":8,"limit":1000,"costSave":{"mean":13.6546,"ci":0.6368},"energySave":{"mean":7.4939,"ci":0.156},"costA":3382,"costB":3916,"peakA":1207,"peakB":1258,"overMinA":91,"overMinB":626.4,"overKWhA":121.6,"overKWhB":1414.9,"comfortA":99.9,"comfortB":100,"drA":75,"drB":9,"evA":100,"evB":100,"pvA":100,"pvB":100,"vacA":799,"vacB":1839,"scenario":{"id":"cloudy","dT":0,"sun":0.25,"occ":1,"ev":0,"limit":0,"drAt":-1,"drShed":0,"drMin":30,"fault":""}},"dr":{"n":8,"limit":1000,"costSave":{"mean":18.9922,"ci":0.1855},"energySave":{"mean":9.4146,"ci":0.1243},"costA":3106,"costB":3834,"peakA":968,"peakB":1170,"overMinA":0,"overMinB":249.5,"overKWhA":0,"overKWhB":270.9,"comfortA":99.4,"comfortB":100,"drA":91,"drB":2,"evA":100,"evB":100,"pvA":100,"pvB":100,"vacA":933,"vacB":2002,"scenario":{"id":"dr","dT":0,"sun":1,"occ":1,"ev":0,"limit":0,"drAt":960,"drShed":300,"drMin":60,"fault":""}},"tight":{"n":8,"limit":850,"costSave":{"mean":17.8621,"ci":0.2974},"energySave":{"mean":9.4071,"ci":0.2314},"costA":2914,"costB":3548,"peakA":1055,"peakB":1170,"overMinA":164.3,"overMinB":755.5,"overKWhA":209.4,"overKWhB":1666.2,"comfortA":99.9,"comfortB":100,"drA":102,"drB":7,"evA":100,"evB":100,"pvA":100,"pvB":100,"vacA":943,"vacB":2002,"scenario":{"id":"tight","dT":0,"sun":1,"occ":1,"ev":0,"limit":850,"drAt":-1,"drShed":0,"drMin":30,"fault":""}},"evrush":{"n":8,"limit":1000,"costSave":{"mean":17.331,"ci":0.2493},"energySave":{"mean":9.2241,"ci":0.1181},"costA":2976,"costB":3600,"peakA":960,"peakB":1267,"overMinA":0,"overMinB":281.6,"overKWhA":0,"overKWhB":426.9,"comfortA":99.9,"comfortB":100,"drA":141,"drB":7,"evA":97,"evB":97,"pvA":100,"pvB":100,"vacA":944,"vacB":2002,"scenario":{"id":"evrush","dT":0,"sun":1,"occ":1,"ev":6,"limit":0,"drAt":-1,"drShed":0,"drMin":30,"fault":""}},"holiday":{"n":8,"limit":1000,"costSave":{"mean":24.807,"ci":0.2765},"energySave":{"mean":16.4886,"ci":0.1266},"costA":2321,"costB":3087,"peakA":946,"peakB":1045,"overMinA":0,"overMinB":45.1,"overKWhA":0,"overKWhB":28.5,"comfortA":99.1,"comfortB":100,"drA":126,"drB":7,"evA":100,"evB":100,"pvA":100,"pvB":100,"vacA":1391,"vacB":2867,"scenario":{"id":"holiday","dT":0,"sun":1,"occ":0.25,"ev":0,"limit":0,"drAt":-1,"drShed":0,"drMin":30,"fault":""}},"fault":{"n":8,"limit":1000,"costSave":{"mean":16.6998,"ci":0.247},"energySave":{"mean":9.3629,"ci":0.1232},"costA":2956,"costB":3548,"peakA":959,"peakB":1170,"overMinA":0,"overMinB":249.5,"overKWhA":0,"overKWhB":270.9,"comfortA":99.9,"comfortB":100,"drA":142,"drB":7,"evA":100,"evB":100,"pvA":100,"pvB":100,"vacA":944,"vacB":2002,"scenario":{"id":"fault","dT":0,"sun":1,"occ":1,"ev":0,"limit":0,"drAt":-1,"drShed":0,"drMin":30,"fault":"stuck"},"injected":1,"detected":1,"falseAlarms":1,"delay":70},"worst":{"n":8,"limit":900,"costSave":{"mean":9.7819,"ci":0.2872},"energySave":{"mean":7.3711,"ci":0.1228},"costA":4267,"costB":4730,"peakA":1512,"peakB":1454,"overMinA":444.6,"overMinB":815.6,"overKWhA":1985.9,"overKWhB":4141.5,"comfortA":99.3,"comfortB":100,"drA":61,"drB":2,"evA":99,"evB":99,"pvA":100,"pvB":100,"vacA":1220,"vacB":2333,"scenario":{"id":"worst","dT":4,"sun":0.5,"occ":1,"ev":4,"limit":900,"drAt":960,"drShed":250,"drMin":60,"fault":""}}}}/*END*/;
const scK = (en, ko) => (insLang() === 'ko' ? ko : en);
const SCN_LIST = ['normal', 'heatwave', 'cloudy', 'dr', 'tight', 'evrush', 'holiday', 'fault', 'worst'];
const SCN_INFO = {
  normal: { name: ['Normal day', '평상시'],
    change: ['Base day: high ≈ 32.5 °C, mostly sunny, weekday occupancy, 15 EV sessions, one 30-min DR call between 14:00 and 17:20.',
      '기본 하루: 최고 약 32.5 °C, 대체로 맑음, 평일 재실, EV 15대, 오후 2시~5시 20분 사이 DR 30분 1회.'],
    agents: [['HVAC pre-cools occupied zones by 1 °C in the hour before the 13–19 h peak and relaxes them by 1 °C during it.', 'HVAC: 피크(13–19시) 1시간 전 재실 구역 1 °C 사전 냉방, 피크 중엔 1 °C 완화'],
      ['The battery charges at night, tops up before the peak and discharges in it, shaving import above 92 % of the limit.', 'ESS: 밤에 충전, 피크 전 보충, 피크에 방전 — 한도 92% 넘는 부분을 깎음'],
      ['Lighting dims to 85 % at peak; EV charging drops to the minimum that still meets departures.', '조명: 피크 85% 디밍 · EV: 출차는 지키는 최소 전력으로']],
    watch: ['Cost and energy saving, highest grid import.', '비용·에너지 절감, 최대 수전'] },
  heatwave: { name: ['Heatwave', '폭염'],
    change: ['+5 °C in the afternoon (high ≈ 37.5 °C) and +2.8 °C at night.', '기온 +5 °C(한낮 최고 약 37.5 °C), 밤에도 +2.8 °C'],
    agents: [['Cooling load pushes import toward the limit; the battery shaves what goes over 92 % of it.', '냉방 부하로 수전이 한도에 다가가면 ESS가 한도 92% 넘는 부분을 방전으로 깎음'],
      ['HVAC still pre-cools and relaxes, but cuts the relaxation to 0.4 °C in buildings where rooms already run 1.3 °C warm.', 'HVAC: 사전 냉방·완화는 그대로, 이미 1.3 °C 넘게 더운 방이 있는 건물은 완화를 0.4 °C로 줄임'],
      ['The coordinator trims pre-cooling when predicted import would pass 94 % of the limit.', '코디네이터: 예측 수전이 한도 94%를 넘으면 사전 냉방을 줄여 한도를 지킴']],
    watch: ['Minutes over the limit, highest import, comfort.', '한도 초과 분, 최대 수전, 쾌적'] },
  cloudy: { name: ['Overcast day', '흐린 날'],
    change: ['Irradiance at 25 %: solar output about a quarter of normal.', '일사량 25% — 태양광 발전이 평소의 약 4분의 1'],
    agents: [['The PV agent forecasts an hour ahead from the clear-sky index it sees, so its forecast drops with the clouds.', 'PV 에이전트: 지금의 맑음 지수로 1시간 앞을 예측해 발전 예측을 낮춤'],
      ['More daytime import: the battery spends more of its charge shaving the peak.', '낮 수전이 늘어 ESS가 피크 깎기에 더 많이 씀'],
      ['Less daylight, so daylight harvesting saves less lighting energy.', '주광이 줄어 조명 절감 여지도 작아짐']],
    watch: ['Highest import, solar self-consumption, cost.', '최대 수전, 태양광 자가소비율, 비용'] },
  dr: { name: ['Demand response', '수요반응 강화'],
    change: ['At 16:00 the utility asks for 300 kW less for 60 min (normally 160–220 kW for 30 min).', '오후 4시, 전력회사가 60분간 300 kW 감축 요청 (평소 160–220 kW · 30분)'],
    agents: [['The coordinator splits the shed by priority: battery → EV → lighting → HVAC.', '코디네이터가 감축량을 ESS → EV → 조명 → HVAC 순서로 나눔'],
      ['HVAC +1.4 °C (data centre +1.0 °C), lighting 70 %, EVs at minimum power, battery at full discharge.', 'HVAC +1.4 °C(데이터센터 +1.0 °C), 조명 70%, EV 최소 전력, ESS 최대 방전'],
      ['The rule-based BMS receives the signal but has no automatic response.', '룰 기반 BMS는 신호를 받아도 자동 대응이 없음']],
    watch: ['DR delivered vs requested, comfort during the event.', 'DR 달성률(요청 대비 실제 감축), 그 시간 쾌적'] },
  tight: { name: ['Lower peak limit', '피크 한도 하향'],
    change: ['Contracted limit cut from 1,000 kW to 850 kW.', '계약 한도 1,000 → 850 kW'],
    agents: [['Every threshold follows the limit (battery shaving at 92 %, coordinator cap at 94 %), so the agents step in earlier and more often.', '모든 기준이 한도를 따라 내려가(ESS 92%, 코디네이터 94%) 더 일찍, 더 자주 개입'],
      ['EVs are held at minimum power whenever import passes 90 % of the limit.', '수전이 한도 90%를 넘으면 EV를 최소 전력으로 묶음'],
      ['This is where negotiation pays: with the normal limit it adds no saving (evidence tab).', '협상 계층이 효과를 내는 조건 — 평소 한도에선 절감이 없음(검증·근거 탭)']],
    watch: ['Minutes and kWh over the limit, comfort.', '한도 초과 분·kWh, 쾌적'] },
  evrush: { name: ['Evening EV rush', '퇴근길 EV 몰림'],
    change: ['6 more EVs arrive 16:00–18:00 and stay overnight (20–45 kWh each).', 'EV 6대 추가 — 오후 4~6시 도착, 밤샘 주차, 대당 20–45 kWh'],
    agents: [['The EV agent holds charging at the minimum that meets each departure during the peak (to 19 h) and while import is above 90 % of the limit.', 'EV 에이전트: 피크(~19시)와 한도 90% 초과 때 출차 시각을 지키는 최소 전력으로 미룸'],
      ['The rule-based BMS charges at full power (22 kW) the moment a car plugs in.', '룰 BMS: 꽂자마자 최대 출력(22 kW)으로 충전'],
      ['There are only 6 chargers: later cars plug in as spaces free up.', '충전기는 6기뿐 — 자리가 비는 대로 연결됨']],
    watch: ['Highest import, EV sessions met.', '최대 수전, EV 충족률'] },
  holiday: { name: ['Holiday / break', '휴일·방학'],
    change: ['Offices and labs at 25 % occupancy; the dormitory as usual.', '오피스·연구동 재실 25% (기숙사는 그대로)'],
    agents: [['Room-level presence: empty rooms go to setback, lights off and plug loads cut.', '실별 재실 감지: 빈 방은 셋백·소등·대기전력 차단'],
      ['No optimal start: buildings that will stay mostly empty are not pre-conditioned.', '최적 기동 생략: 계속 비어 있을 건물은 미리 공조하지 않음'],
      ['The rule-based BMS follows the weekday timetable regardless.', '룰 BMS는 평일 시간표대로 공조·조명']],
    watch: ['Cost saving, energy spent on empty rooms.', '비용 절감, 빈 방 낭비 kWh'] },
  fault: { name: ['Sensor fault', '센서 고장'],
    change: ['30 min after the start, an office temperature sensor on B1 floor 3 freezes at one value.', '시작 30분 뒤 B1 3층 사무실 온도 센서가 한 값에 멈춤(고착)'],
    agents: [['Fault detection reads every sensor each 5 min; 45 min without change is flagged as stuck.', 'FDD: 5분마다 센서를 읽어 45분간 변화가 없으면 고착으로 판단'],
      ['Approve the alarm and that room is controlled from a virtual sensor (setpoint + peers’ error).', '경보를 승인하면 그 방은 가상 센서(설정값 + 이웃 방 오차)로 제어'],
      ['Limit: here the fault does not change control energy; with ?faultImpact=1 the room loops act on the faulty reading until FDD flags it.', '한계: 이 시나리오에서는 고장이 제어 에너지를 바꾸지 않음. ?faultImpact=1이면 FDD가 감지할 때까지 방 제어가 고장 값으로 동작']],
    watch: ['The fault alarm on the right, time to detection.', '오른쪽 이상 감지 카드, 감지까지 걸린 시간'] },
  worst: { name: ['Worst day (combined)', '최악의 날 (복합)'],
    change: ['+4 °C, 50 % sun, limit 900 kW, 250 kW DR for 60 min at 16:00, 4 extra EVs.', '기온 +4 °C · 일사 50% · 한도 900 kW · 오후 4시 DR 250 kW 60분 · EV +4대'],
    agents: [['Every agent acts at once: pre-cooling and relaxation, battery shaving and DR discharge, dimming, EV deferral.', '모든 에이전트가 동시에: 사전 냉방·완화, ESS 깎기·DR 방전, 조명 디밍, EV 미루기'],
      ['The coordinator balances the DR share against protecting the limit.', '코디네이터가 DR 분담과 한도 방어를 함께 조정']],
    watch: ['Minutes over the limit, DR delivered, comfort.', '한도 초과, DR 달성률, 쾌적'] },
};
const scnName = (id) => scK(...(SCN_INFO[id || 'normal'] || SCN_INFO.normal).name);
const scnCur = () => (lastSnap && lastSnap.currency) || '$';

// ---------- run a scenario: reload with its parameters (a fresh, reproducible day) ----------
function scnGo(p) {
  const q = new URLSearchParams(), keep = new URLSearchParams(location.search).get('lang');
  if (keep) q.set('lang', keep);
  for (const k in p) if (p[k] !== '' && p[k] !== null && p[k] !== undefined) q.set(k, p[k]);
  q.set('t', '10'); q.set('insights', 'scn');
  location.href = location.pathname + '?' + q.toString();
}

// ---------- top-bar button ----------
{
  const ib = document.getElementById('insightsBtn');
  if (ib) {
    const b = document.createElement('button');
    b.id = 'scnBtn'; b.type = 'button'; b.className = 'btn' + (SCN.id ? ' on' : '');
    b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h10M4 12h16M4 18h7"/><circle cx="17" cy="6" r="2.2"/><circle cx="14" cy="18" r="2.2"/></svg><span class="lbl"></span>';
    ib.parentNode.insertBefore(b, ib);
    b.addEventListener('click', () => openInsights('scn'));
  }
}
function scnBtnLabel() {
  const b = document.getElementById('scnBtn'); if (!b) return;
  b.querySelector('.lbl').textContent = SCN.id ? scK('Scenario: ', '시나리오: ') + scnName(SCN.id) : scK('Scenarios', '시나리오');
  b.title = scK('Run the campus under other conditions: heatwave, DR, lower limit, EV rush, faults…', '다른 조건으로 캠퍼스 돌려 보기: 폭염, DR, 한도 하향, EV 몰림, 센서 고장…');
}
scnBtnLabel();
onLang(scnBtnLabel);

// ---------- the scenario's sensor fault (client-side, like the fault drill) ----------
if (SCN.fault) {
  let t0 = null, done = false;
  Bus.on('tick', (s) => {
    if (done || !s) return;
    if (t0 === null) t0 = s.T;
    if (s.T < t0 + 30) return;
    const rooms = s.rooms || [], R = rooms.find((r) => r.id.startsWith('B1-F3-') && r.type === 'office') || rooms.find((r) => r.type === 'office');
    if (R && fddInject(R.id, SCN.fault, { rate: SCN.fault === 'drift' ? 0.05 : 0 })) {
      done = true;
      toast(scK(`Scenario: ${SCN.fault} fault injected in ${R.id}`, `시나리오: ${R.id} 센서에 ${({ stuck: '고착', drift: '드리프트', dropout: '끊김' })[SCN.fault]} 고장 주입`), 'var(--violet)');
    }
  });
}

// ---------- insights tab ----------
INS_TABS.push('scn');
{
  const nav = document.querySelector('#evOverlay .ev-tabs'), body = document.getElementById('evBody');
  if (nav && body) {
    nav.insertAdjacentHTML('beforeend', '<button role="tab" id="evTab-scn" data-tab="scn" aria-controls="evPane-scn" aria-selected="false" tabindex="-1"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h10M4 12h16M4 18h7"/><circle cx="17" cy="6" r="2.2"/><circle cx="14" cy="18" r="2.2"/></svg><span data-ins="eval.tab.scn">Scenarios</span></button>');
    body.insertAdjacentHTML('beforeend', '<div class="ev-pane" id="evPane-scn" data-pane="scn" role="tabpanel" aria-labelledby="evTab-scn"></div>');
  }
}
i18nAdd({ en: { 'eval.tab.scn': 'Scenarios' }, ko: { 'eval.tab.scn': '시나리오' } });

const scnN = (x, d = 0) => (x == null || !Number.isFinite(+x) ? '—' : pfN(x, d));
function scnMeasured(id) {                                  // what the 9-day headless runs measured for this scenario
  const R = SCN_RESULTS && SCN_RESULTS.runs && SCN_RESULTS.runs[id];
  if (!R) return `<div class="scn-res dim">${scK('Not measured yet', '아직 측정 전')}</div>`;
  if (id === 'fault') {
    return `<div class="scn-res">${scK('Measured', '측정')}: <span>${scK('detected', '감지')} <b>${R.detected}/${R.injected}</b></span>${R.delay != null ? `<span>${scK('after', '감지까지')} <b>${scnN(R.delay)}${scK(' min', '분')}</b></span>` : ''}${R.falseAlarms ? `<span>${scK('false alarms if left unhandled', '경보를 처리하지 않고 두면 오경보')} <b>${R.falseAlarms}</b></span>` : ''}<span>${scK('energy unchanged here (see ?faultImpact=1)', '여기선 에너지 영향 미반영(?faultImpact=1 참고)')}</span></div>`;
  }
  const bits = [`<span>${scK('cost', '비용')} <b>${R.costSave.mean >= 0 ? '−' : '+'}${scnN(Math.abs(R.costSave.mean), 1)}%</b><small> ±${scnN(R.costSave.ci, 1)}</small></span>`,
    `<span>${scK('peak', '최대 수전')} <b>${scnN(R.peakA)}</b> vs ${scnN(R.peakB)} kW</span>`];
  if (R.overMinA + R.overMinB > 0) bits.push(`<span>${scK('over limit', '한도 초과')} <b>${scnN(R.overMinA, 1)}</b> vs ${scnN(R.overMinB, 1)}${scK(' min/day', '분/일')}</span>`);
  bits.push(`<span>${scK('comfort', '쾌적')} <b>${scnN(R.comfortA, 1)}</b> vs ${scnN(R.comfortB, 1)}%</span>`);
  if (R.drA != null && (id === 'dr' || id === 'worst' || id === 'normal')) bits.push(`<span>DR <b>${scnN(R.drA)}</b> vs ${scnN(R.drB)}%</span>`);
  if (id === 'evrush') bits.push(`<span>${scK('EV met', 'EV 충족')} <b>${scnN(R.evA)}</b> vs ${scnN(R.evB)}%</span>`);
  if (id === 'cloudy') bits.push(`<span>${scK('PV self-use', '태양광 자가소비')} <b>${scnN(R.pvA)}</b> vs ${scnN(R.pvB)}%</span>`);
  if (id === 'holiday') bits.push(`<span>${scK('empty-room energy', '빈 방 낭비')} <b>${scnN(R.vacA)}</b> vs ${scnN(R.vacB)} kWh</span>`);
  return `<div class="scn-res" title="${scK('multi-agent vs rule-based BMS, mean of 8 days', '멀티에이전트 vs 룰 기반 BMS, 8일 평균')}">${scK('Measured (8 days, agents vs BMS)', '측정(8일, 에이전트 vs BMS)')}: ${bits.join('')}</div>`;
}
function scnCard(id) {
  const I = SCN_INFO[id], on = (SCN.id || 'normal') === id;
  return `<article class="scn-card${on ? ' on' : ''}"><h3>${scK(...I.name)}${on ? `<span class="scn-now">${scK('running', '실행 중')}</span>` : ''}</h3>
    <p class="scn-chg">${scK(...I.change)}</p>
    <ul>${I.agents.map((a) => `<li>${scK(...a)}</li>`).join('')}</ul>
    <p class="scn-watch">${scK('Watch: ', '볼 곳: ')}${scK(...I.watch)}</p>
    ${scnMeasured(id)}
    <button type="button" class="ev-btn" data-scn-go="${id}">${on ? scK('Restart this day', '이 하루 다시 시작') : scK('Run this scenario', '이 시나리오 실행')}</button></article>`;
}
function scnForm() {
  const c = SCN.id === 'custom' ? SCN : { dT: 0, sun: 1, occ: 1, limit: 1000, drAt: -1, drShed: 300, drMin: 60, ev: 0, fault: '' };
  const hm = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
  const rng = (k, lab, min, max, step, v, unit) => `<label>${lab} <output id="scnO-${k}">${v}${unit}</output><input type="range" id="scnI-${k}" min="${min}" max="${max}" step="${step}" value="${v}" data-unit="${unit}"></label>`;
  return `<form id="scnForm" class="scn-form">
    ${rng('dT', scK('Temperature change', '기온 변화'), -8, 10, 1, c.dT, ' °C')}
    ${rng('sun', scK('Sunshine', '일사량'), 0, 120, 5, Math.round(100 * c.sun), ' %')}
    ${rng('occ', scK('Office/lab occupancy', '오피스·연구동 재실'), 0, 150, 5, Math.round(100 * c.occ), ' %')}
    ${rng('limit', scK('Peak limit', '피크 한도'), 600, 1200, 50, c.limit || TOPO.peakLimit, ' kW')}
    ${rng('ev', scK('Extra evening EVs', '퇴근길 EV 추가'), 0, 12, 1, c.ev, scK(' cars', '대'))}
    <label>${scK('Sensor fault', '센서 고장')}<select id="scnI-fault" class="sel"><option value="">${scK('none', '없음')}</option>${['stuck', 'drift', 'dropout'].map((f) => `<option value="${f}"${c.fault === f ? ' selected' : ''}>${scK(f, ({ stuck: '고착', drift: '드리프트', dropout: '끊김' })[f])}</option>`).join('')}</select></label>
    <label class="scn-chk"><span><input type="checkbox" id="scnI-dr"${c.drAt >= 0 ? ' checked' : ''}> ${scK('DR call at', 'DR 발령 시각')}</span><input type="time" id="scnI-drAt" step="900" value="${hm(c.drAt >= 0 ? c.drAt : 960)}"></label>
    ${rng('drShed', scK('DR shed', 'DR 감축량'), 50, 500, 10, c.drShed || 300, ' kW')}
    ${rng('drMin', scK('DR length', 'DR 길이'), 15, 120, 15, c.drMin || 60, scK(' min', '분'))}
    <div class="scn-go"><button type="submit" class="ev-btn pri">${scK('Run these conditions', '이 조건으로 실행')}</button><small>${scK('Restarts the day at 10:00 with both controllers on these conditions. Real series (weather, tariff, meters) load through the data button.', '오전 10시부터 두 제어기가 이 조건으로 하루를 새로 시작합니다. 실제 기상·요금·계량 데이터는 상단 데이터 버튼으로 불러올 수 있습니다.')}</small></div>
  </form>`;
}
// Stage 1 preset: ?ablate=ROOM — the agents control buildings and zones only (no room occupancy sensors, smart plugs or room
// VAV; rooms run on the BMS room rules). Same weather and inputs as the normal day; the live table above shows the effect.
function scnStage1() {
  const on = ABLATE.has('ROOM');
  return `<section class="scn-card scn-stage1${on ? ' on' : ''}" style="margin-top:12px"><h3>${scK('Stage 1: building without room sensors', '1단계: 방 센서가 없는 건물')}${on ? `<span class="scn-now">${scK('running', '실행 중')}</span>` : ''}</h3>
    <p class="scn-chg">${scK('Agents control the building and its zones only — no room occupancy sensors, smart plugs or room VAV boxes; rooms stay on the BMS room rules.', '에이전트는 건물과 존 단위로만 제어합니다 — 방 재실 센서·스마트 플러그·방 VAV 없이, 방은 BMS 룰대로 돕니다.')}</p>
    <p class="scn-watch">${scK('Watch the live table above: empty-room energy and cost against the rule BMS (no numbers are fixed here). Uses ?ablate=ROOM.', '위의 실시간 표에서 빈 방 낭비와 비용을 룰 BMS와 비교해 보세요(여기엔 고정 수치가 없습니다). ?ablate=ROOM 과 같은 설정입니다.')}</p>
    <button type="button" class="ev-btn" data-scn-stage1="1">${on ? scK('Restart this day', '이 하루 다시 시작') : scK('Run stage 1', '1단계 실행')}</button></section>`;
}
function scnBuild(el) {
  el.innerHTML = `
  <section class="ev-mhead"><span class="ev-kicker">${scK('Scenarios', '시나리오')}</span>
    <h2>${scK('Change the conditions, see how the agents respond', '조건이 바뀌면 에이전트는 어떻게 움직이나')}</h2>
    <p>${scK('Pick a scenario and the day restarts at 10:00 under it. The multi-agent system and the rule-based BMS get the same weather, occupancy, EVs and DR signals side by side, so the difference between them is the difference in control. Speed up with 4× / 16× to reach the 13–19 h peak.',
      '시나리오를 고르면 오전 10시부터 그 조건으로 하루를 새로 시작합니다. 멀티에이전트와 룰 기반 BMS가 같은 날씨·재실·EV·DR 신호를 받아 나란히 돌기 때문에, 둘의 차이가 곧 제어의 차이입니다. 피크(13–19시)까지는 상단 4×·16×로 빨리 감으세요.')}</p>
    ${!SCN.id && ABLATE.has('ROOM') ? `<p class="pf-tag">${scK('Now running', '지금 실행 중')}: ${scK('Stage 1 (no room sensors)', '1단계(방 센서 없음)')} · <a href="#" data-scn-go="normal">${scK('back to the normal day', '평상시로 돌아가기')}</a></p>` : ''}
    ${SCN.id ? `<p class="pf-tag">${scK('Now running', '지금 실행 중')}: ${scnName(SCN.id)}${SCN.id === 'custom' ? ' — ' + scnSummary() : ''} · <a href="#" data-scn-go="normal">${scK('back to the normal day', '평상시로 돌아가기')}</a></p>` : ''}
  </section>
  <section class="ev-card scn-live"><h3>${scK('Today so far — agents vs rule-based BMS', '오늘 지금까지 — 에이전트 vs 룰 기반 BMS')}</h3><div id="scnLive">${scK('waiting for data…', '데이터를 기다리는 중…')}</div></section>
  <div class="scn-grid">${SCN_LIST.map(scnCard).join('')}</div>
  ${scnStage1()}
  <section class="ev-card" style="margin-top:14px"><h3>${scK('Build your own', '직접 만들기')}</h3>${scnForm()}</section>
  <p class="pf-note">${SCN_RESULTS ? scK(`Measured: each scenario run for ${SCN_RESULTS.days + 1} simulated days minute by minute (day 0 warm-up, days 1–${SCN_RESULTS.days} scored), multi-agent vs rule-based BMS on identical inputs; cost saving is the mean ± 95 % CI over days. DR scenarios call at 16:00: the BMS’s fixed battery discharge starts at 15:00 and would otherwise be counted as DR shed. Simulated, not metered (${SCN_RESULTS.date}).`,
    `측정: 시나리오마다 ${SCN_RESULTS.days + 1}일을 1분 단위로 시뮬레이션(첫날 준비, 1~${SCN_RESULTS.days}일 채점), 같은 입력에서 멀티에이전트와 룰 기반 BMS 비교. 비용 절감은 일별 평균 ± 95% 신뢰구간. DR 시나리오는 16시에 발령합니다 — 룰 BMS의 고정 배터리 방전이 15시에 시작돼, 15시 DR이면 그 방전이 감축으로 잘못 집계되기 때문입니다. 계량값이 아닌 시뮬레이션 결과입니다 (${SCN_RESULTS.date}).`) : ''}</p>`;
  el.querySelectorAll('[data-scn-go]').forEach((b) => b.addEventListener('click', (e) => { e.preventDefault(); const id = b.dataset.scnGo; scnGo(id === 'normal' ? {} : { scn: id }); }));
  el.querySelectorAll('[data-scn-stage1]').forEach((b) => b.addEventListener('click', () => scnGo({ ablate: 'ROOM' })));
  const f = el.querySelector('#scnForm');
  f.addEventListener('input', (e) => { const i = e.target; if (i.type === 'range') { const o = el.querySelector('#scnO-' + i.id.slice(5)); if (o) o.textContent = i.value + i.dataset.unit; } });
  f.addEventListener('submit', (e) => {
    e.preventDefault();
    const v = (k) => el.querySelector('#scnI-' + k).value, p = { scn: 'custom', dT: v('dT'), sun: +v('sun') / 100, occ: +v('occ') / 100, limit: v('limit'), ev: v('ev') };
    if (v('fault')) p.fault = v('fault');
    if (el.querySelector('#scnI-dr').checked) Object.assign(p, { drAt: v('drAt'), drShed: v('drShed'), drMin: v('drMin') });
    scnGo(p);
  });
  scnLive();
}
function scnSummary() {
  const s = SCN, out = [];
  if (s.dT) out.push(`${s.dT > 0 ? '+' : ''}${s.dT} °C`);
  if (s.sun !== 1) out.push(scK('sun ', '일사 ') + Math.round(100 * s.sun) + '%');
  if (s.occ !== 1) out.push(scK('occupancy ', '재실 ') + Math.round(100 * s.occ) + '%');
  if (s.limit) out.push(scK('limit ', '한도 ') + s.limit + ' kW');
  if (s.drAt >= 0) out.push(`DR ${String(Math.floor(s.drAt / 60)).padStart(2, '0')}:${String(s.drAt % 60).padStart(2, '0')} ${s.drShed || ''} kW ${s.drMin}${scK(' min', '분')}`);
  if (s.ev) out.push('EV +' + s.ev);
  if (s.fault) out.push(scK('fault ', '센서 ') + s.fault);
  return out.join(' · ') || scK('no changes', '변경 없음');
}
function scnLive() {                                        // today's figures of the run in progress
  const el = document.getElementById('scnLive'), s = lastSnap; if (!el || !s || !s.metrics) return;
  const A = s.metrics.agent || {}, B = s.metrics.baseline || {}, cur = scnCur();
  const row = (lab, a, b, d, unit, lowerIsBetter = true) => {
    const better = a == null || b == null ? '' : Math.abs(a - b) < 0.05 ? '' : (a < b) === lowerIsBetter ? 'scn-good' : 'scn-bad';
    return `<tr><td>${lab}</td><td class="${better}">${scnN(a, d)}${unit}</td><td>${scnN(b, d)}${unit}</td></tr>`;
  };
  const money = (v) => (v == null ? '—' : cur === '₩' ? '₩' + scnN(v, 0) : '$' + scnN(v, 0));
  el.innerHTML = `<table class="scn-tbl"><thead><tr><th>${scK('clock', '시각')} ${aiHM(s.clock)} · ${scK('limit', '한도')} ${scnN(s.peakLimit)} kW</th><th>${scK('Agents', '에이전트')}</th><th>${scK('Rule BMS', '룰 BMS')}</th></tr></thead><tbody>
    <tr><td>${scK('Cost', '비용')}</td><td class="${A.cost < B.cost - 0.5 ? 'scn-good' : ''}">${money(A.cost)}</td><td>${money(B.cost)}</td></tr>
    ${row(scK('Highest import', '최대 수전'), A.peakKW, B.peakKW, 0, ' kW')}
    ${row(scK('Minutes over limit', '한도 초과'), A.minutesOverLimit, B.minutesOverLimit, 0, scK(' min', '분'))}
    ${row(scK('Comfort', '쾌적'), A.comfortPct, B.comfortPct, 1, '%', false)}
    ${A.drRequestedKWh > 0 ? row(scK('DR delivered', 'DR 달성'), A.drPct, B.drPct, 0, '%', false) : ''}
    ${A.evSessions ? row(scK('EV sessions met', 'EV 충족'), A.evMetPct, B.evMetPct, 0, '%', false) : ''}
    ${row(scK('Energy on empty rooms', '빈 방 낭비'), A.vacantRoomKWh, B.vacantRoomKWh, 0, ' kWh')}
  </tbody></table>`;
}
INS_BUILD.scn = scnBuild;
{ const _iu = insUpdate; insUpdate = function () { _iu(); if (INS.open && INS.tab === 'scn') scnLive(); }; }
setTimeout(() => { if (window.MA_BEMS) window.MA_BEMS.scenario = SCN; }, 0);
