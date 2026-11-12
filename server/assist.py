"""Question handling around the local model: a small glossary, follow-up rewriting and output guards.

Written after asking the fine-tuned Qwen3-8B (v2.1) 66 questions visitors are likely to type (ft/data/realq.json).
It answers the 18 kinds of question it was trained on well, but pushes everything else into the nearest trained
template: "DR이 뭐야?" got the DR status, "절감률은 어떻게 계산해?" got today's cost, "고마워!" got the cost summary.
Given one or two sentences of grounding in the context it uses them (DR, ESS, savings method, scenario playbooks:
probe on 2026-11-10), so concept questions get the matching glossary entries added to campus_state. The guards cover
the other failures seen: a repetition loop that ran to the token cap, the system prompt printed on request, and the
"…에 대해서는 지어내지 않겠습니다" line that echoes the question back.
"""
import json
import re

# term (regex on the question) -> (Korean, English). Facts come from the simulator (TOPO, SCN_INFO, the FDD rules)
# and from KEPCO's general-service tariff; keep them in step with index.html.
GLOSSARY = [
    # what-if first: v2.1 answered "설정온도 1도 올리면 얼마나 절약돼?" with an invented "10 %, 18.9 kW"
    (r'(올리|내리|낮추|높이|바꾸|줄이|끄|켜|소등하|조절하|조정하)면|(온도|설정\s?온도|설정값|조명|소등|불|냉방|냉난방).{0,20}(영향|효과|기여|아끼는|절약되는|줄어드는)|what\s+if|if\s+(we|i|you)\s+(raise|lower|change|turn)',
     '설정 변경 효과: 설정온도를 1 °C 바꿀 때 줄어드는 전력은 건물·날씨·재실에 따라 달라 지금 데이터만으로는 계산할 수 없습니다. 제어 제안으로 설정을 바꾸면 대시보드가 같은 조건의 룰 기반 BMS와 나란히 시뮬레이션해 실제 차이(kW, 비용)를 보여 줍니다.',
     'Effect of a change: how much a 1 °C setpoint change saves depends on the building, weather and occupancy, so it cannot be computed from this data alone. Apply it as a control proposal and the dashboard simulates it next to the rule-based BMS under the same conditions, showing the real difference in kW and cost.'),
    (r'(?<![A-Za-z])DR(?![A-Za-z])|수요\s?반응|전력\s?수요를?\s?(줄|낮)|감축\s?(요청|신호)|demand\s+response',
     'DR(수요반응): 전력 수급이 빠듯할 때 전력회사가 정해진 시간 동안 사용량을 줄여 달라고 요청하는 제도로, 줄인 만큼 보상을 받습니다. 이 캠퍼스는 OpenADR 신호를 받으면 코디네이터가 감축량을 ESS → EV → 조명 → HVAC 순서로 나누고, 룰 기반 BMS는 신호를 받아도 자동 대응이 없습니다.',
     'DR (demand response): when supply is tight the utility asks customers to cut their load for a set time and pays for the cut. Here an OpenADR signal makes the coordinator split the cut in the order battery → EV → lighting → HVAC; the rule-based BMS has no automatic response.'),
    (r'(?<![A-Za-z])ESS(?![A-Za-z])|배터리|에너지\s?저장|방전|충·방전|충방전|충전\s?(시점|전략|규칙)|battery|storage',
     'ESS(에너지저장장치): 이 캠퍼스의 대형 배터리(용량 1,200 kWh, 최대 300 kW)입니다. 단가가 싼 밤에 충전하고, 비싼 최대부하 시간이나 수전이 한도의 92%를 넘을 때 방전해 요금과 피크를 줄입니다. 잔량(SOC)이 8%까지 내려가면 방전을 멈춥니다.',
     'ESS (energy storage system): the campus battery, 1,200 kWh and 300 kW. It charges at night when energy is cheap and discharges in the expensive peak period or when grid import passes 92 % of the limit, cutting both cost and the peak. It stops discharging at 8 % state of charge.'),
    (r'피크\s?한도|한도|피크\s?(관리|제한|억제)|계약\s?전력|최대\s?수요|기본\s?요금|수요\s?요금|peak\s+limit|demand\s+charge',
     '피크 한도: 계약한 최대 수전 전력(kW)입니다. 한전 일반용 요금의 기본요금은 최대수요전력(15분 평균 kW)으로 매겨져, 한 번 높게 찍힌 피크가 이후 최대 1년 동안 기본요금을 올릴 수 있고, 계약전력을 넘으면 초과 사용 부가금이 붙을 수 있습니다. 그래서 코디네이터는 예측 수전이 한도의 94%를 넘지 않게 미리 조정합니다.',
     'Peak limit: the contracted maximum grid import (kW). KEPCO bills the demand charge on the highest 15-minute demand, so one high peak can raise the demand charge for up to a year, and exceeding the contract can add a surcharge. The coordinator therefore keeps forecast import under 94 % of the limit.'),
    (r'절감|절약|아꼈|기준선|룰\s?기반|(?<![A-Za-z])BMS(?![A-Za-z])|비교하|대조|saving|baseline|rule-based',
     '절감률 계산: 같은 날씨·재실·EV 조건으로 룰 기반 BMS(시간표와 고정 설정으로 움직이는 기존 방식)를 동시에 시뮬레이션하고, 그 비용 대비 멀티에이전트 운영 비용이 몇 % 적은지로 계산합니다. 시뮬레이션 기반 수치입니다.',
     'How savings are computed: the rule-based BMS (timetables and fixed setpoints) is simulated alongside under the same weather, occupancy and EVs, and the saving is how much lower the multi-agent cost is than that baseline. These are simulated figures.'),
    (r'협상|코디네이터|에이전트|중재|negotiat|coordinator|agent',
     '에이전트 협상: 6개 에이전트(코디네이터·HVAC·조명·태양광·ESS·EV)가 15분마다 관찰→계획→협상→실행→검증을 반복합니다. 각 에이전트가 계획(예상 kW 변화)을 내면 코디네이터가 예측 수전이 한도의 94% 안에 드는지 보고 승인하거나, 넘치면 줄이도록 되돌려 보냅니다. 평소 한도에서는 협상이 추가 절감을 만들지 않고, 한도가 빠듯할 때 효과가 납니다.',
     'Agent negotiation: six agents (coordinator, HVAC, lighting, PV, battery, EV) repeat observe → plan → negotiate → act → verify every 15 minutes. Each submits a plan (expected kW change); the coordinator approves it if forecast import stays within 94 % of the limit, or sends it back to be cut. With the normal limit negotiation adds no saving; it pays off when the limit is tight.'),
    (r'요금\s?구간|요금제|요금\s?(체계|제도|시간대)|시간대\s?별|계시별|최대부하|중간부하|경부하|오프\s?피크|피크\s?(시간대\s?)?요금|(?<![A-Za-z])TOU(?![A-Za-z])|time[- ]of[- ]use|tariff',
     '계시별 요금(TOU): 시간대마다 kWh 단가가 다릅니다. 이 캠퍼스는 최대부하·중간부하·경부하 세 구간을 씁니다.',
     'Time-of-use tariff: the price per kWh depends on the hour. This campus has three periods: peak, mid-peak and off-peak.'),
    (r'셋백|setback|사전\s?냉방|미리\s?(냉방|식)|pre-?cool|완화',
     '셋백·사전 냉방: 빈 방은 설정온도를 완화(여름엔 높임)해 공조 에너지를 줄이고(셋백), 최대부하 1시간 전에는 재실 구역을 1 °C 미리 식혀 두었다가 최대부하 중에 1 °C 완화해 비싼 시간의 냉방 전력을 줄입니다.',
     'Setback and pre-cooling: empty rooms get a relaxed setpoint (higher in summer) to save HVAC energy, and occupied zones are pre-cooled by 1 °C in the hour before the peak period and relaxed by 1 °C during it.'),
    (r'고장|센서|(?<![A-Za-z])FDD(?![A-Za-z])|가상\s?센서|고착|드리프트|끊김|stuck|drift|dropout|fault|sensor',
     '고장 감지(FDD): 5분마다 온도 센서를 읽어 45분 동안 값이 전혀 안 변하면 고착, 15분 동안 값이 없으면 끊김, 이웃 방과 평소 추종 오차 양쪽에서 15분 넘게 1.6 °C 이상 벗어나면 드리프트로 판단합니다. 운영자가 경보를 승인하면 그 방은 가상 센서(설정온도 + 이웃 방들의 추종 오차)로 제어됩니다.',
     'Fault detection (FDD): every 5 minutes the room sensors are read; no change for 45 minutes is a stuck sensor, 15 minutes without data is a dropout, and a reading more than 1.6 °C off both its neighbours and its own normal tracking for 15 minutes is drift. When the operator approves the alarm, the room is controlled from a virtual sensor (setpoint plus the neighbours\' tracking error).'),
    (r'운영\s?(규칙|원칙|방침)|우선\s?순위|원칙|규칙|(뭘|무엇을)\s?우선|우선(해|시)|대응\s?순서|operating\s+rules?|priorit',
     '운영 우선순위: 1) 피크 한도 초과 방지 2) 재실 구역 쾌적(설정온도 ±1.5 °C) 3) 비용·탄소. 데이터센터(B4)와 서버실·전기실 냉방은 줄이지 않고, AI 비서의 제어 제안은 운영자가 적용을 눌러야 실행됩니다.',
     'Operating priorities: 1) stay under the peak limit 2) keep occupied zones within ±1.5 °C of setpoint 3) cost and carbon. Cooling for the data centre (B4) and server and electrical rooms is never cut, and the assistant\'s control proposals run only when the operator presses Apply.'),
    (r'자가\s?소비|self[- ]consum',
     '자가소비율: 태양광 발전량 가운데 캠퍼스에서 바로 쓴 비율입니다.',
     'Self-consumption: the share of solar generation used on campus.'),
    (r'수전|계통|grid\s+import',
     '수전: 한전 계통에서 받아 오는 전력(kW)으로, 캠퍼스 부하에서 태양광 발전과 ESS 방전을 뺀 값입니다. 피크 한도와 요금은 수전 기준입니다.',
     'Grid import: power drawn from the utility (kW), i.e. campus load minus solar and battery discharge. The peak limit and the bill are based on it.'),
    (r'쾌적|comfort',
     '쾌적 범위: 재실 구역 온도가 설정온도 ±1.5 °C 안이면 쾌적으로 봅니다. 쾌적도(%)는 재실 구역이 이 범위 안에 있었던 비율입니다.',
     'Comfort band: an occupied zone is comfortable within ±1.5 °C of its setpoint; the comfort figure is the share of occupied zones inside that band.'),
    (r'예측|정확도|forecast|accuracy|(?<![A-Za-z])MAPE(?![A-Za-z])|CV\s?\(?RMSE',
     '수요 예측: 미래 날씨를 쓰지 않는 릿지 회귀로 4시간 앞 수전을 15분 단위로 예측하고, 90% 오차 범위를 함께 냅니다. 입력은 어제 관측한 날씨 곡선과 오늘의 차이, 재실 시간표, 어제 같은 시각과 직전 시각의 값이며 슬롯마다 다시 학습합니다. 정확도는 ASHRAE Guideline 14 방식(CV(RMSE), NMBE)으로 매깁니다. 그 가이드라인의 시간 단위 기준(CV(RMSE) 30% 이하, NMBE ±10% 이내)은 에너지 모델 보정용이라 예측이 "기준을 만족한다"는 근거가 아니라 비교용 숫자입니다.',
     'Load forecast: a ridge regression that never uses future weather predicts grid import 4 hours ahead in 15-minute steps with a 90 % band. Its inputs are yesterday\'s observed weather curve plus today\'s offset from it, the occupancy timetable, and the values of the same slot yesterday and the last observed slot; it is refitted every slot. Accuracy is scored like ASHRAE Guideline 14 (CV(RMSE), NMBE). That guideline\'s hourly criteria (CV(RMSE) at most 30 %, NMBE within ±10 %) are for calibrating energy models, so they are a point of comparison, not proof that the forecast "meets a standard".'),
    (r'MA-?BEMS|이 시스템|시스템\s?(구조|원리)|멀티\s?에이전트|AI\s?비서|통합\s?(해\s?)?관리|multi-?agent|this system',
     'MA-BEMS: 건물 에너지 관리(BEMS)를 6개 전문 에이전트로 나눠 각자 담당 설비를 계획하고, 코디네이터가 피크 한도 안에서 조율하는 구조입니다. 같은 조건의 룰 기반 BMS와 나란히 시뮬레이션해 효과를 비교하고, AI 비서는 그 데이터를 읽어 답하거나 운영자가 승인할 조치를 제안합니다.',
     'MA-BEMS: building energy management split into six specialist agents, each planning its own equipment, with a coordinator keeping the campus under the peak limit. A rule-based BMS runs alongside under the same conditions for comparison, and the AI assistant reads that data to answer questions or draft actions for the operator to approve.'),
    # scenario playbooks (SCN_INFO in the page): "what if it gets hot" etc.
    (r'폭염|더위|더우면|더워지|heat\s?wave|hot day',
     '폭염 대응: 냉방 부하로 수전이 한도에 다가가면 ESS가 한도 92%를 넘는 부분을 방전으로 깎고, HVAC는 사전 냉방·완화를 하되 이미 1.3 °C 넘게 더운 방이 있는 건물은 완화폭을 0.4 °C로 줄이며, 코디네이터는 예측 수전이 한도 94%를 넘으면 사전 냉방을 줄입니다.',
     'Heatwave playbook: as cooling pushes import toward the limit the battery shaves what goes above 92 % of it; HVAC keeps pre-cooling and relaxing but cuts the relaxation to 0.4 °C in buildings with rooms already 1.3 °C warm; the coordinator trims pre-cooling when forecast import would pass 94 %.'),
    (r'흐리|흐린|흐림|흐려|구름|비 ?오|비\s?(올|가\s?오)|cloud|overcast|rain',
     '흐린 날 대응: 태양광 에이전트가 지금의 맑음 지수로 1시간 앞 발전을 예측해 낮춰 잡고, 낮 수전이 늘어 ESS가 피크 깎기에 더 많이 쓰며, 주광이 줄어 조명 절감 여지도 작아집니다.',
     'Overcast playbook: the PV agent lowers its one-hour forecast from the clear-sky index it sees, more daytime import means the battery spends more charge on peak shaving, and daylight harvesting saves less lighting energy.'),
    (r'(EV|전기차|충전).{0,12}(몰|많이|붐|혼잡|폭주|집중|rush)|(몰리는|몰릴)\s?충전|충전\s?(혼잡|대기|폭주)|퇴근',
     'EV 몰림 대응: EV 에이전트가 최대부하(19시까지)와 수전이 한도 90%를 넘는 동안 출차 시각을 지키는 최소 전력으로 충전을 미룹니다. 룰 기반 BMS는 꽂자마자 최대 출력(22 kW)으로 충전하고, 충전기는 6기라 자리가 비는 대로 연결됩니다.',
     'EV rush playbook: during the peak period (to 19 h) and while import is above 90 % of the limit the EV agent charges each car at the minimum that still meets its departure; the rule-based BMS charges at full power (22 kW) on plug-in, and with 6 chargers later cars wait for a free one.'),
    (r'휴일|방학|주말|쉬는\s?날|공휴일|연휴|holiday|weekend|break',
     '휴일·방학 대응: 실별 재실 감지로 빈 방은 셋백·소등·대기전력 차단을 하고, 계속 비어 있을 건물은 미리 공조하지 않습니다. 룰 기반 BMS는 평일 시간표대로 공조·조명을 켭니다.',
     'Holiday playbook: room-level presence puts empty rooms into setback with lights and plug loads off, and buildings that will stay mostly empty are not pre-conditioned; the rule-based BMS follows the weekday timetable.'),
]
GLOSSARY = [(re.compile(rx, re.I), ko, en) for rx, ko, en in GLOSSARY]

