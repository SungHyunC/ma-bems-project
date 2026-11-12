"""Question phrasings for the v2.2 data, written by an open-weight model on Fireworks (DeepSeek, as in v2), never by
Claude: the project keeps Claude output out of the training data. Only questions are generated; every answer is still
written by the rules in make_data_v22.py from the campus context.

    FIREWORKS_API_KEY=... python gen_paraphrases_v22.py ../data/v22/paraphrases_v22.json [--only key,key] [--dry]

v2.2 adds the question kinds that visitors asked and v2.1 had no rule for (ft/data/realq.json, 2026-11-11): a building's
or a floor's own figure, the chiller, the time of today's peak, the hottest floor, empty rooms with lights on, EV
counts, the scenario, why the battery is doing what it does, concept questions ("절감률은 어떻게 계산해?"), off-topic
chat, typed control requests ("에어컨 좀 약하게"), short follow-ups and more English. The existing kinds get new
phrasings too, so the held-out set can be unseen by both v2.1 and v2.2. The file is resumable: keys already present are
kept unless --only names them. Token usage is written next to it (*_usage.json) for the budget.
"""
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MODEL = 'accounts/fireworks/models/deepseek-v4p1-flash'
HERE = Path(__file__).resolve().parent

STYLE = ('반말·존댓말, 아주 짧은 것(2~5단어)과 긴 것, 실무자 말투와 구어체를 섞고, 같은 문장 구조를 반복하지 마세요. '
         '오타 없이 쓰세요.')

# ---------------------------------------------------------------- kinds that already had phrasings (v2): more of them
OLD = {
    'q_peak': '지금 계통 수전이 피크 한도까지 얼마나 여유가 있는지 / 한도를 넘을 위험이 있는지',
    'q_cost': '오늘 지금까지의 전기요금과 룰 기반 BMS 대비 절감액·절감률',
    'q_top': '지금 전력을 가장 많이 쓰는 건물이 어디인지',
    'q_ess': '배터리(ESS)가 지금 충전/방전 중인지와 충전 상태(SOC)',
    'q_pv': '태양광이 지금 얼마나 발전하고 있는지',
    'q_comfort': '실내 쾌적성 상태, 쾌적 범위를 벗어난 구역이 있는지',
    'q_agents': '에이전트들이 지금 무엇을 하고 있고 최근 어떤 조치를 했는지',
    'q_weather': '바깥 날씨(기온·일사)가 전력 부하나 냉방에 어떤 영향을 주는지',
    'q_dr': '수요반응(DR) 이벤트가 지금 진행 중인지',
    'q_faults': '센서 고장이나 이상 경보가 있는지',
    'q_forecast': '앞으로 몇 시간의 최대 수전(피크) 예측값과 시각',
    'q_tariff': '지금 요금 구간과 kWh 단가, 피크 요금 시간대',
    'q_temp': '지금 바깥 기온이 몇 도인지 (영향 말고 값 자체)',
    'q_maxtoday': '오늘 지금까지 가장 높았던 계통 수전(최대 수요)과 한도를 넘었는지',
    'q_co2': '오늘 지금까지의 탄소(CO2) 배출량',
    'q_ev': '전기차(EV) 충전 현황(충전 전력, 오늘 충전 세션)',
    'q_pvself': '오늘 태양광 발전량과 그중 캠퍼스가 바로 쓴 비율(자가소비율)',
}

# ---------------------------------------------------------------- new kinds
NEW = {
    'q_load': '지금 캠퍼스 전체가 전기를 얼마나 쓰고 있는지(현재 부하, 사용 전력)',
    'q_grid': '지금 한전 계통에서 받아 오는 전력(계통 수전)이 몇 kW인지',
    'q_chiller': '냉동기(칠러)가 지금 전력을 얼마나 쓰고 있는지',
    'q_peak_time': '오늘 최대 수전(최대 전력)이 몇 시에 찍혔는지',
    'q_savings': '오늘 룰 기반 BMS보다 돈을 얼마나 아꼈는지(절감액)',
    'q_why_ess': '배터리(ESS)가 지금 왜 충전·방전·대기 중인지 그 이유',
    'q_hot': '사람이 있는 층 가운데 지금 가장 더운 곳이 어디인지',
    'q_cold': '사람이 있는 층 가운데 지금 가장 시원한 곳이 어디인지',
    'q_vacant_lights': '사람이 없는 빈 방인데 조명이 켜져 있는 곳이 있는지',
    'q_ev_count': '전기차가 지금 몇 대 충전기에 연결돼 있고 몇 대가 충전 중인지(대수)',
    'q_scenario': '지금 대시보드가 어떤 시나리오(오늘의 조건)로 돌아가고 있는지',
    'q_capabilities': 'AI 비서가 무엇을 할 수 있는지, 어떻게 쓰면 되는지',
}

