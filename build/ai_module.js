/* =====================================================================
   SECTION 7f — AI OPERATIONS ASSISTANT  (client of server/mabems_server.py)
   ---------------------------------------------------------------------
   Side-panel tab "AI" + top-bar button. Questions, briefings, explanations and control
   proposals go to POST /api/llm/chat (Server-Sent Events). The gateway picks the tier:
   local Ollama (qwen3-8b) first, Claude when the local model is down, slow, returns bad JSON
   or numbers the campus data does not contain. API keys never reach this page.
   On this PC the page is served by the gateway (same origin, no key). On the public site the
   gateway's tunnel address comes from config.json and every call carries an access key the
   operator handed out (a #key=… link or typed in the AI tab); the gateway checks it.
   aiContext() = compact JSON of the live snapshot; proposals are validated and clamped here
   and run only when the operator presses Apply (Sim.command).
   ===================================================================== */
const AI = { online: false, status: null, tier: 'auto', busy: false, chat: [], logs: [], tab: 'info', ctl: null, checkedAt: -1e9, hello: false,
  usage: { local: { calls: 0, tok: 0 }, api: { calls: 0, tok: 0, usd: 0 } } };
// Claude list prices, USD per million tokens: input, output, cached input (cost meter only; the gateway owns the model choice)
const AI_PRICE = { 'claude-opus-5-5': [4, 20, 0.2], 'claude-sonnet-5-5': [2, 10, 0.2], 'claude-haiku-5-5': [0.1, 0.5, 0.01] };
function aiRenderUsage() {
  const el = aiEl('aiDisclose'); if (!el) return;
  const u = AI.usage, k = (n) => (n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n));
  const line = u.local.calls + u.api.calls ? t('ai.usage', { lc: u.local.calls, lt: k(u.local.tok), ac: u.api.calls, at: k(u.api.tok), usd: u.api.usd.toFixed(3) }) : t('ai.usage.none');
  el.innerHTML = `<span class="ai-tag ai-badge">${uiEsc(t('ai.badge'))}</span> ${uiEsc(t('ai.disclose'))}<div class="ai-usage">${uiEsc(line)}</div>`;
}
try { AI.tier = localStorage.getItem('mabems.ai.tier') || 'auto'; } catch (e) { /* storage blocked */ }
AG.AI = { id: 'AI', short: 'AI', color: '#7B6CF6' };       // decision-log avatar for AI briefings
// where the gateway is: mode 'same' = this page came from the gateway (http://127.0.0.1:5178), 'remote' = public site
// (address from config.json, access key required), 'none' = a copy with no gateway (claude.ai link, file)
const AI_SITE = 'https://sunghyunc.github.io/ma-bems/';
const AI_LOCALHOST = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
const AI_GW = { mode: '', base: '', key: '', up: null, err: '' };
try { AI_GW.key = localStorage.getItem('mabems.ai.key') || ''; } catch (e) { /* storage blocked */ }
function aiKeyFromHash() {                               // share link …/#key=…: keep the key, then take it out of the address bar
  const m = /(?:^#|&)key=([A-Za-z0-9_-]{20,})/.exec(location.hash);
  if (!m) return false;
  AI_GW.key = m[1];
  try { localStorage.setItem('mabems.ai.key', AI_GW.key); } catch (e) { /* storage blocked */ }
  history.replaceState(null, '', location.pathname + location.search);
  return true;
}
aiKeyFromHash();
addEventListener('hashchange', () => { if (aiKeyFromHash()) aiCheck(true); });   // link pasted into an open tab
const aiAuth = () => (AI_GW.mode === 'remote' && AI_GW.key ? { Authorization: 'Bearer ' + AI_GW.key } : {});
i18nAdd({
  en: {
    'ai.btn': 'AI', 'ai.btn.title': 'AI operations assistant — local LLM first, Claude as backup', 'ui.ag.AI': 'AI assistant',
    'ai.tab.info': 'Info', 'ai.tab.ai': 'AI assistant',
    'ai.tier.auto': 'Auto · local first', 'ai.tier.local': 'Local only', 'ai.tier.api': 'Claude only', 'ai.tier.title': 'Which model answers',
    'ai.q.brief': 'Brief me', 'ai.q.explain': 'Explain selection', 'ai.q.propose': 'Suggest controls', 'ai.q.peak': 'Peak headroom?',
    'ai.q.peak.text': 'How much headroom is left to the peak limit, and what is driving grid import right now?',
    'ai.ph': 'Ask about loads, cost, comfort or the agents…', 'ai.send': 'Send', 'ai.stop': 'Stop',
    'ai.offline': 'The AI assistant runs through the local gateway, which keeps the API key off this page. Start it in the MA-BEMS folder:',
    'ai.offline.then': 'then open http://127.0.0.1:5178', 'ai.retry': 'Check again',
    'ai.remote': 'On this site the AI assistant answers with the language model running on the operator’s PC (local Qwen3-8B), reached through an encrypted tunnel. Enter the access key the operator gave you to turn it on.',
    'ai.remote.note': 'The simulation, agents, forecast and fault detection run in your browser without a key. The key is kept in this browser only.',
    'ai.gw.up': 'Operator PC: online', 'ai.gw.down': 'Operator PC: offline — the assistant is unavailable until the operator starts the gateway.',
    'ai.key.ph': 'Access key (mbk_…)', 'ai.key.go': 'Connect', 'ai.key.bad': 'That key was not accepted. Check it, or ask the operator for a new one.',
    'ai.key.user': 'Key · {n} · local model', 'ai.key.admin': 'Admin key · {n}', 'ai.key.forget': 'Forget this key in this browser',
    'ai.key.adminOnly': 'Claude is reserved for the operator’s admin key',
    'ai.copy': 'The AI assistant is not available in this copy. Open the public site to use it:',
    'ai.limit': 'Too many requests — try again in {s} s.', 'ai.busy': 'The operator’s model is busy with other questions — try again in a few seconds.',
    'ai.st.local': 'Local {m}', 'ai.st.api': 'Claude {m}', 'ai.st.on': 'ready', 'ai.st.off': 'off',
    'ai.meta.local': 'local · {m}', 'ai.meta.api': 'Claude · {m}', 'ai.esc': '{from} → {to}: {reason}', 'ai.tier.name.local': 'Local', 'ai.tier.name.api': 'Claude',
    'ai.check.ok': 'numbers match the data', 'ai.check.bad': 'not in the data: {v}', 'ai.cache': 'cache {n} tok', 'ai.err': 'No answer — {m}',
    'ai.needSel': 'Select a building, zone, room or asset first, then ask again.',
    'ai.prop.title': 'Proposed controls', 'ai.prop.apply': 'Apply', 'ai.prop.applied': 'Applied', 'ai.prop.none': 'No change needed right now.', 'ai.prop.skip': 'Not applicable: {why}',
    'ai.prop.toast': 'Applied AI proposal: {what}', 'ai.prop.note': 'Proposals run only when you press Apply. Limits: 22–28 °C, B4 cooling untouched.',
    'ai.why.zone': 'unknown zone', 'ai.why.room': 'unknown room', 'ai.why.value': 'invalid value', 'ai.why.b4': 'data-centre cooling stays as is', 'ai.why.type': 'unsupported action',
    'ai.why.cold': 'cold rooms stay at 4 °C',
    'ai.brief.log': 'AI briefing ({tier}): {text}',
    'ai.task.brief': 'Brief me on current operations.', 'ai.task.explain': 'Explain: {name}', 'ai.task.propose': 'Suggest control actions for the next hour.',
    'ai.hello': 'Ask about loads, cost, comfort or what the agents are doing. Answers use only the live campus data, and numbers that are not in it are flagged.',
    'ai.thinking': 'thinking…',
    'ai.badge': 'AI-generated', 'ai.disclose': 'AI-generated answers from a language model (local Qwen3-8B first, Claude when needed). Numbers are checked against live data; controls run only when you press Apply.',
    'ai.usage': 'This session: local {lc}× · {lt} tokens (no API cost) · Claude {ac}× · {at} tokens · ≈ ${usd}', 'ai.usage.none': 'No AI calls yet this session.',
    'ai.ex.title': 'Try asking', 'ai.ex.list': 'How much headroom to the peak?|When is electricity most expensive today?|Which building uses the most power?|What is the battery doing?|What is demand response?|Turn off the lights in empty rooms',
    'ai.canned': 'built-in reply', 'ai.cmd.tag': 'request read by the page · no model', 'ai.lookup': 'data lookup · no model',
    'ai.small.greet': 'Hello! I am the Helio Campus energy operations assistant. I answer from the live campus data (loads, cost, comfort, what the agents are doing) and can draft control actions that run only when you press Apply.',
    'ai.small.thanks': 'You are welcome. Ask me anything else about the campus.',
    'ai.small.bye': 'Bye. Open this tab again any time.',
    'ai.small.help': 'Here is what I can do:\n- Current state: load, peak headroom, tariff period, battery, solar, EV, floor temperatures, fault alarms\n- A briefing, or an explanation of the building, floor or room you select on the map\n- Control proposals: say "turn off the lights in empty rooms" and I draft actions you apply with a button\n- Terms: demand response, ESS, peak limit, how the savings are computed\nEvery number comes from the live data, and values that are not there are not made up.',
    'ai.rule.b4': 'Cooling for the data centre (B4) and the server and electrical rooms is never switched off or cut back (during demand response its setpoint is relaxed by only 1 °C): overheating servers cause outages. The peak is cut with the battery, deferred EV charging and wider setpoints in the other buildings instead.\n- For those actions, ask "What should we do to cut the peak?"',
  },
  ko: {
    'ai.btn': 'AI', 'ai.btn.title': 'AI 운영 비서 — 로컬 LLM 우선, Claude 보조', 'ui.ag.AI': 'AI 비서',
    'ai.tab.info': '정보', 'ai.tab.ai': 'AI 비서',
    'ai.tier.auto': '자동 · 로컬 우선', 'ai.tier.local': '로컬만', 'ai.tier.api': 'Claude만', 'ai.tier.title': '답변할 모델',
    'ai.q.brief': '운영 브리핑', 'ai.q.explain': '선택 대상 설명', 'ai.q.propose': '제어 제안', 'ai.q.peak': '피크 여유?',
    'ai.q.peak.text': '피크 한도까지 여유가 얼마나 남았고, 지금 계통 수전을 키우는 요인은 뭐야?',
    'ai.ph': '부하·요금·쾌적·에이전트에 대해 물어보세요…', 'ai.send': '보내기', 'ai.stop': '중지',
    'ai.offline': 'AI 비서는 API 키를 페이지 밖에 두는 로컬 게이트웨이를 거쳐 동작합니다. MA-BEMS 폴더에서 실행하세요:',
    'ai.offline.then': '그다음 http://127.0.0.1:5178 을 여세요', 'ai.retry': '다시 확인',
    'ai.remote': '이 사이트의 AI 비서는 운영자 PC에서 도는 언어모델(로컬 Qwen3-8B)이 암호화 터널을 거쳐 답합니다. 운영자에게 받은 접근 키를 넣으면 켜집니다.',
    'ai.remote.note': '시뮬레이션·에이전트·예측·고장 감지는 키 없이도 브라우저에서 모두 동작합니다. 키는 이 브라우저에만 저장됩니다.',
    'ai.gw.up': '운영자 PC: 켜짐', 'ai.gw.down': '운영자 PC: 꺼짐 — 운영자가 게이트웨이를 켜기 전까지 AI 비서를 쓸 수 없습니다.',
    'ai.key.ph': '접근 키 (mbk_…)', 'ai.key.go': '연결', 'ai.key.bad': '키가 맞지 않습니다. 다시 확인하거나 운영자에게 새 키를 받으세요.',
    'ai.key.user': '접근 키 · {n} · 로컬 모델', 'ai.key.admin': '관리자 키 · {n}', 'ai.key.forget': '이 브라우저에서 키 지우기',
    'ai.key.adminOnly': 'Claude는 운영자 관리자 키 전용입니다',
    'ai.copy': '이 사본에서는 AI 비서를 쓸 수 없습니다. AI 비서까지 쓰려면 공개 사이트에서 여세요:',
    'ai.limit': '요청이 너무 많습니다 — {s}초 뒤에 다시 시도하세요.', 'ai.busy': '운영자 PC의 모델이 다른 질문을 처리 중입니다 — 몇 초 뒤에 다시 시도하세요.',
    'ai.st.local': '로컬 {m}', 'ai.st.api': 'Claude {m}', 'ai.st.on': '준비', 'ai.st.off': '꺼짐',
    'ai.meta.local': '로컬 · {m}', 'ai.meta.api': 'Claude · {m}', 'ai.esc': '{from} → {to}: {reason}', 'ai.tier.name.local': '로컬', 'ai.tier.name.api': 'Claude',
    'ai.check.ok': '수치 검증 통과', 'ai.check.bad': '데이터에 없는 수치: {v}', 'ai.cache': '캐시 {n}토큰', 'ai.err': '응답 없음 — {m}',
    'ai.needSel': '먼저 건물·존·방·설비 중 하나를 선택한 뒤 다시 요청하세요.',
    'ai.prop.title': '제어 제안', 'ai.prop.apply': '적용', 'ai.prop.applied': '적용됨', 'ai.prop.none': '지금은 바꿀 필요가 없습니다.', 'ai.prop.skip': '적용 불가: {why}',
    'ai.prop.toast': 'AI 제안 적용: {what}', 'ai.prop.note': '적용 버튼을 눌러야만 실행됩니다. 범위 22–28 °C, B4 냉방은 건드리지 않습니다.',
    'ai.why.zone': '없는 존', 'ai.why.room': '없는 방', 'ai.why.value': '잘못된 값', 'ai.why.b4': '데이터센터 냉방은 유지', 'ai.why.type': '지원하지 않는 조치',
    'ai.why.cold': '저온실은 4 °C 유지',
    'ai.brief.log': 'AI 브리핑({tier}): {text}',
    'ai.task.brief': '현재 운영 상황을 브리핑해 줘.', 'ai.task.explain': '설명해 줘: {name}', 'ai.task.propose': '앞으로 1시간 동안의 제어 조치를 제안해 줘.',
    'ai.hello': '부하·요금·쾌적·에이전트 동작을 물어보세요. 답변은 실시간 캠퍼스 데이터만 근거로 하며, 데이터에 없는 수치는 표시해 드립니다.',
    'ai.thinking': '생각 중…',
    'ai.badge': 'AI 생성', 'ai.disclose': '이 탭의 답변은 언어모델(LLM)이 만든 AI 생성물입니다 — 로컬 Qwen3-8B 우선, 필요할 때 Claude. 숫자는 실시간 데이터와 자동 대조하고, 제어는 적용 버튼을 눌러야만 실행됩니다.',
    'ai.usage': '이번 세션: 로컬 {lc}회 · {lt}토큰(API 비용 없음) · Claude {ac}회 · {at}토큰 · 약 ${usd}', 'ai.usage.none': '이번 세션에는 아직 AI 호출이 없습니다.',
    'ai.ex.title': '예시 질문', 'ai.ex.list': '지금 피크 여유는?|오늘 가장 비싼 시간대는?|어느 건물이 제일 많이 써?|배터리는 지금 뭐 해?|DR이 뭐야?|빈 방 조명 꺼 줘',
    'ai.canned': '자동 안내', 'ai.cmd.tag': '요청 해석 · 모델 없이', 'ai.lookup': '데이터 조회 · 모델 없이',
    'ai.small.greet': '안녕하세요! Helio Campus 에너지 운영 비서입니다. 실시간 캠퍼스 데이터로 부하·요금·쾌적·에이전트 동작에 답하고, 필요하면 제어 조치를 제안합니다(적용 버튼을 눌러야 실행).',
    'ai.small.thanks': '천만에요. 더 궁금한 게 있으면 언제든 물어보세요.',
    'ai.small.bye': '네, 필요할 때 다시 불러 주세요.',
    'ai.small.help': '이런 일을 할 수 있습니다.\n- 지금 상태: 부하·피크 여유·요금 구간·배터리·태양광·EV·층별 온도·고장 알람\n- 운영 브리핑, 그리고 지도에서 고른 건물·층·방 설명\n- 제어 제안: "빈 방 조명 꺼 줘"처럼 말하면 조치를 만들고, 적용 버튼을 눌러야 실행\n- 용어 설명: DR, ESS, 피크 한도, 절감률 계산 방식 등\n수치는 모두 실시간 데이터에서 가져오고, 데이터에 없는 값은 지어내지 않습니다.',
    'ai.rule.b4': '데이터센터(B4)와 서버실·전기실 냉방은 운영 규칙상 끄거나 줄이지 않습니다(수요반응 때도 설정온도를 1 °C만 완화). 서버가 과열되면 장애로 이어지기 때문입니다. 피크는 ESS 방전, EV 충전 미루기, 다른 건물의 설정온도 완화로 낮춥니다.\n- 그런 조치가 필요하면 "피크 줄이려면 뭘 해야 돼?"처럼 물어보세요.',
  },
});

// ---------- DOM: top-bar button, side-panel tabs, AI pane ----------
{
  const ib = document.getElementById('insightsBtn');
  if (ib) {
    const b = document.createElement('button');
    b.id = 'aiBtn'; b.className = 'btn'; b.type = 'button'; b.setAttribute('data-i18n-title', 'ai.btn.title');
    b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15.5l-1.9-4.6L5.5 9l4.6-1.4z"/><path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8z"/></svg><span class="lbl" data-i18n="ai.btn">AI</span><i class="ai-dot"></i>';
    ib.parentNode.insertBefore(b, ib);
  }
  const head = document.getElementById('sideHead'), side = document.getElementById('side');
  if (head && side) {
    const tabs = document.createElement('div');
    tabs.id = 'sideTabs'; tabs.setAttribute('role', 'tablist');
    tabs.innerHTML = '<button type="button" data-tab="info" role="tab" data-i18n="ai.tab.info">Info</button><button type="button" data-tab="ai" role="tab"><span data-i18n="ai.tab.ai">AI assistant</span><i class="ai-dot"></i></button>';
    head.appendChild(tabs);
    const pane = document.createElement('section');
    pane.id = 'aiPane'; pane.className = 'hide';
    pane.innerHTML = `<div class="ai-top"><div id="aiStatus" class="ai-status"></div><select id="aiTier" class="sel" aria-label="AI tier"></select></div>
      <div id="aiDisclose" class="ai-disclose"></div>
      <div class="ai-quick" id="aiQuick"><button data-q="brief" data-i18n="ai.q.brief"></button><button data-q="explain" data-i18n="ai.q.explain"></button><button data-q="propose" data-i18n="ai.q.propose"></button><button data-q="peak" data-i18n="ai.q.peak"></button></div>
      <div id="aiMsgs" class="ai-msgs" aria-live="polite"></div>
      <div id="aiOff" class="ai-off hide"></div>
      <form id="aiForm" class="ai-form"><textarea id="aiInput" rows="2" data-i18n-placeholder="ai.ph"></textarea><button id="aiSend" class="btn" type="submit" data-i18n="ai.send">Send</button></form>`;
    side.appendChild(pane);
  }
  applyI18n(document.getElementById('topbar')); applyI18n(document.getElementById('side'));
}
const aiEl = (id) => document.getElementById(id);
function aiSetTab(tab) {
  AI.tab = tab === 'ai' ? 'ai' : 'info';
  const side = aiEl('side'); if (!side) return;
  side.classList.toggle('ai-mode', AI.tab === 'ai');
  aiEl('sideBody').classList.toggle('hide', AI.tab === 'ai');
  aiEl('aiPane').classList.toggle('hide', AI.tab !== 'ai');
  document.querySelectorAll('#sideTabs [data-tab]').forEach((b) => { const on = b.dataset.tab === AI.tab; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
  aiEl('aiBtn') && aiEl('aiBtn').classList.toggle('on', AI.tab === 'ai' && !document.body.classList.contains('side-off'));
  if (AI.tab === 'ai') { aiCheck(); if (!AI.hello) { AI.hello = true; aiBubble('note', `<p>${uiEsc(t('ai.hello'))}</p>${aiExamples()}`); } setTimeout(() => aiEl('aiInput') && aiEl('aiInput').focus(), 50); }
}
document.querySelectorAll('#sideTabs [data-tab]').forEach((b) => b.addEventListener('click', () => aiSetTab(b.dataset.tab)));
aiEl('aiBtn') && aiEl('aiBtn').addEventListener('click', () => {
  const hidden = document.body.classList.contains('side-off');
  if (!hidden && AI.tab === 'ai') { aiSetTab('info'); return; }
  if (hidden && typeof LY !== 'undefined') { LY.state.side = true; LY.sideAuto = false; lyApply(); }
  aiSetTab('ai');
});
function aiTierOptions() {
  const sel = aiEl('aiTier'); if (!sel) return;
  sel.innerHTML = ['auto', 'local', 'api'].map((k) => `<option value="${k}">${uiEsc(t('ai.tier.' + k))}</option>`).join('');
  sel.value = AI.tier; sel.title = t('ai.tier.title');
}
aiTierOptions();
aiEl('aiTier') && aiEl('aiTier').addEventListener('change', (e) => { AI.tier = e.target.value; try { localStorage.setItem('mabems.ai.tier', AI.tier); } catch (err) { /* storage blocked */ } });

// ---------- gateway status ----------
async function aiFindGateway() {
  if (AI_LOCALHOST) {                                    // served by the gateway on this PC?
    try { const r = await fetch('/api/llm/status', { cache: 'no-store' }); if (r.ok) { AI_GW.mode = 'same'; AI_GW.base = ''; return; } } catch (e) { /* another server */ }
  }
  try {                                                  // public site: the tunnel's current address
    const c = await (await fetch('config.json?t=' + Date.now(), { cache: 'no-store' })).json();
    const gw = String(c.gateway || '').trim().replace(/\/+$/, '');
    AI_GW.mode = 'remote'; AI_GW.base = /^https:\/\/[a-z0-9.-]+$/i.test(gw) ? gw : '';
    return;
  } catch (e) { /* no config.json */ }
  AI_GW.mode = AI_LOCALHOST ? 'same' : 'none'; AI_GW.base = '';
}
async function aiCheck(force) {
  if (!force && performance.now() - AI.checkedAt < 15000) return;
  AI.checkedAt = performance.now();
  let st = null, err = '';
  try {
    if (location.protocol === 'file:') throw new Error('file');
    if (!AI_GW.mode || !AI.online) await aiFindGateway();   // re-read after a failure: a restarted tunnel has a new address
    if (AI_GW.mode === 'same') {
      const r = await fetch('/api/llm/status', { cache: 'no-store' }); if (r.ok) st = await r.json();
    } else if (AI_GW.mode === 'remote') {
      if (!AI_GW.base) { AI_GW.up = false; err = 'down'; }
      else if (!AI_GW.key) { const h = await fetch(AI_GW.base + '/healthz', { cache: 'no-store' }); AI_GW.up = h.ok; err = 'nokey'; }
      else {
        const r = await fetch(AI_GW.base + '/api/llm/status', { cache: 'no-store', headers: aiAuth() }); AI_GW.up = true;
        if (r.ok) st = await r.json(); else err = r.status === 401 ? 'badkey' : 'HTTP ' + r.status;
      }
    }
  } catch (e) { AI_GW.up = false; }
  AI.status = st; AI.online = !!st; AI_GW.err = err;
  aiRenderStatus();
}
function aiSetKey(v) {
  AI_GW.key = String(v || '').trim();
  try { if (AI_GW.key) localStorage.setItem('mabems.ai.key', AI_GW.key); else localStorage.removeItem('mabems.ai.key'); } catch (e) { /* storage blocked */ }
  aiCheck(true);
}
function aiRenderStatus() {
  const st = AI.status, box = aiEl('aiStatus'), off = aiEl('aiOff');
  const up = AI.online && st && (st.local.alive || st.api.available);
  document.querySelectorAll('.ai-dot').forEach((d) => { d.className = 'ai-dot ' + (up ? 'on' : AI.online ? 'warn' : 'off'); });
  if (!box) return;
  if (!AI.online) {
    box.innerHTML = '';
    off.classList.remove('hide');
    if (AI_GW.mode === 'remote') {                       // public site: the assistant needs the operator's PC and a key
      const pc = AI_GW.up === true ? `<p class="ai-gw on"><i></i>${uiEsc(t('ai.gw.up'))}</p>` : AI_GW.up === false ? `<p class="ai-gw off"><i></i>${uiEsc(t('ai.gw.down'))}</p>` : '';
      off.innerHTML = `<p>${uiEsc(t('ai.remote'))}</p>${pc}<form id="aiKeyForm" class="ai-keyform"><input id="aiKeyIn" type="password" autocomplete="off" spellcheck="false" aria-label="${uiEsc(t('ai.key.ph'))}" placeholder="${uiEsc(t('ai.key.ph'))}"><button type="submit" class="btn">${uiEsc(t('ai.key.go'))}</button></form>`
        + (AI_GW.err === 'badkey' ? `<p class="ai-errtxt">${uiEsc(t('ai.key.bad'))}</p>` : '') + `<p class="ai-dim">${uiEsc(t('ai.remote.note'))}</p>`;
      aiEl('aiKeyForm').onsubmit = (e) => { e.preventDefault(); const v = aiEl('aiKeyIn').value.trim(); if (v) aiSetKey(v); };
    } else if (AI_GW.mode === 'none') {                  // a copy without a gateway (claude.ai link): point to the public site
      off.innerHTML = `<p>${uiEsc(t('ai.copy'))}</p><p><a href="${AI_SITE}" target="_blank" rel="noopener">${uiEsc(AI_SITE.replace(/^https:\/\//, ''))}</a></p>`;
    } else {
      off.innerHTML = `<p>${uiEsc(t('ai.offline'))}</p><code>.venv\\Scripts\\python server\\mabems_server.py</code><p>${uiEsc(t('ai.offline.then'))}</p><button type="button" class="btn" id="aiRetry">${uiEsc(t('ai.retry'))}</button>`;
      if (aiEl('aiRetry')) aiEl('aiRetry').onclick = () => aiCheck(true);
    }
    aiEl('aiForm').classList.add('dis'); aiEl('aiQuick').classList.add('dis');
    return;
  }
  off.classList.add('hide'); aiEl('aiForm').classList.remove('dis'); aiEl('aiQuick').classList.remove('dis');
  const chip = (on, label, title) => `<span class="ai-chip ${on ? 'on' : 'off'}" title="${uiEsc(title || '')}"><i></i>${uiEsc(label)}</span>`;
  const acc = st.access, userKey = acc && acc.scope !== 'admin';
  box.innerHTML = chip(st.local.alive && st.local.installed, t('ai.st.local', { m: st.local.model }), st.local.base_url)
    + chip(st.api.available, t('ai.st.api', { m: st.api.model.replace(/^claude-/, '') }), userKey ? t('ai.key.adminOnly') : st.api.reason || `effort ${st.api.effort} · ${st.api.calls_last_hour}/${st.api.cap_per_hour} h`)
    + (acc ? `<span class="ai-chip key">${uiEsc(t(userKey ? 'ai.key.user' : 'ai.key.admin', { n: acc.name }))}<button type="button" id="aiKeyOut" title="${uiEsc(t('ai.key.forget'))}" aria-label="${uiEsc(t('ai.key.forget'))}">×</button></span>` : '');
  if (aiEl('aiKeyOut')) aiEl('aiKeyOut').onclick = () => aiSetKey('');
  const sel = aiEl('aiTier'), apiOpt = sel && sel.querySelector('option[value="api"]');   // a user key cannot pick Claude
  if (apiOpt) { apiOpt.disabled = !!userKey; if (userKey && sel.value === 'api') sel.value = AI.tier = 'auto'; }
}
setTimeout(() => aiCheck(true), 1500);
setInterval(() => { if (AI.tab === 'ai' && !document.hidden) aiCheck(); }, 20000);

// ---------- live campus context (compact, rounded: easier for the model and for the number check) ----------
const aiR = (v, d = 1) => (Number.isFinite(+v) ? +(+v).toFixed(d) : null);
const aiHM = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(Math.floor(m % 60)).padStart(2, '0')}`;
Bus.on('log', (e) => { AI.logs.push(e); if (AI.logs.length > 40) AI.logs.shift(); });
function aiRoomView(R) {
  if (!R) return null;
  const meta = (typeof INT_ROOM !== 'undefined' && INT_ROOM[R.id]) || {};
  return { id: R.id, name: LANG === 'ko' ? (meta.nameKo || R.nameKo || R.name) : (meta.name || R.name), type: meta.type || R.type, people: R.people, capacity: meta.cap,
    tempC: aiR(R.T), setpointC: aiR(R.sp), userSetpointC: aiR(R.spUser), kW: aiR(R.kw, 2), lightKW: aiR(R.lightKW, 2), plugKW: aiR(R.plugKW, 2), hvacKW: aiR(R.hvacKW, 2),
    lights: R.lights, lightLevelPct: aiR(100 * (R.lightLevel || 0), 0), plugMode: R.plugMode, hvacMode: R.hvacMode, vacantMin: aiR(R.vacantMin, 0), lastAction: R.action || undefined };
}
function aiSelected(s) {
  const k = selection.kind, id = selection.id; if (!k) return null;
  const label = (selection.info && typeof uiPick === 'function') ? uiPick(selection.info).label : id;
  const out = { kind: k, id, label };
  if (k === 'building' && s.buildings[id]) { const b = s.buildings[id]; Object.assign(out, { loadKW: aiR(b.load), hvacKW: aiR(b.hvac), lightKW: aiR(b.light), plugKW: aiR(b.plug), itKW: aiR(b.it), pvKW: aiR(b.pv), occupancyPct: aiR(100 * b.occ, 0), people: b.people, setpointOffsetC: aiR(b.spOffset) }); out.zones = (s.zones || []).filter((z) => z.id.startsWith(id + '-')).map((z) => ({ id: z.id, tempC: aiR(z.T), setpointC: aiR(z.sp), occupancyPct: aiR(100 * z.occ, 0), kW: aiR(z.kw), inBand: z.inBand })); }
  else if (k === 'zone') { const z = (s.zones || []).find((q) => q.id === id); if (z) Object.assign(out, { tempC: aiR(z.T), setpointC: aiR(z.sp), userSetpointC: aiR(z.spUser), occupancyPct: aiR(100 * z.occ, 0), kW: aiR(z.kw), inBand: z.inBand }); out.rooms = (s.rooms || []).filter((R) => R.id.startsWith(id + '-')).map(aiRoomView); }
  else if (k === 'room') out.room = aiRoomView((s.rooms || []).find((R) => R.id === id));
  else if (k === 'ess') Object.assign(out, { socPct: aiR(100 * s.soc, 0), powerKW: aiR(s.essP) });
  else if (k === 'pv') Object.assign(out, { campusPvKW: aiR(s.pv), irradianceWm2: aiR(s.env && s.env.irr, 0) });
  else if (k === 'charger' || k === 'ev') Object.assign(out, { evKW: aiR(s.ev), chargers: (s.chargers || []).map((c) => ({ id: c.id, kW: aiR(c.kw || c.p), soc: aiR(c.soc != null ? 100 * c.soc : null, 0) })) });
  else if (k === 'agent') { const a = (s.agents || []).find((q) => q.id === id); if (a) Object.assign(out, { stage: a.stage >= 0 ? t('ui.stage.' + a.stage) : 'idle', round: a.round, nextInMin: aiR(a.nextIn, 0) }); }
  return out;
}
// Fields added on 2026-11-10 after asking the assistant 66 questions visitors are likely to type (ft/data/realq.json):
// it had no off-peak hours or prices (answered "the cheapest time is now" during the peak), no per-floor data (answered
// "B1 floor 3" with B3 floor 3's values), no room or EV counts and no scenario. Each block below fills one of those gaps.
function aiTariff(s) {                                     // every load period, most expensive first, and when this one ends
  const tierAt = (h) => { const inR = (rs) => rs.some(([a, b]) => h >= a && h < b); return inR(TOU_HOURS.peak) ? 'peak' : inR(TOU_HOURS.mid) ? 'mid' : 'off'; };
  const runs = { peak: [], mid: [], off: [] };
  for (let a = 0, h = 1; h <= 24; h++) if (h === 24 || tierAt(h) !== tierAt(a)) { runs[tierAt(a)].push([a, h]); a = h; }
  for (const k in runs) { const r = runs[k]; if (r.length > 1 && r[0][0] === 0 && r[r.length - 1][1] === 24) r[0] = [r.pop()[0], r[0][1]]; }   // 22-24 + 0-8 → 22-8
  const hh = (x) => String(x % 24).padStart(2, '0') + ':00';
  const kp = typeof KEPCO !== 'undefined' && KEPCO.active, R = kp ? (KEPCO.rates[KEPCO.season] || KEPCO.rates.summer) : null;
  const fromData = !kp && typeof simData !== 'undefined' && simData && simData.col && simData.col.price;   // a loaded price column overrides the table
  const name = (k) => (LANG === 'ko' ? TOU[k].nameKo : TOU[k].name);
  const order = ['peak', 'mid', 'off'].filter((k) => runs[k].length);
  const rank = LANG === 'ko' ? ['가장 비쌈', '중간', '가장 쌈'] : ['most expensive', 'middle', 'cheapest'];
  const schedule = order.map((k, i) => Object.assign({ tier: name(k), hours: runs[k].map(([a, b]) => `${hh(a)}-${hh(b)}`).join(', ') },
    fromData ? {} : { pricePerKWh: kp ? R[k] : TOU[k].price }, { rank: i === 0 ? rank[0] : i === order.length - 1 ? rank[2] : rank[1] }));
  const h0 = Math.floor((s.clock % 1440) / 60), now = tierAt(h0);
  let end = h0 + 1; while (end < h0 + 24 && tierAt(end % 24) === now) end++;
  // "from" first: with only "to", v2.1 twice read the next period as the current one ("지금은 중간부하" at 14:36)
  return { schedule, nextChange: { from: name(now), to: name(tierAt(end % 24)), at: hh(end), inMin: Math.round(end * 60 - (s.clock % 1440)) } };
}
function aiPeakAt(s) {                                     // the 15-min slot of today's highest grid import
  try {
    const h = s.hist('grid'), last = Math.min(95, Math.floor((s.clock % 1440) / 15));
    let bi = -1; for (let i = 0; i <= last; i++) if (Number.isFinite(h[i]) && (bi < 0 || h[i] > h[bi])) bi = i;
    return bi < 0 ? null : aiHM(bi * 15);
  } catch (e) { return null; }
}
function aiScenario() {
  try {
    const id = (typeof SCN !== 'undefined' && SCN.id) || 'normal', k = LANG === 'ko' ? 1 : 0, I = SCN_INFO[id];
    if (!I) return { id, name: LANG === 'ko' ? '사용자 정의' : 'Custom', settings: typeof scnSummary === 'function' ? scnSummary() : '' };
    return { id, name: I.name[k], whatIsDifferent: I.change[k], howAgentsRespond: I.agents.map((a) => a[k]) };
  } catch (e) { return null; }
}
// what a question points at: zone / room ids, building names, "lights in empty rooms" (used to pick proposal candidates)
const AI_BLD = [[/오피스|타워|본관|office/i, 'B1'], [/연구동|lab\b|research/i, 'B2'], [/기숙사|dorm/i, 'B3'], [/데이터 ?센터|data ?cent/i, 'B4']];
function aiFocus(q) {
  const f = { zones: new Set(), rooms: new Set(), bld: new Set(), vacantLights: false }, s = String(q || '');
  for (const m of s.matchAll(/\bB([1-4])\s*-?\s*F\s*(\d{1,2})(?:\s*-?\s*R\s*(\d{1,2}))?/gi)) { f.zones.add(`B${m[1]}-F${+m[2]}`); if (m[3]) f.rooms.add(`B${m[1]}-F${+m[2]}-R${+m[3]}`); }
  for (const m of s.matchAll(/\bB([1-4])(?![-\d])/gi)) f.bld.add('B' + m[1]);
  for (const [rx, b] of AI_BLD) if (rx.test(s)) f.bld.add(b);
  const fl = /(\d{1,2})\s*층/.exec(s); if (fl) for (const b of f.bld) f.zones.add(`${b}-F${+fl[1]}`);
  f.vacantLights = /(불|조명|전등|라이트|light)/i.test(s) && /(빈|공실|아무도|비어|empty|vacant|unoccupied)/i.test(s);
  return f;
}
function aiContext(task, question) {
  const s = lastSnap; if (!s) return '';
  const cur = s.currency || '$', m = s.metrics || {}, pick = (o) => { const r = {}; for (const key in o || {}) if (typeof o[key] === 'number') r[key] = aiR(o[key], 2); return r; };
  const zones = (s.zones || []).map((z) => ({ id: z.id, tempC: aiR(z.T), setpointC: aiR(z.sp), occupancyPct: aiR(100 * z.occ, 0), kW: aiR(z.kw), inBand: z.inBand, dev: Math.abs((z.T || 0) - (z.spUser || z.sp || 0)) }));
  const rooms = (s.rooms || []).filter((R) => R.name !== 'Cold room'), lit = (R) => (R.lightLevel || 0) > 0.05, empty = (R) => !((R.people || 0) > 0);
  const vacantLit = rooms.filter((R) => empty(R) && lit(R)).sort((a, b) => (b.lightKW || 0) - (a.lightKW || 0));
  const roomName = (R) => { const meta = (typeof INT_ROOM !== 'undefined' && INT_ROOM[R.id]) || {}; return LANG === 'ko' ? (meta.nameKo || R.nameKo || R.name) : (meta.name || R.name); };
  const tf = aiTariff(s), chargers = s.chargers || [];
  const ctx = {
    units: 'kW, kWh, °C; costs in ' + cur + '; times on the simulation clock',
    clock: aiHM(s.clock), day: s.day, controlMode: s.mode === 'agent' ? 'multi-agent' : 'rule-based baseline',
    tariff: Object.assign({ tier: s.tou, pricePerKWh: aiR(s.price, 3), currency: cur, peakHours: TOU_HOURS.peak.map(([x, y]) => `${x}-${y}h`).join(', ') },
      KEPCO.active ? { plan: `${KEPCO.name} (${KEPCO.edition})`, demandChargePerKWMonth: KEPCO.demandKRWperKWmonth } : {},
      { schedule: tf.schedule, nextChange: tf.nextChange }),
    weather: { outdoorC: aiR(s.env && s.env.tout), irradianceWm2: aiR(s.env && s.env.irr, 0) },
    campus: { loadNowKW: aiR(s.load), gridImportNowKW: aiR(s.grid), peakLimitKW: s.peakLimit, headroomNowKW: aiR(s.peakLimit - s.grid), headroomNowPct: aiR(100 * (s.peakLimit - s.grid) / s.peakLimit, 0),
      pvNowKW: aiR(s.pv), essNowKW: aiR(s.essP), essNote: 'essNowKW > 0 = discharging, < 0 = charging', essSocPct: aiR(100 * s.soc, 0), evNowKW: aiR(s.ev), chillerNowKW: aiR(s.chiller), baselineGridNowKW: aiR(s.gridBase) },
    today: { energyKWh: aiR(s.energy, 0), cost: aiR(s.cost, 0), costAgent: aiR(s.costAgent, 0), costBaseline: aiR(s.costBase, 0), savingsPct: aiR(100 * s.savings), highestGridImportTodayKW: aiR(s.peak, 0), highestGridImportAt: aiPeakAt(s), comfortPct: aiR(100 * s.comfort, 1), zonesInBand: s.inBand, zonesCounted: s.counted },
    buildingsByLoad: Object.entries(s.buildings || {}).sort((a, b) => b[1].load - a[1].load).map(([id, b], i) => ({ rank: i + 1, id, name: uiBldName(id), loadKW: aiR(b.load), hvacKW: aiR(b.hvac), lightKW: aiR(b.light), plugKW: aiR(b.plug), itKW: aiR(b.it), pvKW: aiR(b.pv), occupancyPct: aiR(100 * b.occ, 0), people: b.people, lightLevelPct: aiR(100 * b.lightLevel, 0) })),
    buildingsNote: 'buildingsByLoad is sorted by current loadKW, largest first (rank 1 = largest)',
    zonesNeedingAttention: zones.filter((z) => !z.inBand || z.dev > 1).sort((a, b) => b.dev - a.dev).slice(0, 6).map(({ dev, ...z }) => z),
    floors: zones.map(({ dev, ...z }) => z),
    floorsNote: 'floors lists every floor (zone) of every building: id B1-F3 = building B1, floor 3',
    rooms: { total: rooms.length, occupied: rooms.filter((R) => !empty(R)).length, vacantWithLightsOn: vacantLit.length,
      vacantWithLightsOnRooms: vacantLit.slice(0, 6).map((R) => ({ id: R.id, name: roomName(R), vacantMin: aiR(R.vacantMin, 0) })),
      note: LANG === 'ko' ? '조명 에이전트는 10분 넘게 빈 방을 소등합니다' : 'the lighting agent switches off rooms empty for more than 10 min' },
    ev: { chargers: chargers.length, carsConnected: chargers.filter((c) => c.s).length, charging: chargers.filter((c) => (c.p || 0) > 0.1).length, totalKW: aiR(s.ev) },
    assets: { essCapacityKWh: TOPO.ess.capKWh, essMaxKW: TOPO.ess.maxKW },
    scenario: aiScenario(),
    demandResponse: s.dr && s.dr.active ? { active: true, shedKW: aiR(s.dr.shed), start: aiHM(s.dr.start % 1440), end: aiHM(s.dr.end % 1440), source: s.dr.source } : { active: false },
    alerts: (s.alerts || []).slice(0, 5).map((a) => `${a.level}: ${a.text}${a.sub ? ' — ' + a.sub : ''}`),
    agents: (s.agents || []).map((a) => `${uiAgName(a.id)}: ${a.stage >= 0 ? t('ui.stage.' + a.stage) : 'idle'} (round ${a.round})`),
    recentDecisions: AI.logs.filter((e) => e.model === s.mode && e.agent !== 'AI').slice(-8).map((e) => `${e.clock} ${uiAgName(e.agent)}: ${e.i18n && e.i18n[LANG] ? e.i18n[LANG] : e.text}`),
    dayMetrics: { agent: pick(m.agent), baseline: pick(m.baseline) },
    dataset: s.dataset ? s.dataset.name : null,
  };
  try { ctx.forecast = fcSummary(); ctx.faults = fddSummary(); } catch (e) { /* forecast / FDD not ready yet */ }
  const sel = aiSelected(s); if (sel) ctx.selected = sel;
  if (task === 'propose') {                                // ids the model may use; the ones the request names come first
    delete ctx.dayMetrics; delete ctx.agents; delete ctx.floors; delete ctx.floorsNote; delete ctx.scenario; ctx.recentDecisions = ctx.recentDecisions.slice(-4);
    const f = aiFocus(question), zoneOf = (id) => id.split('-').slice(0, 2).join('-');
    const zRank = (z) => (f.zones.has(z.id) ? 0 : f.bld.has(z.id.slice(0, 2)) ? 1 : 2);
    const rRank = (R) => (f.rooms.has(R.id) || (f.vacantLights && empty(R) && lit(R)) ? 0 : f.zones.has(zoneOf(R.id)) ? 1 : f.bld.has(R.id.slice(0, 2)) ? 2 : 3);
    ctx.candidateZones = zones.filter((z) => !z.id.startsWith('B4')).sort((a, b) => zRank(a) - zRank(b) || b.kW - a.kW).slice(0, 8).map((z) => ({ id: z.id, tempC: z.tempC, setpointC: z.setpointC, occupancyPct: z.occupancyPct, kW: z.kW }));
    ctx.candidateRooms = rooms.filter((R) => !R.id.startsWith('B4') && ((R.kw || 0) > 0.2 || rRank(R) < 3))   // walk-in cold rooms hold 4 °C (filtered above)
      .sort((a, b) => rRank(a) - rRank(b) || ((a.people || 0) > 0) - ((b.people || 0) > 0) || (b.kw || 0) - (a.kw || 0)).slice(0, 8)
      .map((R) => ({ id: R.id, people: R.people, tempC: aiR(R.T), setpointC: aiR(R.sp), kW: aiR(R.kw, 2), lights: R.lights, lightLevelPct: aiR(100 * (R.lightLevel || 0), 0), hvacMode: R.hvacMode }));
  }
  return JSON.stringify(ctx);
}

// ---------- messages ----------
function aiFmt(text) {
  const lines = uiEsc(String(text || '')).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/^\s*#{1,6}\s*(.+)$/gm, '<b>$1</b>').split(/\n+/);
  let html = '', list = false;
  for (const ln of lines) {
    const m = /^\s*(?:[-•*]|\d+[.)])\s+(.*)$/.exec(ln);
    if (m) { if (!list) { html += '<ul>'; list = true; } html += `<li>${m[1]}</li>`; continue; }
    if (list) { html += '</ul>'; list = false; }
    if (ln.trim()) html += `<p>${ln}</p>`;
  }
  return html + (list ? '</ul>' : '');
}
function aiBubble(role, html) {
  const box = aiEl('aiMsgs'), el = document.createElement('div');
  el.className = 'ai-msg ' + role; el.innerHTML = `<div class="ai-body">${html || ''}</div><div class="ai-foot"></div>`;
  box.appendChild(el); box.scrollTop = box.scrollHeight; return el;
}
function aiNote(text) { aiBubble('note', `<p>${uiEsc(text)}</p>`); }
const aiScroll = () => { const box = aiEl('aiMsgs'); if (box) box.scrollTop = box.scrollHeight; };
async function aiStream(body, on) {
  const ctl = new AbortController(); AI.ctl = ctl;
  const res = await fetch(AI_GW.base + '/api/llm/chat', { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, aiAuth()), body: JSON.stringify(body), signal: ctl.signal });
  if (!res.ok || !res.body) {                            // the public API answers errors as JSON: rate limit, busy, key
    let msg = 'HTTP ' + res.status;
    try { const j = await res.json(); msg = res.status === 429 ? t('ai.limit', { s: j.retry_after_s || 60 }) : res.status === 503 ? t('ai.busy') : res.status === 401 ? t('ai.key.bad') : (j.error || msg); } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  const rd = res.body.getReader(), dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await rd.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      let ev = 'message', data = '';
      for (const line of chunk.split('\n')) { if (line.startsWith('event: ')) ev = line.slice(7); else if (line.startsWith('data: ')) data += line.slice(6); }
      if (data) on(ev, JSON.parse(data));
    }
  }
}
// ---------- what a typed question is: small talk and rule questions get a built-in reply, requests to change
// something become a control proposal (cards with Apply), everything else goes to the model as a question ----------
const AI_RX = {
  greet: /^\s*(안녕|안뇽|하이|헬로|반가|hi\b|hello|hey\b|good (morning|afternoon|evening))/i,
  thanks: /(고마워|고맙|감사|땡큐|thank|thx)/i,
  bye: /^\s*(잘 ?가|바이|bye|수고(했|하셨|해))/i,
  help: /(뭘|무엇을|뭐|어떤 걸|어떤 것을?)\s*(할 수|도와|해 ?줄 수|물어)|할 수 있는 (일|것|게|기능)|사용법|도움말|기능(이|은|을)?\s*(뭐|알려)|what can you|how (do|can) i use|\bhelp\b/i,
  // requests to change something. Extended 2026-11-12 (v2.2 fine-tune data): of the model-written request phrasings in
  // ft/data/v22 (train split) 58 % fell through to chat ("냉방 약하게 부탁해", "낮춰 주시겠어요?", "조명 에너지 절감해 주세요",
  // "Can you ease off the AC?"): more control verbs and request endings; English requests need a request opener
  cmd: /(?:꺼|켜|끄|올려|내려|낮춰|높여|줄여|늘려|바꿔|맞춰|아껴|틀어|잡아|돌려|당겨|미뤄|멈춰|약하게 해|세게 해|강하게 해|(?:조절|조정|설정|해제|전환|완화|절약|절감|제어|차단|중지|정지|운영|감축|축소)\s?해)\s*(?:줘|주세요|주라|줄래|줄 ?수|봐|달라|주실|주시(?:겠|고|기|면\s?좋)|주면\s?좋|부탁)|(?:약하게|세게|강하게|어둡게|밝게|높게|낮게|덜\s?\S{1,4}게)\s*(?:해|틀어|돌려|맞춰|만들어)?\s*(?:줘|주세요|주시|주실|줄래|달라|부탁)|\b(turn|switch)\s+(on|off)\b|\bset\b.+\bto\b|\b(lower|raise|dim)\b|\b(please|can you|could you|would you|can we|could we|you could|let['’]?s|go ahead and)\s+(?:kindly\s+|please\s+|just\s+|maybe\s+)?(?:ease|dial|turn|lower|raise|reduce|cut|adjust|warm|cool|soften|switch|dim|bump|tone|make\s+(?:it|things|the\s+\w+)\s+(?:less|more|warmer|cooler|darker|dimmer|brighter)|bring\s+(?:it|the\s+\w+(?:\s+\w+)?)\s+(?:down|up))\b/i,
  advice: /(줄이려면|낮추려면|아끼려면|절약하려면|절감하려면|막으려면|피하려면).*(뭘|무엇|어떻게|방법|조치|할\s?일|해야)|(줄이려면|낮추려면|아끼려면|절약하려면|절감하려면)\s*[?？]?\s*$|(뭘|무엇을|어떻게)\s*해야|(조치|제어)(를|가|는|은)?\s*(뭐|무엇|뭔|추천|제안|필요)|(해야\s?할|할\s?수\s?있는|취할|취해야\s?할)\s?(일|조치)|(줄일|낮출|아낄|절약할|절감할|막을|피할)\s?(수\s?있는\s?)?(방법|조치)|what should (we|i) (do|adjust|change|turn)|what to do\b|how (can|do|should) (we|i) (cut|reduce|lower|save|shave|bring down|avoid|keep)|\b(steps|actions|ways?|plan|list of actions)\s+(to|for)\b.{0,30}\b(cut|reduce|lower|save|shave|bring down)\b|\b(advise|recommend|suggest)\b.{0,50}\b(cut|reduce|lower|save|shave)\b/i,
  energy: /(피크|전력|전기|요금|비용|부하|수전|냉방|난방|조명|전등|밝기|불|온도|에너지|탄소|한도|kW|절약|절감|에어컨|공조|배터리|ESS|EV|peak|power|load|cost|cooling|light|energy|temperature|air ?con|\bAC\b|HVAC|setpoint|thermostat|electric|bill|demand)/i,
  b4: /(데이터 ?센터|\bB4\b|서버실|전기실|data ?cent|server room)/i,
  cool: /(냉방|에어컨|공조|cool|\bAC\b|HVAC)/i,
  down: /(꺼|끄|줄|낮|중지|멈|off|cut|reduce|lower|stop)/i,
  // "지금 상태 괜찮아?" asks for an overview: the trained briefing answers it (v2.1 gave the cost template instead)
  overview: /(괜찮|상태\s?(어때|어떄|어떻|좋|는\s?어)|문제\s?(없|있)|이상\s?(없|있)|잘\s?(돌아|되고)|어떻게\s?돌아가|전반적|상황\s?(어때|어떻|좀)|how\s+are\s+(we|things)|everything\s+ok|overall|overview)/i,
  subject: /(배터리|ESS|태양광|PV|EV|전기차|충전|건물|층|B[1-4]|방|조명|냉방|난방|요금|비용|탄소|날씨|DR|고장|센서|피크|한도|에이전트|한\s?(줄|문장)|one\s+(line|sentence)|battery|solar|building|floor|room|cost|price|carbon|weather|fault|sensor|peak|limit|agent)/i,
};
function aiRoute(text) {
  const q = String(text || '').trim(), short = q.length <= 24, energy = AI_RX.energy.test(q);
  if (short && AI_RX.thanks.test(q)) return 'thanks';
  if (short && AI_RX.bye.test(q)) return 'bye';
  if (short && AI_RX.greet.test(q) && !energy) return 'greet';
  if (AI_RX.help.test(q) && !energy) return 'help';
  if (AI_RX.b4.test(q) && AI_RX.cool.test(q) && AI_RX.down.test(q)) return 'b4';   // a fixed operating rule: no model needed
  if (AI_RX.cmd.test(q) && energy) return 'propose';
  if (AI_RX.advice.test(q) && (energy || AI.chat.length)) return 'propose';
  if (AI_RX.overview.test(q) && !AI_RX.subject.test(q)) return 'brief';
  return 'chat';
}
// built-in replies follow the language of the question, not the page ("What can you do?" on the Korean page)
const aiLangOf = (q) => (/[가-힣]/.test(q) ? 'ko' : /[A-Za-z]{2}/.test(q) ? 'en' : LANG);
function tl(key, lang, params) {
  const d = I18N[lang], s0 = d && d[key] != null ? String(d[key]) : null;
  return s0 == null ? t(key, params) : s0.replace(/\{(\w+)\}/g, (m, k) => (params && params[k] != null ? params[k] : m));
}
const aiRemember = (q, a) => { AI.chat.push({ role: 'user', content: q }, { role: 'assistant', content: a }); if (AI.chat.length > 12) AI.chat.splice(0, AI.chat.length - 12); };
function aiExamples(lang = LANG) {
  return `<div class="ai-ex"><span>${uiEsc(tl('ai.ex.title', lang))}</span>${tl('ai.ex.list', lang).split('|').map((q) => `<button type="button" data-ask="${uiEsc(q)}">${uiEsc(q)}</button>`).join('')}</div>`;
}
function aiCanned(text, kind) {                            // built-in reply: instant, no model call, labelled as such
  const lang = aiLangOf(text);
  aiBubble('user', `<p>${uiEsc(text)}</p>`);
  const reply = tl(kind === 'b4' ? 'ai.rule.b4' : 'ai.small.' + kind, lang);
  const el = aiBubble('bot', aiFmt(reply) + (kind === 'greet' || kind === 'help' ? aiExamples(lang) : ''));
  el.querySelector('.ai-foot').innerHTML = `<span class="ai-tag">${uiEsc(tl('ai.canned', lang))}</span>`;
  if (kind === 'b4' || kind === 'help') aiRemember(text, reply);
  aiScroll();
  return { task: 'canned:' + kind, text: reply };
}
// Requests that name their target and value ("B1 3층 온도 26도로 올려줘", "빈 방 불 꺼 줘", "B1-F5-R2 조명 켜") become
// cards without the model: the fine-tuned model answered "B1 3층 26도로" with its usual empty-room lights-off proposal.
// Vaguer requests ("에어컨 좀 약하게", "피크 줄이려면?") still go to the model as a proposal task.
function aiParseCommand(q) {
  const s = lastSnap; if (!s) return null;
  const ko = aiLangOf(q) === 'ko', f = aiFocus(q), acts = [];
  const num = /(\d{2}(?:\.\d)?)\s*(?:도|°\s*C|℃|degrees?\b)/i.exec(q);
  const temp = /(온도|설정|냉방|난방|에어컨|공조|temperature|setpoint|cooling|heating|\bAC\b)/i.test(q) || /(°|℃|\d\s*도\s*(로|까지|에))/.test(q);
  const light = /(불|조명|전등|라이트|light)/i.test(q), off = /(꺼|끄|소등|\boff\b)/i.test(q), on = !off && /(켜|점등|\bon\b)/i.test(q);
  // like the model's candidates: no data-centre (B4) rooms, cold rooms or server / electrical / mechanical rooms
  const zoneOf = (id) => id.split('-').slice(0, 2).join('-'), rooms = (s.rooms || []).filter((R) => R.name !== 'Cold room' && !R.id.startsWith('B4')
    && !['server', 'electrical', 'mechanical'].includes(((typeof INT_ROOM !== 'undefined' && INT_ROOM[R.id]) || {}).type || R.type));
  const lit = (R) => (R.lightLevel || 0) > 0.05, empty = (R) => !((R.people || 0) > 0);
  const roomName = (R) => { const meta = (typeof INT_ROOM !== 'undefined' && INT_ROOM[R.id]) || {}; return ko ? (meta.nameKo || R.nameKo || R.name) : (meta.name || R.name); };
  let summary = '';
  if (num && temp && (f.zones.size || f.rooms.size)) {
    const v = +num[1], cv = clamp(Math.round(v * 2) / 2, 22, 28);
    for (const id of f.rooms) { const R = rooms.find((x) => x.id === id); acts.push({ type: 'roomSetpoint', target: id, value: String(cv),
      expected_effect: R ? (ko ? `${roomName(R)} 설정 ${aiR(R.sp)} → ${cv} °C (지금 ${aiR(R.T)} °C)` : `${roomName(R)} setpoint ${aiR(R.sp)} → ${cv} °C (now ${aiR(R.T)} °C)`) : '' }); }
    for (const id of f.zones) if (![...f.rooms].some((r) => zoneOf(r) === id)) { const z = (s.zones || []).find((x) => x.id === id); acts.push({ type: 'setpoint', target: id, value: String(cv),
      expected_effect: z ? (ko ? `설정 ${aiR(z.sp)} → ${cv} °C (지금 ${aiR(z.T)} °C, 재실 ${aiR(100 * z.occ, 0)}%)` : `setpoint ${aiR(z.sp)} → ${cv} °C (now ${aiR(z.T)} °C, ${aiR(100 * z.occ, 0)} % occupied)`) : '' }); }
    summary = ko ? `요청하신 설정온도 변경입니다${cv !== v ? ` — ${v} °C는 허용 범위(22–28 °C) 밖이라 ${cv} °C로 맞췄습니다` : ''}.`
      : `Here is the requested setpoint change${cv !== v ? ` — ${v} °C is outside the allowed 22–28 °C, so it is set to ${cv} °C` : ''}.`;
  } else if (light && (off || on) && (f.rooms.size || f.zones.size || f.vacantLights)) {
    const pick = (f.rooms.size ? rooms.filter((R) => f.rooms.has(R.id))
      : rooms.filter((R) => (!f.zones.size || f.zones.has(zoneOf(R.id))) && (off ? lit(R) && empty(R) : !lit(R))))
      .sort((a, b) => (b.lightKW || 0) - (a.lightKW || 0)).slice(0, 6);
    if (!pick.length) return { summary: ko ? '요청에 맞는 방이 지금은 없습니다(조명이 켜진 빈 방 없음).' : 'No room matches the request right now (no empty room has its lights on).', actions: [] };
    for (const R of pick) acts.push({ type: 'roomLights', target: R.id, value: off ? 'off' : 'on',
      expected_effect: `${roomName(R)} · ${empty(R) ? (ko ? `${aiR(R.vacantMin, 0)}분째 빈 방` : `empty ${aiR(R.vacantMin, 0)} min`) : (ko ? `재실 ${R.people}명` : `${R.people} people`)} · ${ko ? '조명' : 'lights'} ${aiR(100 * (R.lightLevel || 0), 0)}%` });
    summary = ko ? `요청하신 조명 조치입니다: ${pick.length}개 방 ${off ? '소등' : '점등'}${!f.rooms.size && off ? '(사람이 있는 방은 제외)' : ''}.`
      : `Here is the requested lighting change: ${pick.length} room(s) ${off ? 'off' : 'on'}${!f.rooms.size && off ? ' (occupied rooms left alone)' : ''}.`;
  }
  if (!acts.length) return null;
  for (const a of acts) a.reason = ko ? '운영자 요청' : 'requested by the operator';
  return { summary, actions: acts };
}
function aiCommand(text, data) {                           // a request the page read itself: cards at once, no model call
  const lang = aiLangOf(text);
  aiBubble('user', `<p>${uiEsc(text)}</p>`);
  const el = aiBubble('bot', ''), body = el.querySelector('.ai-body');
  aiProposal(body, data);
  el.querySelector('.ai-foot').innerHTML = `<span class="ai-tag">${uiEsc(tl('ai.cmd.tag', lang))}</span>`;
  aiRemember(text, data.summary); aiScroll();
  return { task: 'command', text: data.summary, json: data, valid: data.actions.map((a) => aiValidate(a).ok) };
}
function aiSubmit(q) {
  const r = aiRoute(q);
  if (r === 'propose') { const cmd = aiParseCommand(q); if (cmd) return Promise.resolve(aiCommand(q, cmd)); }
  return r === 'chat' || r === 'propose' || r === 'brief' ? aiAsk(r, q) : Promise.resolve(aiCanned(q, r));
}
async function aiAsk(task, text) {
  if (AI.busy) return null;
  if (!AI.online) { await aiCheck(true); if (!AI.online) return null; }
  if (task === 'explain' && !selection.kind) { aiNote(t('ai.needSel')); return null; }
  const shown = text || (task === 'explain' ? t('ai.task.explain', { name: uiPick(selection.info || { kind: selection.kind, id: selection.id }).label }) : t('ai.task.' + task));
  aiBubble('user', `<p>${uiEsc(shown)}</p>`);
  const history = task === 'chat' ? AI.chat.slice(-6) : [];
  const sent = task === 'brief' && text ? tl('ai.task.brief', aiLangOf(text)) : shown;   // a routed overview question asks for the trained briefing
  const messages = history.concat([{ role: 'user', content: sent }]);
  const el = aiBubble('bot', `<p class="ai-wait">${uiEsc(t('ai.thinking'))}</p>`), body = el.querySelector('.ai-body'), foot = el.querySelector('.ai-foot');
  let text_ = '', meta = '', notes = [], final = null, err = '';
  AI.busy = true; aiEl('aiSend').textContent = t('ai.stop'); aiEl('aiForm').classList.add('busy');
  const tierName = (k) => t('ai.tier.name.' + k);
  try {
    await aiStream({ task, tier: AI.tier, messages, context: aiContext(task, text) }, (ev, d) => {
      if (ev === 'meta') { meta = d.tier === 'rule' ? t(d.model === 'lookup' ? 'ai.lookup' : 'ai.canned') : t(d.tier === 'local' ? 'ai.meta.local' : 'ai.meta.api', { m: d.model }); foot.innerHTML = `<span class="ai-tag ${d.tier}">${uiEsc(meta)}</span>`; }
      else if (ev === 'delta') { text_ += d.text; body.innerHTML = aiFmt(text_); aiScroll(); }
      else if (ev === 'escalate') { notes.push(t('ai.esc', { from: tierName(d.from), to: tierName(d.to), reason: d.reason })); if (d.reset) { text_ = ''; body.innerHTML = `<p class="ai-wait">${uiEsc(t('ai.thinking'))}</p>`; } }
      else if (ev === 'done') final = d;
      else if (ev === 'error') throw new Error(d.message);
    });
  } catch (e) {
    err = e.message || String(e);
    if (e.name !== 'AbortError') { body.innerHTML = `<p class="ai-errtxt">${uiEsc(t('ai.err', { m: e.message }))}</p>`; aiCheck(true); }
  } finally {
    AI.busy = false; AI.ctl = null; aiEl('aiSend').textContent = t('ai.send'); aiEl('aiForm').classList.remove('busy');
  }
  if (!final) { if (notes.length) foot.insertAdjacentHTML('beforeend', `<span class="ai-esc">${uiEsc(notes.join(' · '))}</span>`); return { task, error: err || 'no answer' }; }
  if (final.tier === 'rule') {                             // the gateway answered without the model: a timetable lookup, or a refusal
    const lk = final.model === 'lookup', lang = aiLangOf(shown);
    foot.innerHTML = `<span class="ai-tag">${uiEsc(tl(lk ? 'ai.lookup' : 'ai.canned', lang))}</span>` + (final.check && final.check.ok ? `<span class="ai-ok">✓ ${uiEsc(t('ai.check.ok'))}</span>` : '');
    body.innerHTML = aiFmt(final.text); aiRemember(shown, final.text); aiScroll();
    return { task: lk ? 'lookup' : 'rule', text: final.text, model: final.model, tier: 'rule', check: final.check };
  }
  const us = final.usage || {}, tok = (us.input_tokens || 0) + (us.output_tokens || 0) + (us.cache_read_tokens || 0) + (us.cache_write_tokens || 0);
  if (final.tier === 'api') {                              // $ per MTok: input, output, cache read; cache writes cost 1.25x input (5-min TTL)
    const P = AI_PRICE[final.model] || AI_PRICE['claude-opus-5-5']; AI.usage.api.calls++; AI.usage.api.tok += tok;
    AI.usage.api.usd += ((us.input_tokens || 0) * P[0] + (us.output_tokens || 0) * P[1] + (us.cache_read_tokens || 0) * P[2] + (us.cache_write_tokens || 0) * P[0] * 1.25) / 1e6;
  }
  else { AI.usage.local.calls++; AI.usage.local.tok += tok; }
  aiRenderUsage();
  const bits = [`<span class="ai-tag ai-badge">${uiEsc(t('ai.badge'))}</span>`, `<span class="ai-tag ${final.tier}">${uiEsc(t(final.tier === 'local' ? 'ai.meta.local' : 'ai.meta.api', { m: final.model }))}</span>`, `<span>${(final.latency_ms / 1000).toFixed(1)} s</span>`];
  if (final.usage && final.usage.cache_read_tokens) bits.push(`<span>${uiEsc(t('ai.cache', { n: final.usage.cache_read_tokens }))}</span>`);
  if (final.check) bits.push(final.check.ok ? `<span class="ai-ok">✓ ${uiEsc(t('ai.check.ok'))}</span>` : `<span class="ai-warn">⚠ ${uiEsc(t('ai.check.bad', { v: final.check.unmatched.join(', ') }))}</span>`);
  if (notes.length) bits.push(`<span class="ai-esc">${uiEsc(notes.join(' · '))}</span>`);
  foot.innerHTML = bits.join('');
  const result = { task, text: final.text || text_, json: final.json, check: final.check, model: final.model, tier: final.tier };
  if (task === 'propose') {
    aiProposal(body, final.json); aiScroll();
    const acts = (final.json && final.json.actions) || [];
    result.valid = acts.map((a) => aiValidate(a).ok);
    if (text && final.json) { AI.chat.push({ role: 'user', content: shown }, { role: 'assistant', content: final.json.summary || '' }); if (AI.chat.length > 12) AI.chat.splice(0, AI.chat.length - 12); }
    return result;
  }
  body.innerHTML = aiFmt(final.text || text_);
  if (task === 'chat' || task === 'brief' || task === 'explain') { AI.chat.push({ role: 'user', content: shown }, { role: 'assistant', content: final.text || text_ }); if (AI.chat.length > 12) AI.chat.splice(0, AI.chat.length - 12); }
  if (task === 'brief' && lastSnap) {
    const flat = (final.text || '').replace(/^\s*#{1,6}\s*/gm, '').replace(/\s*\n+\s*[-•*]?\s*/g, ' · ').replace(/\*\*/g, '').slice(0, 320), tier = tierName(final.tier);
    Bus.emit('log', { T: lastSnap.T, clock: aiHM(lastSnap.clock), agent: 'AI', text: t('ai.brief.log', { tier, text: flat }), kind: 'plan', tags: ['COORD'], model: lastSnap.mode });
  }
  aiScroll();
  return result;
}
aiEl('aiForm') && aiEl('aiForm').addEventListener('submit', (e) => {
  e.preventDefault();
  if (AI.busy) { if (AI.ctl) AI.ctl.abort(); return; }
  const inp = aiEl('aiInput'), q = inp.value.trim(); if (!q) return;
  inp.value = ''; aiSubmit(q);
});
aiEl('aiInput') && aiEl('aiInput').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); aiEl('aiForm').requestSubmit(); } });
aiEl('aiQuick') && aiEl('aiQuick').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-q]'); if (!b) return;
  if (b.dataset.q === 'peak') aiAsk('chat', t('ai.q.peak.text')); else aiAsk(b.dataset.q);
});
aiEl('aiMsgs') && aiEl('aiMsgs').addEventListener('click', (e) => {   // example-question buttons inside the messages
  const b = e.target.closest('button[data-ask]'); if (!b || AI.busy || !AI.online) return;
  aiSubmit(b.dataset.ask);
});

// ---------- proposals: validated, clamped, applied only on click ----------
function aiValidate(a) {
  const s = lastSnap || {}, type = a && a.type, tgt = String((a && a.target) || '').trim(), raw = String(a && a.value != null ? a.value : '').trim().toLowerCase();
  const bad = (why) => ({ ok: false, why: t('ai.why.' + why) });
  const room = (typeof INT_ROOM !== 'undefined' && INT_ROOM[tgt]) || (TOPO.rooms || []).find((r) => r.id === tgt);
  const hot = (id, r) => /^B4/.test(id) || (r && ['server', 'electrical', 'mechanical'].includes(r.type));
  const cold = (TOPO.rooms || []).some((r) => r.id === tgt && r.name === 'Cold room');
  if (cold && (type === 'roomSetpoint' || type === 'roomLights')) return bad('cold');
  if (type === 'setpoint') {
    if (!(s.zones || []).some((z) => z.id === tgt)) return bad('zone');
    if (hot(tgt)) return bad('b4');
    const v = parseFloat(raw); if (!Number.isFinite(v)) return bad('value');
    const val = clamp(Math.round(v * 2) / 2, 22, 28);
    return { ok: true, cmd: { type: 'setpoint', zone: tgt, value: val }, label: `${tgt} → ${val.toFixed(1)} °C` };
  }
  if (type === 'roomSetpoint') {
    if (!room) return bad('room'); if (hot(tgt, room)) return bad('b4');
    if (raw === 'null' || raw === 'auto') return { ok: true, cmd: { type: 'roomSetpoint', room: tgt, value: null }, label: `${tgt} → auto` };
    const v = parseFloat(raw); if (!Number.isFinite(v)) return bad('value');
    const val = clamp(Math.round(v * 2) / 2, 22, 28);
    return { ok: true, cmd: { type: 'roomSetpoint', room: tgt, value: val }, label: `${tgt} → ${val.toFixed(1)} °C` };
  }
  if (type === 'roomLights') {
    if (!room) return bad('room'); if (!['auto', 'on', 'off'].includes(raw)) return bad('value');
    return { ok: true, cmd: { type: 'roomLights', room: tgt, value: raw }, label: `${tgt} · ${t('int.lights.' + raw) || raw}` };
  }
  return bad('type');
}
// ---------- impact preview: what the next 60 minutes look like with and without a proposed action ----------
// createLocalSim() is a factory, so a second, private simulator (own bus, own models) can be built. It is brought to the
// live clock by replaying from the start of the run, including every operator command logged below, then branched: one
// copy gets the action, one does not, and both run 60 more simulated minutes. The live Sim is never touched. Before the
// numbers are shown the replay is checked against the live state (grid import and cost, both controllers); if they
// disagree the preview says so instead of guessing. Coordinator v2 (the default) reads a net-load forecast (NET_FC) that
// lives outside the simulator and is fed by the live bus; the private replay builds its own forecaster from T=0 on its
// own bus and points NET_FC at it only for the duration of each synchronous Sim call, so the live forecaster (FC / FCN)
// is never read or written by the preview. Not supported (stated in the card): ?faultImpact=1, whose sensor state lives
// outside the simulator, and an external dataset loaded mid-run (simData is shared).
i18nAdd({
  en: { 'ai.pv.title': 'Next 60 min, simulated', 'ai.pv.wait': 'Simulating the next 60 minutes…', 'ai.pv.with': 'with action', 'ai.pv.without': 'without', 'ai.pv.cost': 'Cost', 'ai.pv.peak': 'Peak import',
    'ai.pv.comfort': 'Comfort', 'ai.pv.note': 'Re-simulated from the current state with the agents in control; operator actions so far are replayed.',
    'ai.pv.off.fault': 'not available with ?faultImpact=1', 'ai.pv.off.data': 'not available after an external dataset was loaded mid-run',
    'ai.pv.off.drift': 'the replay does not match the live run, so no preview', 'ai.pv.off.err': 'could not simulate ({m})', 'ai.pv.none': 'no visible effect' },
  ko: { 'ai.pv.title': '앞으로 60분 예측', 'ai.pv.wait': '앞으로 60분을 시뮬레이션하는 중…', 'ai.pv.with': '적용 시', 'ai.pv.without': '미적용', 'ai.pv.cost': '비용', 'ai.pv.peak': '최대 수전',
    'ai.pv.comfort': '쾌적', 'ai.pv.note': '현재 상태에서 에이전트 제어로 다시 시뮬레이션한 값입니다. 지금까지의 운영자 조작은 그대로 재현합니다.',
    'ai.pv.off.fault': '?faultImpact=1 에서는 쓸 수 없음', 'ai.pv.off.data': '실행 중에 외부 데이터셋을 불러오면 쓸 수 없음',
    'ai.pv.off.drift': '재현 결과가 실제 실행과 달라 예측하지 않음', 'ai.pv.off.err': '시뮬레이션 실패({m})', 'ai.pv.none': '눈에 띄는 변화 없음' },
});
const PV = { cmds: [], t0: Math.round(clamp(+(new URLSearchParams(location.search).get('t') || 10), 0.5, 23.9) * 60), dataset: false, q: Promise.resolve(), cache: new Map() };
{
  const _cmd = Sim.command;
  Sim.command = function (c) {
    if (c && c.type === 'dataset') PV.dataset = true;
    else if (c && ['dr', 'setpoint', 'roomSetpoint', 'roomLights'].includes(c.type)) PV.cmds.push({ T: lastSnap ? lastSnap.T : PV.t0, c: JSON.parse(JSON.stringify(c)) });
    return _cmd.apply(this, arguments);
  };
}
const pvYield = () => new Promise((r) => setTimeout(r, 0));
async function pvSim(cmds, tNow, action) {            // → { at: snapshot at tNow, ticks: the next 60 minutes }
  const bus = createBus(), sim = createLocalSim(bus); let snap = null;
  // coordinator v2: a private net-load forecaster, fed by the private bus (like fcRecord on the live bus). NET_FC points at
  // it only while a Sim call runs; the calls are synchronous, so the live simulator can never see it, and the live
  // forecaster is left exactly as it was.
  const pf = COORD_V2 ? fcMake((s) => s.load - s.pv) : null, liveFc = NET_FC;
  const priv = (fn) => { if (!pf) return fn(); NET_FC = () => pf.out; try { return fn(); } finally { NET_FC = liveFc; } };
  bus.on('tick', (s) => { snap = s; if (pf) pf.record(s); });
  priv(() => sim.start(PV.t0));
  const run = async (to) => {                          // n minutes per update: speed 4n at dt 0.25 is exactly n steps
    // (v2: one minute per update, because a tick is emitted per update and the forecaster averages minute readings into
    // 15-min slots, as the live run does at its 1-minute steps)
    while (snap.T < to) { const n = pf ? 1 : Math.min(60, to - snap.T); priv(() => { sim.command({ type: 'speed', value: 4 * n }); sim.update(0.25); }); if (snap.T % 240 === 0) await pvYield(); }
  };
  for (const k of cmds) { await run(k.T); priv(() => sim.command(k.c)); }
  await run(tNow); await pvYield();
  const at = snap, ticks = [];
  priv(() => {
    if (action) sim.command(action);
    sim.command({ type: 'speed', value: 4 });
    for (let i = 0; i < 60; i++) { sim.update(0.25); ticks.push(snap); }
  });
  return { at, ticks };
}
function pvStats(at, ticks) {
  let cost = 0, prev = at.cost, peak = 0, ok = 0, n = 0;
  for (const s of ticks) { cost += Math.max(0, s.cost - prev); prev = s.cost; peak = Math.max(peak, s.grid); if (s.counted > 0) { ok += s.inBand / s.counted; n++; } }
  return { cost, peak, comfort: n ? 100 * ok / n : null };
}
const pvOff = (why, m) => ({ off: t('ai.pv.off.' + why, { m }) });
function pvPreview(cmd) {
  const live = lastSnap;
  if (!live) return Promise.resolve(pvOff('err', 'no data'));
  const ck = JSON.stringify(cmd) + '@' + live.T;
  if (PV.cache.has(ck)) return PV.cache.get(ck);
  if (typeof FAULT_IMPACT !== 'undefined' && FAULT_IMPACT) return Promise.resolve(pvOff('fault'));
  if (PV.dataset) return Promise.resolve(pvOff('data'));
  const tNow = live.T, cmds = PV.cmds.filter((k) => k.T <= tNow), ref = { g: live.gridAgent, b: live.gridBase, c: live.costAgent };
  const p = (PV.q = PV.q.then(async () => {
    try {
      const A = await pvSim(cmds, tNow, null);
      const near = (x, y) => Math.abs(x - y) <= 0.005 * Math.max(1, Math.abs(y));
      if (!near(A.at.gridAgent, ref.g) || !near(A.at.gridBase, ref.b) || !near(A.at.costAgent, ref.c)) return pvOff('drift');
      const B = await pvSim(cmds, tNow, cmd);
      return { without: pvStats(A.at, A.ticks), with: pvStats(B.at, B.ticks), cur: A.at.currency };
    } catch (e) { return pvOff('err', e && e.message ? e.message : String(e)); }
  }));
  PV.cache.set(ck, p);
  return p;
}
function pvRender(el, r) {
  if (r.off) { el.innerHTML = `<small class="ai-dim">${uiEsc(t('ai.pv.title'))}: ${uiEsc(r.off)}</small>`; return; }
  const W = r.without, X = r.with, cur = r.cur === '₩' ? '₩' : r.cur || '$', d0 = cur === '₩' ? 0 : 2;
  const money = (v) => cur + fmt(v, d0), sgn = (v, d, u, pre = '') => (v > 0 ? '+' : v < 0 ? '−' : '±') + pre + fmt(Math.abs(v), d) + u;
  const row = (lab, a, b, txt, delta) => `<tr><td>${uiEsc(lab)}</td><td>${txt(a)}</td><td>${txt(b)}</td><td>${delta}</td></tr>`;
  const dc = X.cost - W.cost, dp = X.peak - W.peak, dq = X.comfort != null && W.comfort != null ? X.comfort - W.comfort : null;
  const same = Math.abs(dc) < (cur === '₩' ? 0.5 : 0.005) && Math.abs(dp) < 0.5 && (dq === null || Math.abs(dq) < 0.05);
  el.innerHTML = `<div class="ai-pv"><div class="ai-pv-h">${uiEsc(t('ai.pv.title'))}${same ? ` · ${uiEsc(t('ai.pv.none'))}` : ''}</div><table><thead><tr><th></th><th>${uiEsc(t('ai.pv.without'))}</th><th>${uiEsc(t('ai.pv.with'))}</th><th>Δ</th></tr></thead><tbody>`
    + row(t('ai.pv.cost'), W.cost, X.cost, money, sgn(dc, d0, '', cur))
    + row(t('ai.pv.peak'), W.peak, X.peak, (v) => fmt(v, 0) + ' kW', sgn(dp, 0, ' kW'))
    + (dq === null ? '' : row(t('ai.pv.comfort'), W.comfort, X.comfort, (v) => fmt(v, 1) + '%', sgn(dq, 1, ' pp')))
    + `</tbody></table><small class="ai-dim">${uiEsc(t('ai.pv.note'))}</small></div>`;
}
function aiProposal(body, data) {
  if (!data) { body.innerHTML = `<p class="ai-errtxt">${uiEsc(t('ai.err', { m: 'no JSON' }))}</p>`; return; }
  const acts = (data.actions || []).slice(0, 4);
  let html = `<p>${uiEsc(data.summary || '')}</p>`;
  if (!acts.length) html += `<p class="ai-dim">${uiEsc(t('ai.prop.none'))}</p>`;
  html += `<div class="ai-props">${acts.map((a, i) => {
    const v = aiValidate(a);
    return `<div class="ai-prop ${v.ok ? '' : 'bad'}"><div class="ai-prop-h"><b>${uiEsc(v.ok ? v.label : `${a.type || '?'} ${a.target || ''} ${a.value || ''}`)}</b>${v.ok ? `<button type="button" class="btn" data-i="${i}">${uiEsc(t('ai.prop.apply'))}</button>` : ''}</div>
      <small>${uiEsc(a.expected_effect || '')}</small><small class="ai-dim">${uiEsc(a.reason || '')}</small>${v.ok ? '' : `<small class="ai-warn">${uiEsc(t('ai.prop.skip', { why: v.why }))}</small>`}</div>`;
  }).join('')}</div>${acts.length ? `<small class="ai-dim">${uiEsc(t('ai.prop.note'))}</small>` : ''}`;
  body.innerHTML = html;
  body.querySelectorAll('.ai-prop').forEach((card, i) => {            // impact preview under each applicable action
    const v = acts[i] && aiValidate(acts[i]); if (!v || !v.ok) return;
    const el = document.createElement('div'); el.className = 'ai-pv-slot'; el.innerHTML = `<small class="ai-dim">${uiEsc(t('ai.pv.wait'))}</small>`;
    card.appendChild(el);
    pvPreview(v.cmd).then((r) => pvRender(el, r));
  });
  body.querySelectorAll('.ai-prop button[data-i]').forEach((btn) => btn.addEventListener('click', () => {
    const v = aiValidate(acts[+btn.dataset.i]); if (!v.ok) return;
    Sim.command(v.cmd); btn.disabled = true; btn.textContent = t('ai.prop.applied'); btn.classList.add('on');
    toast(t('ai.prop.toast', { what: v.label }), 'var(--violet)');
  }));
}
onLang(() => { aiTierOptions(); aiRenderStatus(); aiRenderUsage(); applyI18n(document.getElementById('side')); });
aiRenderUsage();
aiSetTab('info');
// evaluation hook: the exact context the panel sends, the session's token counters, and the typed-question path
// (ask = what pressing Send does, with an optional tier; ft/scripts/eval_realq_page.mjs drives it)
setTimeout(() => {
  if (window.MA_BEMS) window.MA_BEMS.ai = { context: aiContext, usage: () => JSON.parse(JSON.stringify(AI.usage)), price: AI_PRICE, route: aiRoute,
    preview: (cmd) => pvPreview(cmd), previewLog: () => PV.cmds.slice(),
    ask: (q, opts) => { if (opts && opts.tier) AI.tier = opts.tier; return aiSubmit(q); }, reset: () => { AI.chat = []; },
    online: async () => { await aiCheck(true); return AI.online; } };
}, 0);