# a question about meaning, method or behaviour (not a reading of the current value)
CONCEPT = re.compile(
    r'뭐야|뭔가요|뭐예요|뭐에요|뭔데|무엇(인|이|을)|뜻|의미|개념|이란|란\s?(뭐|무엇)|원리|방식|어떻게\s?(계산|작동|동작|돌아|대응|결정|정해|협상|해|하|돼|되|운영|판단|감지|예측)|'
    r'어떤\s?식|왜\s?(중요|필요|하는|해)|설명해|무슨\s?(뜻|의미|역할)|차이|달라|다른\s?점|역할|넘으면|오면|되면|하면\s?(어떻게|뭐가)|'
    r'(올리|내리|낮추|높이|바꾸|줄이|끄|켜)면\s?.{0,12}(얼마|절약|절감|줄어|아껴|어떻게|효과)|'
    r'what\s+(is|are|does|happens)|how\s+(does|do|is|are)|explain|meaning|difference|why\s+(is|does|do)|what\s+if', re.I)


# Glossary attachment uses a wider test than CONCEPT: on ~420 model-written concept questions (ft/data/v22, train split;
# the 66 visitor questions were not used) CONCEPT recognised only about half ("왜 사전 냉방을 해?", "쾌적도는 어떻게 구해?",
# "피크 한도라는 말을 쉽게 풀어 주세요"), so the matching entry was attached for 40 %. CONCEPT itself stays as it was: it
# also decides whether answer_facts treats "…넘으면" as hypothetical, which these additions must not change.
CONCEPT_GLOSS = re.compile(CONCEPT.pattern + '|' +
    r'왜|이유|까닭|근거|원칙|방법|메커니즘|매커니즘|로직|구조|흐름|절차|전략|정의|용어|헷갈|(이)?라는\s?(말|뜻|용어)|뭐라고\s?(해|하|불러|부르)|'
    r'풀어\s?(줘|주세요|주시|설명)|어떻게\s?\S{0,4}(나와|나오|세우|세워|재|구해|구하|정의|식별|탐지|구분|분산|처리|관리|평가|검증|학습|이루어|'
    r'연동|바뀌|바꾸|제어|조정|협력|이해|반응|완화|구성|움직|정하|활용|쓰)|(무슨|어떤|뭘|무엇을?)\s?(기준|원리|원칙|방식|근거|데이터|지표|영향|효과|'
    r'조치|설비)|기준(은|이)\s?(뭐|무엇|어떻게)|기준은\s*[?？]?\s*$|우선(해|시|순위|으로)|누가\s?정|상관\s?관계|미치는\s?영향|언제\s?(충전|방전|작동|켜|꺼|시작)|'
    r'\bwhy\b|how\s+(exactly|do\s+you|does\s+it|is\s+it)|when\s+(does|do|is|should)|what\s+(triggers|determines|do\s+they\s+ask)|rundown|break\s+(it\s+)?down|'
    r'summari[sz]e|describe|\brole\b|calculat|comput|deriv|account\s+for', re.I)