# building-level figures: one call per building and figure, so the particles fit the name
BUILDINGS = {'B1': '오피스 타워', 'B2': '연구동', 'B3': '기숙사', 'B4': '데이터센터'}
BLD_METRIC = {
    'load': '그 건물이 지금 전력을 얼마나 쓰고 있는지(건물 전체 부하)',
    'hvac': '그 건물의 냉방(공조) 전력이 얼마인지',
    'light': '그 건물의 조명 전력이 얼마인지',
    'people': '그 건물에 지금 사람이 몇 명 있는지(재실 인원·재실률)',
}
# floor-level figures: the floor is a placeholder filled in by make_data_v22.py ("B1 3층", "연구동 2층", ...)
FLOOR_METRIC = {
    'temp': '그 층의 지금 실내 온도(몇 도인지)',
    'occ': '그 층에 사람이 얼마나 있는지(재실률)',
    'power': '그 층이 전력을 얼마나 쓰는지',
    'comfort': '그 층이 쾌적 범위 안에 있는지, 더운지',
}

# concept questions: the gateway adds the matching glossary entry to campus_state (server/assist.py augment)
CONCEPT = {
    'c_dr': '수요반응(DR)이 무엇이고 이 캠퍼스는 DR 신호가 오면 어떻게 대응하는지',
    'c_ess': 'ESS(에너지저장장치, 배터리)가 무엇이고 언제 충전·방전하는지 원리',
    'c_limit': '피크 한도(계약전력, 최대수요)가 무엇이고 왜 중요한지',
    'c_savings': '절감률을 어떻게 계산하는지, 룰 기반 BMS(기준선)와 무엇이 다른지',
    'c_negotiation': '에이전트끼리 어떻게 협상하고 코디네이터가 무슨 역할을 하는지',
    'c_tou': '계시별 요금(시간대별 요금 구간)이 무엇인지',
    'c_setback': '셋백과 사전 냉방이 무엇이고 왜 하는지',
    'c_fdd': '센서 고장 감지(FDD)가 어떻게 작동하고 고착·드리프트·끊김을 어떻게 판단하는지',
    'c_rules': '운영 우선순위나 운영 규칙이 무엇인지',
    'c_selfcons': '태양광 자가소비율이 무슨 뜻인지',
    'c_grid': '수전(계통 수전)이 무슨 뜻이고 어떻게 계산되는지',
    'c_comfort': '쾌적 범위·쾌적도가 무슨 뜻이고 어떻게 계산하는지',
    'c_forecast': '수요 예측을 어떻게 하는지, 예측 정확도는 어떻게 재는지',
    'c_mabems': '이 시스템(MA-BEMS, 멀티에이전트 BEMS)이 어떤 구조이고 어떻게 작동하는지',
    'c_heatwave': '폭염이 오면 에이전트들이 어떻게 대응하는지',
    'c_cloudy': '흐린 날(구름, 비)에는 에이전트들이 어떻게 대응하는지',
    'c_evrush': '전기차 충전이 몰릴 때(퇴근 시간) 어떻게 대응하는지',
    'c_holiday': '휴일·방학·주말에는 어떻게 운영하는지',
    'c_whatif': '설정온도를 올리거나 내리면, 조명을 끄면 전력이나 비용이 얼마나 줄어드는지(가정 질문)',
}