def glossary_for(question, max_items=3):
    """Glossary entries for a concept question, in the question's language, or {} for a reading of a value."""
    q = question or ''
    if not CONCEPT_GLOSS.search(q):
        return {}
    ko = bool(re.search(r'[가-힣]', q))
    out = {}
    for rx, k, e in GLOSSARY:
        if rx.search(q):
            text = k if ko else e
            out[text.split(':', 1)[0]] = text.split(':', 1)[1].strip()
            if len(out) >= max_items:
                break
    return out


# ---------- answer facts: the one or two records a question asks about, pulled out of campus_state ----------
# The fine-tuned model answers trained question types from a template even when the context has the answer: with the
# full tariff schedule in campus_state it still answered "제일 싼 시간은?" with the most expensive period. A short
# answerFacts list naming exactly the record asked for is copied the way glossary sentences are.
_BLD = [(re.compile(r'오피스|타워|본관|office', re.I), 'B1'), (re.compile(r'연구동|\blab\b|research', re.I), 'B2'),
        (re.compile(r'기숙사|dorm', re.I), 'B3'), (re.compile(r'데이터\s?센터|data\s?cent', re.I), 'B4')]


def _floors_named(q):
    ids = ['B%s-F%d' % (m.group(1), int(m.group(2))) for m in re.finditer(r'B([1-4])\s*-?\s*F\s*(\d{1,2})', q, re.I)]
    blds = {('B' + m.group(1)) for m in re.finditer(r'(?<![A-Za-z])B([1-4])(?![-\d])', q)} | {b for rx, b in _BLD if rx.search(q)}
    fl = re.search(r'(\d{1,2})\s*(층|floor|F\b)', q, re.I) or re.search(r'(?:floor|F)\s*(\d{1,2})', q, re.I)
    if fl:
        ids += ['%s-F%d' % (b, int(fl.group(1))) for b in sorted(blds)]
    return ids


def answer_facts(question, ctx):
    """Short sentences with the records the question names (tariff extremes, period end, time of today's peak, a floor,
    the hottest/coldest floor, empty rooms with lights on, EV chargers, the scenario). [] when nothing specific."""
    q, out = question or '', []
    ko = bool(re.search(r'[가-힣]', q))
    tf, today = ctx.get('tariff') or {}, ctx.get('today') or {}
    sched, cur = tf.get('schedule') or [], tf.get('currency') or ''
    price = lambda r: ('%s%s/kWh' % (cur, r['pricePerKWh']) if cur in ('$', '₩') else '%s %s/kWh' % (r['pricePerKWh'], cur)) if r.get('pricePerKWh') is not None else ''   # noqa: E731
    timeq = re.search(r'시간|때|언제|구간|시각|when|time|hour|period', q, re.I)
    cheap, dear = re.search(r'(?<!비)싸|(?<!비)싼|저렴|cheap|lowest', q, re.I), re.search(r'비싸|비싼|비쌈|expensive|highest price|most costly', q, re.I)
    if sched and timeq and cheap:
        r = sched[-1]
        out.append(('가장 싼 시간대는 %s %s(%s)입니다' if ko else 'The cheapest period is %s, %s (%s)') % (r['tier'], r['hours'], price(r)))
    if sched and timeq and dear:
        r = sched[0]
        out.append(('가장 비싼 시간대는 %s %s(%s)입니다' if ko else 'The most expensive period is %s, %s (%s)') % (r['tier'], r['hours'], price(r)))
    if sched and timeq and (cheap or dear) and isinstance(tf.get('tier'), dict):
        # with the schedule in view v2.1 once wrote "지금은 중간부하 19:00-22:00" at 14:36: say which period is current
        now = next((r for r in sched if r.get('tier') == tf['tier'].get('name')), None)
        if now:
            out.append(('지금(%s)은 %s 구간(%s)입니다' if ko else 'Now (%s) is the %s period (%s)') % (ctx.get('clock'), now['tier'], price(now)))
    nc = tf.get('nextChange') or {}
    if nc and re.search(r'끝나|끝날|바뀌|언제까지|다음\s?(요금|구간)|until|end|next|change', q, re.I) and re.search(r'요금|구간|시간|피크|비싼|싼|tariff|price|period|peak', q, re.I):
        tier = (tf.get('tier') or {}).get('name') if isinstance(tf.get('tier'), dict) else tf.get('tier')
        out.append(('지금 구간(%s)은 %s에 끝나고 %s%s 바뀝니다(%s분 뒤)' % (tier, nc.get('at'), nc.get('to'), _ro(nc.get('to')), nc.get('inMin'))) if ko else
                   'The current period (%s) ends at %s and changes to %s (in %s min)' % (tier, nc.get('at'), nc.get('to'), nc.get('inMin')))
    peakq = re.search(r'최대|피크|가장\s?많이|제일\s?많이|한도|peak|highest|max|limit', q, re.I)
    peak_time = bool(today.get('highestGridImportAt') and peakq and re.search(r'몇\s?시|언제|시각|what time|when', q, re.I))
    if peak_time:
        out.append(('오늘 최대 수전 %s kW는 %s 무렵(15분 평균 기준)에 기록됐습니다' if ko else "Today's highest grid import, %s kW, was around %s (15-min average)") % (today.get('highestGridImportTodayKW'), today['highestGridImportAt']))
    dm = ctx.get('dayMetrics') or {}
    ma, mb = (dm.get('agent') or {}).get('minutesOverLimit'), (dm.get('baseline') or {}).get('minutesOverLimit')
    hypo = CONCEPT.search(q)                              # "한도를 넘으면 어떻게 돼?" asks about consequences, not today's minutes
    if hypo and peakq and re.search(r'넘으면|초과하면|넘게\s?되면|넘어가면|exceed|go(es)?\s+over', q, re.I):
        out.append('피크 한도를 넘으면 기본요금이 오릅니다: 한전 기본요금은 최대수요전력(15분 평균 kW)으로 매겨져 한 번 높게 찍힌 피크가 최대 1년 동안 기본요금에 반영되고, 계약전력을 넘으면 초과 사용 부가금이 붙을 수 있습니다. 그래서 코디네이터가 예측 수전을 한도의 94% 안으로 묶습니다'
                   if ko else 'Going over the peak limit raises the demand charge: KEPCO bills it on the highest 15-minute demand, so one high peak counts for up to a year, and exceeding the contract can add a surcharge. That is why the coordinator keeps forecast import within 94 % of the limit')
    if isinstance(ma, (int, float)) and isinstance(mb, (int, float)) and peakq and (peak_time or (not hypo and re.search(r'넘|초과|exceed|over', q, re.I))):
        # v2.1 once gave the baseline's 97 minutes as the agents' own: name both
        out.append(('오늘 한도를 넘은 시간: 멀티에이전트 %g분, 같은 조건의 룰 기반 BMS %g분' if ko else
                    'Minutes over the limit today: multi-agent %g, rule-based BMS under the same conditions %g') % (ma, mb))
    campus = ctx.get('campus') or {}
    if campus and re.search(r'괜찮|문제\s?(없|있)|이상\s?(없|있)|정상(이|인|이야)|상태\s?(어때|어떄|어떻|좋)|잘\s?(돌아|되고)|how\s+are\s+we|everything\s+ok|all\s+good', q, re.I):
        # "지금 상태 괜찮아?" got the cost template: give the three things that decide it
        faults = (ctx.get('faults') or {}).get('openAlarms') or []
        out.append(('수전 %s kW / 한도 %s kW(여유 %s%%), 쾌적 범위 %s/%s개 구역, 열린 경보 %d건, 센서 고장 의심 %d건' if ko else
                    'Grid import %s kW of %s kW (%s %% headroom), %s of %s zones in the comfort band, %d open alerts, %d suspected sensor faults') % (
            campus.get('gridImportNowKW'), campus.get('peakLimitKW'), campus.get('headroomNowPct'), today.get('zonesInBand'), today.get('zonesCounted'),
            len(ctx.get('alerts') or []), len(faults)))
    alerts = [a for a in (ctx.get('alerts') or []) if isinstance(a, str)]
    if alerts and re.search(r'급해|급한|급하|위험|심각|문제|조치가?\s?필요|urgent|critical|problem|wrong', q, re.I):
        alerts.sort(key=lambda a: 0 if a.startswith('crit') else 1 if a.startswith('warn') else 2)
        out.append(('가장 심각한 경보: %s' if ko else 'Most severe alert: %s') % alerts[0].split(': ', 1)[-1])
    bl = ctx.get('buildingsByLoad') or []
    if not ko and bl and re.search(r'building', q, re.I):
        en = {'B1': 'office tower', 'B2': 'research building', 'B3': 'dormitory', 'B4': 'data centre'}
        out.append('Load by building now: ' + ', '.join('%s (%s) %s kW' % (b.get('id'), en.get(b.get('id'), b.get('id')), b.get('loadKW')) for b in bl[:4]))
    floors = {f.get('id'): f for f in (ctx.get('floors') or []) if isinstance(f, dict)}
    for fid in _floors_named(q)[:2]:
        f = floors.get(fid)
        if f:
            out.append(('%s: %s °C(설정 %s °C), 재실 %s%%, %s kW, 쾌적 범위 %s' if ko else '%s: %s °C (setpoint %s °C), %s %% occupied, %s kW, %s the comfort band') % (
                fid, f.get('tempC'), f.get('setpointC'), f.get('occupancyPct'), f.get('kW'), ('안' if f.get('inBand') else '밖') if ko else ('inside' if f.get('inBand') else 'outside')))
        elif fid and floors:
            out.append(('%s 층은 데이터에 없습니다(층 id는 floors에 있음)' if ko else '%s is not in the data (floor ids are in floors)') % fid)
    hot, cold = re.search(r'(제일|가장)\s?(덥|더운|뜨거|hot)|hottest|warmest', q, re.I), re.search(r'(제일|가장)\s?(춥|추운|시원|cold)|coldest|coolest', q, re.I)
    occ = [f for f in floors.values() if (f.get('occupancyPct') or 0) > 0 and isinstance(f.get('tempC'), (int, float))]
    if (hot or cold) and occ:
        f = max(occ, key=lambda x: x['tempC']) if hot else min(occ, key=lambda x: x['tempC'])
        out.append(('재실 층 중 가장 %s 곳은 %s: %s °C(설정 %s °C)입니다' if ko else 'Of the occupied floors the %s is %s: %s °C (setpoint %s °C)') % (
            ('더운' if hot else '시원한') if ko else ('warmest' if hot else 'coolest'), f['id'], f['tempC'], f.get('setpointC')))
    rooms = ctx.get('rooms') or {}
    if rooms and re.search(r'불|조명|전등|light', q, re.I) and re.search(r'빈|공실|아무도|비어|empty|vacant', q, re.I):
        lst = ', '.join('%s(%s, %s분째 빈 방)' % (r.get('id'), r.get('name'), r.get('vacantMin')) if ko else '%s (%s, empty %s min)' % (r.get('id'), r.get('name'), r.get('vacantMin'))
                        for r in rooms.get('vacantWithLightsOnRooms') or [])
        n = rooms.get('vacantWithLightsOn', 0)
        out.append(('빈 방인데 조명이 켜진 방은 %s개입니다%s. %s' % (n, ': ' + lst if lst else '', rooms.get('note', '')) if ko else
                    '%s empty rooms have their lights on%s. %s' % (n, ': ' + lst if lst else '', rooms.get('note', ''))).strip())
    ev = ctx.get('ev') or {}
    if ev and re.search(r'몇\s?대|대수|how many', q, re.I) and re.search(r'충전|EV|전기차|car|charg', q, re.I):
        out.append(('충전기 %s기 중 %s대 연결, %s대 충전 중, 합계 %s kW' if ko else '%s chargers: %s cars connected, %s charging, %s kW in total') % (
            ev.get('chargers'), ev.get('carsConnected'), ev.get('charging'), ev.get('totalKW')))
    sc = ctx.get('scenario') or {}
    if sc and re.search(r'시나리오|scenario|오늘\s?(조건|상황)이?\s?(뭐|어떤)', q, re.I):
        out.append(('지금 시나리오는 "%s"입니다: %s' if ko else 'The scenario now running is "%s": %s') % (sc.get('name'), sc.get('whatIsDifferent') or sc.get('settings') or ''))
    return out[:3]