# typed control requests the page sends to the proposal task (vague ones; named targets are parsed by the page)
REQUEST = {
    'req_cool': '냉방(에어컨)을 약하게 하거나 설정온도를 올려 달라는 요청. 특정 층·방 이름이나 숫자 온도는 넣지 말고, "~해 줘" 같은 요청형으로',
    'req_light': '조명을 줄이거나 아껴 달라는 요청. "빈 방"이라는 말이나 특정 방 이름은 넣지 말고, "~해 줘" 같은 요청형으로',
    'req_advice': '피크나 전기요금·전력을 줄이려면 지금 무엇을 해야 하는지 조치를 묻는 질문',
}

EN = {
    'q_peak_en': 'how much headroom is left to the peak limit right now',
    'q_cost_en': 'how much money was saved today compared with the rule-based BMS',
    'q_load_en': 'how much power the whole campus is using right now',
    'q_top_en': 'which building is using the most power right now',
    'q_ess_en': 'what the battery (ESS) is doing now and its state of charge',
    'q_pv_en': 'how much the solar panels are generating right now',
    'q_faults_en': 'whether any sensor fault or alarm is open',
    'q_dr_en': 'whether a demand response event is active',
    'c_savings_en': 'how the savings percentage is computed and how this differs from the rule-based BMS',
    'c_dr_en': 'what demand response is and how this campus responds to it',
    'c_ess_en': 'what the ESS (battery) is and when it charges or discharges',
    'req_advice_en': 'what we should do right now to cut the peak or the electricity cost',
    'req_cool_en': 'a request to turn the air conditioning down (warmer setpoints), without naming a floor or a number',
}

FIELDS = ('현재 시각, 요금 구간·단가·피크 시간대, 바깥 기온·일사량, 캠퍼스 부하·계통 수전·피크 한도·여유, 태양광 발전, '
          'ESS 충·방전·SOC, EV 충전 전력·대수, 냉동기 전력, 오늘 누적 전력량·비용·룰 기반 BMS 대비 절감률·오늘 최대 수전과 그 시각·쾌적 유지율, '
          '건물별 부하(냉방·조명·콘센트·IT)·재실, 층별 온도·재실·전력, 빈 방 조명, 주의 구역 온도, DR 이벤트, 경보, 에이전트 상태와 최근 조치 로그, '
          '오늘 탄소 배출량·EV 충전 세션·태양광 자가소비율, 향후 4시간 피크 예측, 센서 고장 경보, 지금 시나리오')


def call(prompt, usage, max_tokens=6000, temperature=0.9):
    body = {'model': MODEL, 'max_tokens': max_tokens, 'temperature': temperature, 'reasoning_effort': 'low',
            'messages': [{'role': 'user', 'content': prompt}]}
    req = urllib.request.Request('https://api.fireworks.ai/inference/v1/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + os.environ['FIREWORKS_API_KEY'], 'Content-Type': 'application/json'})
    for attempt in range(4):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=300).read())
            break
        except Exception as e:                            # rate limit / transient: back off
            if attempt == 3:
                raise
            print('retry', type(e).__name__, flush=True)
            time.sleep(5 * (attempt + 1))
    u = d.get('usage') or {}
    usage['prompt_tokens'] += u.get('prompt_tokens', 0)
    usage['completion_tokens'] += u.get('completion_tokens', 0)
    usage['calls'] += 1
    text = d['choices'][0]['message'].get('content') or ''
    m = re.search(r'\[.*\]', text, re.S)
    try:
        arr = json.loads(m.group(0)) if m else []
    except ValueError:
        arr = []
    if not arr and d['choices'][0].get('finish_reason') == 'length' and max_tokens < 16000:
        return call(prompt, usage, max_tokens * 2, temperature)   # the whole budget went to reasoning: give it more room
    return [q.strip() for q in arr if isinstance(q, str) and q.strip()]


def ko_prompt(desc, n, have=()):
    p = ('스마트 캠퍼스 에너지 관리 대시보드의 AI 비서에게 운영자나 방문자가 묻는 말을 만듭니다.\n의도: %s\n'
         '이 의도의 서로 다른 한국어 문장 %d개를 만드세요. %s 숫자나 특정 건물 id는 넣지 마세요.\n') % (desc, n, STYLE)
    if have:
        p += '이미 있는 문장(이것과 같거나 거의 같은 문장은 쓰지 마세요): ' + ' / '.join(have) + '\n'
    return p + 'JSON 문자열 배열만 출력하세요.'