def _ro(word):
    """The Korean particle 로 / 으로 for a word (경부하로, 피크 시간으로)."""
    w = str(word or '')
    code = ord(w[-1]) - 0xAC00 if w else -1
    return '으로' if 0 <= code < 11172 and code % 28 not in (0, 8) else '로'


_DEFINE = re.compile(r'^\s*(.{1,24}?)\s*(이|가|은|는|란|이란)?\s*(뭐야|뭔가요|뭐예요|뭐에요|뭔데|무엇인가요|무엇이야|무엇이에요|뭐지|무슨\s?뜻이야|무슨\s?뜻인가요|란|이란)\s*[?？.!]*\s*$'
                     r'|^\s*what\s+(is|are|does)\s+(an?\s+|the\s+)?(.{1,40}?)(\s+mean)?\s*[?.!]*\s*$', re.I)


def define_answer(question, context):
    """'DR이 뭐야?' / 'What is demand response?': the glossary definition and the current value, without the model.
    v2.1 used the glossary sentence in most runs but in one answered only "지금 진행 중이지 않습니다" (2026-11-11),
    and "DR이 뭐야?" is one of the example buttons. None unless the whole question asks what one glossary term is."""
    q = question or ''
    m = _DEFINE.match(q)
    if not m:
        return None
    term = (m.group(1) or m.group(6) or '').strip()
    if re.search(r'지금|현재|오늘|요즘|\bnow\b|current|today', term, re.I):   # "지금 요금 구간이 뭐야?" asks for a value
        return None
    hit = next(((k, e) for rx, k, e in GLOSSARY[1:] if rx.search(term)), None)   # [0] is the what-if entry
    if not hit:
        return None
    ko = bool(re.search(r'[가-힣]', q))
    text = hit[0] if ko else hit[1]
    name, body = text.split(':', 1)
    lines = ['%s: %s' % (name.strip(), body.strip())]
    try:
        c = json.loads(context) if context else {}
    except ValueError:
        c = {}
    cp, dr = c.get('campus') or {}, c.get('demandResponse') or {}
    if re.search(r'(?<![A-Za-z])DR(?![A-Za-z])|수요\s?반응|demand', term, re.I) and dr:
        lines.append(('- 지금 DR 진행 중: %s–%s, %s kW 감축 (%s)' % (dr.get('start'), dr.get('end'), dr.get('shedKW'), dr.get('source')) if dr.get('active') else '- 지금 진행 중인 DR은 없습니다')
                     if ko else ('- Demand response is active now: %s–%s, cutting %s kW' % (dr.get('start'), dr.get('end'), dr.get('shedKW')) if dr.get('active') else '- No demand response event is active now'))
    elif re.search(r'ESS|배터리|저장|battery|storage', term, re.I) and cp.get('essNowKW') is not None:
        p = cp['essNowKW']
        state = ('방전' if p > 0 else '충전' if p < 0 else '대기') if ko else ('discharging' if p > 0 else 'charging' if p < 0 else 'idle')
        lines.append(('- 지금 ESS: %s %s kW, 잔량(SOC) %s%%' if ko else '- Battery now: %s %s kW, state of charge %s %%') % (state, abs(p), cp.get('essSocPct')))
    elif re.search(r'요금\s?구간|계시별|TOU|time[- ]of[- ]use|tariff', term, re.I) and (c.get('tariff') or {}).get('schedule'):
        cur = c['tariff'].get('currency') or ''
        for r in c['tariff']['schedule']:
            lines.append('- %s %s(%s%s/kWh)' % (r.get('tier'), r.get('hours'), cur, r.get('pricePerKWh')) if r.get('pricePerKWh') is not None else
                         '- %s %s' % (r.get('tier'), r.get('hours')))
    elif re.search(r'한도|limit|계약|최대\s?수요|기본\s?요금|demand\s+charge', term, re.I) and cp.get('peakLimitKW') is not None:
        lines.append(('- 지금 수전 %s kW, 한도 %s kW(여유 %s kW)' if ko else '- Now: %s kW against a %s kW limit (%s kW headroom)') % (cp.get('gridImportNowKW'), cp.get('peakLimitKW'), cp.get('headroomNowKW')))
    return '\n'.join(lines)


def faq_answer(question, context):
    """A fixed explanation plus today's numbers for "피크 한도를 넘으면 어떻게 돼?": v2.1 answered it with the headroom
    template ("1,000 kW까지는 문제가 없습니다") even with the consequence sentence in answerFacts and the glossary
    (3 runs, 2026-11-11). None for any other question."""
    q = question or ''
    if not (CONCEPT.search(q) and re.search(r'한도|피크|limit|peak', q, re.I) and re.search(r'넘으면|초과하면|넘게\s?되면|넘어가면|exceed|go(es)?\s+over', q, re.I)):
        return None
    try:
        c = json.loads(context) if context else {}
    except ValueError:
        c = {}
    ko = bool(re.search(r'[가-힣]', q))
    cp, dm = c.get('campus') or {}, c.get('dayMetrics') or {}
    lines = ['피크 한도를 넘으면 기본요금이 오릅니다. 한전 기본요금은 최대수요전력(15분 평균 kW)으로 매겨져, 한 번 높게 찍힌 피크가 최대 1년 동안 기본요금에 반영되고 계약전력을 넘으면 초과 사용 부가금이 붙을 수 있습니다.'
             if ko else 'Going over the peak limit raises the demand charge: KEPCO bills it on the highest 15-minute demand, so one high peak counts for up to a year, and exceeding the contract can add a surcharge.',
             '- 그래서 코디네이터는 예측 수전이 한도의 94%를 넘지 않게 미리 조정합니다' if ko else '- That is why the coordinator keeps forecast import within 94 % of the limit']
    if cp.get('gridImportNowKW') is not None:
        lines.append(('- 지금 수전 %s kW, 한도 %s kW(여유 %s kW)' if ko else '- Now: %s kW against a %s kW limit (%s kW headroom)') % (cp.get('gridImportNowKW'), cp.get('peakLimitKW'), cp.get('headroomNowKW')))
    ma, mb = (dm.get('agent') or {}).get('minutesOverLimit'), (dm.get('baseline') or {}).get('minutesOverLimit')
    if isinstance(ma, (int, float)) and isinstance(mb, (int, float)):
        lines.append(('- 오늘 한도를 넘은 시간: 멀티에이전트 %g분, 같은 조건의 룰 기반 BMS %g분' if ko else '- Minutes over the limit today: multi-agent %g, rule-based BMS %g') % (ma, mb))
    return '\n'.join(lines)