def jobs_all(existing_old):
    J = {}
    for k, d in OLD.items():
        have = existing_old.get(k, [])[:12]
        J[k + '@v22'] = ko_prompt(d, 25, have)
    for k, d in NEW.items():
        J[k] = ko_prompt(d, 30)
    for b, name in BUILDINGS.items():
        for m, d in BLD_METRIC.items():
            J['q_bld_%s_%s' % (m, b)] = (
                '스마트 캠퍼스 에너지 관리 대시보드의 AI 비서에게 운영자가 묻는 질문을 만듭니다.\n'
                '건물: %s(%s). 의도: %s\n이 의도를 묻는 서로 다른 한국어 질문 10개를 만드세요. 건물은 "%s"라고 부르거나 "%s"라고 부르세요(섞어서). '
                '%s 다른 숫자는 넣지 마세요.\nJSON 문자열 배열만 출력하세요.') % (name, b, d, name, b, STYLE)
    for m, d in FLOOR_METRIC.items():
        J['q_floor_' + m] = (
            '스마트 캠퍼스 에너지 관리 대시보드의 AI 비서에게 운영자가 묻는 질문을 만듭니다.\n의도: 특정 층에 대해 %s\n'
            '서로 다른 한국어 질문 20개를 만드세요. 층은 반드시 자리표시자 "{층}"으로 쓰세요(예: "{층} 온도 알려줘"). '
            '"{층}"에는 "B1 3층", "연구동 2층" 같은 말이 들어가므로 뒤 조사는 "층"으로 끝나는 말에 맞게(은/이/에/의) 쓰세요. '
            '%s 다른 숫자는 넣지 마세요.\nJSON 문자열 배열만 출력하세요.') % (d, STYLE)
    for k, d in CONCEPT.items():
        J[k] = ('스마트 캠퍼스 에너지 관리 대시보드의 AI 비서에게 방문자가 개념이나 원리를 묻는 질문을 만듭니다.\n의도: %s\n'
                '지금 값을 묻는 질문이 아니라 뜻·원리·방식·이유를 묻는 서로 다른 한국어 질문 20개를 만드세요. %s 숫자는 넣지 마세요.\n'
                'JSON 문자열 배열만 출력하세요.') % (d, STYLE)
    for k, d in REQUEST.items():
        J[k] = ko_prompt(d, 30)
    J['q_offtopic'] = ('스마트 캠퍼스 에너지 관리 대시보드의 AI 비서에게 방문자가 던지는, 에너지·건물 운영과 전혀 관계없는 말 50개를 한국어로 만드세요. '
                       '예: 음식·맛집, 주식·코인, 연예·스포츠, 코딩·수학 숙제, 번역, 농담, 연애 상담, 여행, 영화 추천, 잡담. '
                       '인사("안녕")나 감사("고마워")는 빼세요. %s\nJSON 문자열 배열만 출력하세요.') % STYLE
    J['unknown@v22'] = ('스마트 캠퍼스 에너지 대시보드의 AI 비서는 다음 데이터만 봅니다: %s.\n'
                        '이 데이터로는 절대 답할 수 없는 운영자 질문 50개를 한국어로 만드세요. 예: 내일·다음 주 일정이나 날씨, 과거(어제·지난달·작년) 비교, '
                        '이번 달·연간 요금, 고지서·계약 정보, 특정 사람, 이 시스템을 만든 사람, 설비 제조사·수리 이력, 다른 캠퍼스, 전력 시장 가격, 탄소를 나무로 환산. '
                        '지금 시점의 값으로 답할 수 있는 질문은 넣지 마세요. %s\nJSON 문자열 배열만 출력하세요.') % (FIELDS, STYLE)
    J['followup'] = ('AI 비서와 대화하던 사용자가 바로 앞 답변에 이어서 짧게 되묻는 말 30개를 한국어로 만드세요. '
                     '앞 내용 없이는 뜻이 안 통하는 짧은 말이어야 합니다(예: 이유를 묻기, 언제까지인지 묻기, 더 자세히 말해 달라고 하기, 그래서 어떻게 되는지). '
                     '12자 이내로 짧게 쓰고, 특정 설비·숫자는 넣지 마세요.\nJSON 문자열 배열만 출력하세요.')
    for k, d in EN.items():
        n = 15
        J[k] = ('Write %d different English questions or requests an operator might type to an energy-management assistant, all about: %s. '
                'Mix short and long, casual and formal. No numbers. Output a JSON array of strings only.') % (n, d)
    J['one_ko'] = ('AI 비서에게 질문 끝에 덧붙여 "한 문장으로만 짧게 답하라"고 요구하는 한국어 지시문 24개를 만드세요. '
                   '예: 질문 뒤에 붙는 짧은 말(한 줄 요약 요청, 결론만 요청, 길게 말하지 말라는 요청). 반말·존댓말을 섞고 질문 내용은 넣지 마세요.\n'
                   'JSON 문자열 배열만 출력하세요.')
    J['one_en'] = ('Write 10 different short English instructions a user appends to a question to ask for a one-sentence answer '
                   '(e.g. asking for just the bottom line). No question content. JSON array of strings only.')
    # run 2 (train only): more varied one-line instructions, also ones that ask to summarise ("…요약해 줘")
    J['one_ko2'] = ('AI 비서에게 답을 아주 짧게 해 달라고 하는 한국어 지시문 40개를 만드세요. 질문 끝에 붙이는 말이고, 모두 "한 문장"이나 "한 줄"로 답하라는 뜻이어야 합니다. '
                    '"요약", "한마디로", "요점만", "결론만", "짧게" 같은 표현과 "한 줄"·"한 문장"을 다양하게 섞고, 반말·존댓말, 아주 짧은 것(2~4단어)도 넣으세요. 질문 내용은 넣지 마세요.\n'
                    'JSON 문자열 배열만 출력하세요.')
    J['one_en2'] = ('Write 20 different short English instructions a user appends to a question to get a one-sentence or one-line answer '
                    '(e.g. asking for a one-line summary, the gist, TL;DR, a single sentence). No question content. JSON array of strings only.')
    J['q_unknown_en'] = ('An energy dashboard assistant only sees live campus data (load, grid import, peak limit, tariff, solar, battery, EV, '
                         'buildings and floors, comfort, alarms, agents, today\'s totals). Write 20 English questions it can never answer from that '
                         '(tomorrow, last year, monthly bills, contracts, people, vendors, other sites, market prices). JSON array of strings only.')
    J['q_offtopic_en'] = ('Write 20 English messages a visitor might type to a campus energy assistant that have nothing to do with energy or buildings '
                          '(food, stocks, sports, homework, jokes, travel, movies). No greetings or thanks. JSON array of strings only.')
    return J


def main():
    out = Path(sys.argv[1])
    only = set()
    if '--only' in sys.argv:
        only = set(sys.argv[sys.argv.index('--only') + 1].split(','))
    data = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {}
    old = json.loads((HERE.parent / 'data' / 'paraphrases.json').read_text(encoding='utf-8'))
    J = jobs_all(old)
    todo = {k: p for k, p in J.items() if (k in only) or (not only and k not in data)}
    print('jobs', len(J), 'to run', len(todo), flush=True)
    if '--dry' in sys.argv:
        for k, p in list(todo.items())[:3]:
            print(k, p[:300])
        return
    upath = out.with_name(out.stem + '_usage.json')
    usage = json.loads(upath.read_text()) if upath.exists() else {'prompt_tokens': 0, 'completion_tokens': 0, 'calls': 0}
    usage.setdefault('calls', 0)

    def run(item):
        k, p = item
        return k, call(p, usage)
    with ThreadPoolExecutor(6) as ex:
        for k, qs in ex.map(run, todo.items()):
            data[k] = sorted(set(qs), key=qs.index)
            print(k, len(data[k]), data[k][:2], flush=True)
            out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
            upath.write_text(json.dumps(usage, indent=1))
    print('usage', usage)


if __name__ == '__main__':
    main()