def lookup_answer(question, context):
    """A finished answer, without the model, for tariff-timetable questions ("가장 비싼/싼 시간대는?", "언제 끝나?").
    They are pure lookups, and v2.1 kept answering "가장 비싼 시간대" with today's highest grid import, even with the
    timetable in campus_state and the answer sentence in answerFacts (3 tries, 2026-11-11). None for anything else."""
    q = question or ''
    try:
        c = json.loads(context) if context else None
    except ValueError:
        return None
    tf = c.get('tariff') if isinstance(c, dict) else None
    sched = (tf or {}).get('schedule') or []
    if not sched or not re.search(r'요금|전기|단가|구간|시간대|tariff|price|electricity|period', q, re.I):
        return None
    timeq = re.search(r'시간|때|언제|구간|시각|몇\s?시|when|time|hour|period', q, re.I)
    cheap = timeq and re.search(r'(가장|제일|젤|언제)\s?.{0,6}((?<!비)싸|(?<!비)싼|저렴)|(?<!비)싼\s?(시간|때)|cheapest|lowest\s+price', q, re.I)   # not the 싼 in 비싼
    dear = timeq and re.search(r'(가장|제일|젤|언제)\s?.{0,6}(비싸|비싼)|비싼\s?(시간|때)|most\s+expensive|highest\s+price', q, re.I)
    ends = re.search(r'(언제|몇\s?시에?)\s?(끝|바뀌)|끝나|끝날|until\s+when|when\s+does\s+.*\s(end|change)', q, re.I)
    nowq = re.search(r'(지금|현재)\s?(전기\s?)?(요금\s?)?(구간|단가|요금)|current\s+(tariff|price|period)|(tariff|price)\s+(period\s+)?(is\s+it\s+)?now', q, re.I)
    if not (cheap or dear or ends or nowq):
        return None
    ko = bool(re.search(r'[가-힣]', q))
    cur = tf.get('currency') or ''

    def price(r):
        if r.get('pricePerKWh') is None:
            return ''
        return '%s%s/kWh' % (cur, r['pricePerKWh']) if cur in ('$', '₩') else '%s %s/kWh' % (r['pricePerKWh'], cur)
    now_name = (tf.get('tier') or {}).get('name') if isinstance(tf.get('tier'), dict) else tf.get('tier')
    now = next((r for r in sched if r.get('tier') == now_name), None)
    nc = tf.get('nextChange') or {}
    top, low = sched[0], sched[-1]
    en = {'최대부하': 'peak', '중간부하': 'mid-peak', '경부하': 'off-peak'}           # the page sends tier names in its own language
    name = (lambda x: x) if ko else (lambda x: en.get(x, x))
    say = (lambda r: '%s %s(%s)' % (r['tier'], r['hours'], price(r))) if ko else (lambda r: '%s, %s (%s)' % (name(r['tier']), r['hours'], price(r)))
    if ends and re.search(r'비싼|비싸|expensive', q, re.I) and now_name != top.get('tier'):
        ends, nowq = None, True                               # "비싼 시간 언제 끝나?" at night: say it is not expensive now
        head0 = ('지금은 비싼 시간이 아닙니다. ' if ko else 'It is not an expensive period now. ')
    else:
        head0 = ''
    if ko:
        head = head0 + ('가장 비싼 시간대는 %s, 가장 싼 시간대는 %s입니다.' % (say(top), say(low)) if cheap and dear else
                '가장 비싼 시간대는 %s입니다.' % say(top) if dear else '가장 싼 시간대는 %s입니다.' % say(low) if cheap else
                '지금 %s 구간은 %s에 끝나고 %s%s 바뀝니다.' % (now_name, nc.get('at'), nc.get('to'), _ro(nc.get('to'))) if ends else
                '지금(%s)은 %s 구간(%s)이고, %s분 뒤 %s에 %s%s 바뀝니다.' % (c.get('clock'), now_name, price(now) if now else '', nc.get('inMin'), nc.get('at'), nc.get('to'), _ro(nc.get('to'))))
        lines = [head]
        if now and nc and (cheap or dear or ends):              # the current-period answer already says it
            lines.append('- 지금(%s)은 %s 구간(%s)이고, %s분 뒤 %s에 %s%s 바뀝니다' % (c.get('clock'), now['tier'], price(now), nc.get('inMin'), nc.get('at'), nc.get('to'), _ro(nc.get('to'))))
        if dear and not cheap:
            lines.append('- 가장 싼 시간대는 %s입니다' % say(low))
        elif cheap and not dear:
            lines.append('- 가장 비싼 시간대는 %s입니다' % say(top))
        elif ends or nowq:
            lines += ['- %s' % say(r) for r in sched]
    else:
        head = head0 + ('Most expensive: %s; cheapest: %s.' % (say(top), say(low)) if cheap and dear else
                'The most expensive period is %s.' % say(top) if dear else 'The cheapest period is %s.' % say(low) if cheap else
                'The current %s period ends at %s and changes to %s.' % (name(now_name), nc.get('at'), name(nc.get('to'))) if ends else
                'Now (%s) is the %s period (%s); it changes to %s at %s, in %s min.' % (c.get('clock'), name(now_name), price(now) if now else '', name(nc.get('to')), nc.get('at'), nc.get('inMin')))
        lines = [head]
        if now and nc and (cheap or dear or ends):
            lines.append('- Now (%s) is the %s period (%s); it changes to %s at %s, in %s min' % (c.get('clock'), name(now['tier']), price(now), name(nc.get('to')), nc.get('at'), nc.get('inMin')))
        if dear and not cheap:
            lines.append('- The cheapest period is %s' % say(low))
        elif cheap and not dear:
            lines.append('- The most expensive period is %s' % say(top))
        elif ends or nowq:
            lines += ['- %s' % say(r) for r in sched]
    return '\n'.join(lines)


def align_summary(data, question=''):
    """Rewrite a proposal summary that names a kind of action the proposal does not contain. With the schema narrowed
    to setpoints ("에어컨 좀 약하게 해줘"), v2.1 still wrote its usual "…빈 방 조명을 끄기를 제안합니다"."""
    acts = [a for a in (data.get('actions') or []) if isinstance(a, dict)]
    if not acts:
        return
    kinds = {a.get('type') for a in acts}
    s = data.get('summary') or ''
    says_light, says_temp = re.search(r'조명|소등|lights?\b', s, re.I), re.search(r'설정\s?온도|냉방|셋백|setpoint|cooling', s, re.I)
    if not ((says_light and 'roomLights' not in kinds) or (says_temp and not kinds & {'setpoint', 'roomSetpoint'})):
        return
    n_t = sum(1 for a in acts if a.get('type') in ('setpoint', 'roomSetpoint'))
    n_l = sum(1 for a in acts if a.get('type') == 'roomLights')
    if re.search(r'[가-힣]', question or s):
        parts = (['설정온도 조치 %d개' % n_t] if n_t else []) + (['조명 조치 %d개' % n_l] if n_l else [])
        data['summary'] = '요청에 맞춰 %s를 제안합니다.' % ', '.join(parts)
    else:
        parts = (['%d setpoint action(s)' % n_t] if n_t else []) + (['%d lighting action(s)' % n_l] if n_l else [])
        data['summary'] = 'Proposed for this request: %s.' % ', '.join(parts)


def model_view(context):
    """The campus_state the model sees: the page also sends the tariff timetable (tariff.schedule, tariff.nextChange)
    for the gateway's lookups, but with it in view v2.1 kept calling the next period the current one ("지금은 중간부하"
    at 14:36, in chat and in the briefing), so it is taken out here; the answers that need it come from lookup_answer
    and answerFacts instead."""
    try:
        c = json.loads(context) if context else None
    except ValueError:
        return context
    tf = c.get('tariff') if isinstance(c, dict) else None
    if not isinstance(tf, dict) or not ({'schedule', 'nextChange'} & set(tf)):
        return context
    tf.pop('schedule', None)
    tf.pop('nextChange', None)
    return json.dumps(c, ensure_ascii=False)


def augment(question, context):
    """campus_state for a typed question: answerFacts and glossary appended last, next to the question. Returns the
    context unchanged when it is not a JSON object or nothing applies."""
    try:
        c = json.loads(context) if context else None
    except ValueError:
        return context
    if not isinstance(c, dict):
        return context
    facts, gloss = answer_facts(question, c), glossary_for(question)
    if facts:
        c['answerFacts'] = facts
    if gloss:
        c['glossary'] = gloss
    return json.dumps(c, ensure_ascii=False) if facts or gloss else context


# short follow-ups that only make sense with the previous question ("왜 그런 거야?", "언제까지야?")
FOLLOW = re.compile(r'^\s*(왜|그럼|그러면|그건|그거|그게|그래서|언제까지|얼마나|더\s?자세히|자세히|그\s|이유|why\b|and\b|then\b|what about|how long|until when)', re.I)


def contextualize(messages):
    """Attach the previous user question to a short follow-up, which the fine-tuned model reads as a new question."""
    if len(messages) < 3 or messages[-1]['role'] != 'user':
        return messages
    q = messages[-1]['content']
    if len(q) > 30 and not FOLLOW.match(q):
        return messages
    if not (FOLLOW.match(q) or len(q) <= 12):
        return messages
    prev = next((m['content'] for m in reversed(messages[:-1]) if m['role'] == 'user'), '')
    if not prev:
        return messages
    ko = bool(re.search(r'[가-힣]', q))
    lead = ('(앞 질문: %s)\n' if ko else '(previous question: %s)\n') % prev[:200]
    return messages[:-1] + [{'role': 'user', 'content': lead + q}]


# requests for the hidden instructions or keys: answered without the model
PROMPT_ASK = re.compile(
    r'시스템\s?프롬프트|system\s?prompt|(지시|지침|프롬프트)(문|사항)?\s?(을|를)?\s?(전부\s?|모두\s?|그대로\s?)?(무시|보여|출력|알려|공개)|'
    r'(이전|앞의?|위의?)\s?(지시|명령|규칙)\s?(은|는|을|를)?\s?(모두\s?|전부\s?)?무시|ignore\s+(all\s+|any\s+)?(previous|prior|above|the)?\s*(instructions|rules|prompts?)|'
    r'reveal\s+(your\s+)?(instructions|prompt)|api\s?키|api\s?key|access\s?key|접근\s?키|비밀\s?번호|password', re.I)


def refusal(question):
    ko = bool(re.search(r'[가-힣]', question or ''))
    return ('그 요청은 도와드릴 수 없습니다. 내부 지침과 키는 공개하지 않고, 운영 규칙(피크 한도 우선, 데이터센터 냉방 유지)도 바꾸지 않습니다.\n'
            '- 캠퍼스 부하·요금·쾌적·에이전트 동작은 무엇이든 물어보세요' if ko else
            'I cannot help with that: internal instructions and keys are not shared, and the operating rules (peak limit first, '
            'data-centre cooling kept) do not change.\n- Ask me anything about loads, cost, comfort or the agents')


def leaks_prompt(text, system):
    """True when the answer reproduces two or more distinctive lines of the system prompt."""
    lines = [ln.strip(' -') for ln in system.splitlines() if len(ln.strip(' -')) >= 24]
    return sum(1 for ln in lines if ln[:40] in text) >= 2


_ECHO = re.compile(r'^\s*[-•*]?\s*.{1,120}?에 대해서는 지어내지 않겠습니다\.?\s*$', re.M)


def clean_answer(text, context=''):
    """Drop the trained 'unknown' template's line that repeats the question back, and bullet lines that only copy a
    note meant for the model ("BuildingsByLoad is sorted by current loadKW…")."""
    out = _ECHO.sub('', text)
    notes = re.findall(r'"\w+Note"\s*:\s*"([^"]{20,})"', context or '')   # buildingsNote, floorsNote, essNote (not rooms.note)
    if notes:
        out = '\n'.join(ln for ln in out.splitlines() if not any(n[:28].lower() in ln.lower() for n in notes))
    return re.sub(r'\n{3,}', '\n\n', out).strip() or text


_LOOP = re.compile(r'(.{3,40}?)\1{5,}', re.S)


def find_loop(text):
    """Index where a phrase starts repeating itself 6+ times in a row (a decoding loop), or -1."""
    m = _LOOP.search(text[-1600:])
    if not m:
        return -1
    return len(text) - len(text[-1600:]) + m.start() + len(m.group(1))   # keep the first occurrence


class SafeStream:
    """Keep partial prompt signatures private, including signatures split across deltas.

    Suppress the first distinctive signature too: two signatures may be arbitrarily
    far apart, so a finite tail alone cannot undo the first disclosure.
    """
    def __init__(self, system, emit):
        self.signatures = [ln.strip(' -')[:40] for ln in system.splitlines() if len(ln.strip(' -')) >= 24]
        self.emit = emit
        self.pending = ''
        self.blocked = False

    def feed(self, piece):
        if self.blocked:
            return
        self.pending += piece
        if any(s in self.pending for s in self.signatures):
            self.blocked = True
            self.pending = ''
            return
        keep = max((len(s) for s in self.signatures), default=1) - 1
        if len(self.pending) > keep:
            n = len(self.pending) - keep
            self.emit(self.pending[:n])
            self.pending = self.pending[n:]

    def finish(self):
        if not self.blocked and self.pending:
            self.emit(self.pending)
            self.pending = ''


def forecast_answer(question, context):
    q = question or ''
    if not (re.search(r'한도|피크|limit|peak', q, re.I) and
            re.search(r'넘을|초과할|이대로|will.*(?:exceed|over)|going to.*(?:exceed|over)', q, re.I)):
        return None
    try:
        c = json.loads(context) if context else {}
    except (ValueError, TypeError):
        c = {}
    ko = bool(re.search(r'[가-힣]', q))
    f = c.get('forecast') or {}
    limit = (c.get('campus') or {}).get('peakLimitKW')
    peak, at = f.get('next4hMaxKW'), f.get('next4hMaxAt')
    if peak is None or limit is None or at is None:
        return '예측이 아직 준비되지 않았습니다.' if ko else 'The forecast is not ready yet.'
    margin = limit - peak
    if ko:
        text = '향후 4시간 예측 최대 수전은 %s에 %g kW입니다. 한도 %g kW 대비 %g kW %s 예상입니다.' % (at, peak, limit, abs(margin), '초과' if margin < 0 else '여유')
    else:
        text = 'The next 4-hour forecast peaks at %g kW at %s: %g kW %s the %g kW limit.' % (peak, at, abs(margin), 'above' if margin < 0 else 'below', limit)
    if f.get('next4hMaxPctOfLimit') is not None:
        text += ' (%s%%)' % f['next4hMaxPctOfLimit']
    if f.get('band90KW') is not None:
        text += (' 90%% 예측 범위: %s kW.' if ko else ' 90%% forecast band: %s kW.') % f['band90KW']
    return text
