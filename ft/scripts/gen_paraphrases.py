"""Question paraphrases for the v2 data, written by an open-weight model on Fireworks (not Claude: the v1 decision
to keep Claude output out of the training data stands). Only questions are generated; answers stay rule-written.

    FIREWORKS_API_KEY=... python gen_paraphrases.py paraphrases.json
"""
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MODEL = 'accounts/fireworks/models/deepseek-v4p1-flash'
KEY = os.environ['FIREWORKS_API_KEY']

FIELDS = ('현재 시각, 요금 구간·단가·피크 시간대, 바깥 기온·일사량, 캠퍼스 부하·계통 수전·피크 한도·여유, 태양광 발전, '
          'ESS 충·방전·SOC, EV 충전 전력, 냉동기 전력, 오늘 누적 전력량·비용·룰 기반 BMS 대비 절감률·오늘 최대 수전·쾌적 유지율, '
          '건물별 부하(냉방·조명·콘센트·IT)·재실, 주의 구역 온도, DR 이벤트, 경보, 에이전트 상태와 최근 조치 로그, '
          '오늘 탄소 배출량·EV 충전 세션·태양광 자가소비율, 향후 4시간 피크 예측, 센서 고장 경보')

INTENTS = {
    'q_peak': '지금 계통 수전이 피크 한도까지 얼마나 여유가 있는지 / 한도를 넘을 위험이 있는지',
    'q_cost': '오늘 지금까지의 전기요금과 룰 기반 BMS 대비 절감액·절감률',
    'q_top': '지금 전력을 가장 많이 쓰는 건물이 어디인지',
    'q_ess': '배터리(ESS)가 지금 충전/방전 중인지와 충전 상태(SOC)',
    'q_pv': '태양광이 지금 얼마나 발전하고 있는지',
    'q_comfort': '실내 쾌적성 상태, 덥거나 범위를 벗어난 구역이 있는지',
    'q_agents': '에이전트들이 지금 무엇을 하고 있고 최근 어떤 조치를 했는지',
    'q_weather': '바깥 날씨(기온·일사)가 전력 부하나 냉방에 어떤 영향을 주는지',
    'q_dr': '수요반응(DR) 이벤트가 진행 중인지',
    'q_faults': '센서 고장이나 이상 경보가 있는지',
    'q_forecast': '앞으로 몇 시간의 피크(최대 수전) 예측',
    'q_tariff': '요금이 가장 비싼 시간대(피크 요금 시간)와 지금 요금 구간·단가',
    'q_temp': '지금 바깥 기온이 몇 도인지 (영향 말고 값 자체)',
    'q_maxtoday': '오늘 지금까지 가장 높았던 계통 수전(최대 수요)과 한도 초과 여부',
    'q_co2': '오늘 지금까지의 탄소(CO2) 배출량',
    'q_ev': '전기차(EV) 충전 현황',
    'q_pvself': '태양광 발전량 중 자체 소비 비율(자가소비율)과 오늘 발전량',
}
EN = {
    'q_peak_en': 'how much headroom is left to the peak limit right now',
    'q_cost_en': 'how much money was saved today compared with the rule-based BMS',
}


def call(prompt, max_tokens=4000):
    body = {'model': MODEL, 'max_tokens': max_tokens, 'temperature': 0.9, 'reasoning_effort': 'low',
            'messages': [{'role': 'user', 'content': prompt}]}
    req = urllib.request.Request('https://api.fireworks.ai/inference/v1/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    text = d['choices'][0]['message'].get('content') or ''
    m = re.search(r'\[.*\]', text, re.S)
    return [q.strip() for q in json.loads(m.group(0)) if isinstance(q, str) and q.strip()] if m else []


def ko(key, desc):
    p = ('스마트 캠퍼스 에너지 관리 대시보드의 AI 비서에게 운영자가 묻는 질문을 만듭니다.\n'
         '의도: %s\n이 의도를 묻는 서로 다른 한국어 질문 30개를 만드세요. 반말·존댓말, 아주 짧은 것(3~5단어)과 긴 것, '
         '실무자 말투, 오타 없는 구어체를 섞고, 같은 문장 구조를 반복하지 마세요. 숫자나 특정 건물 id는 넣지 마세요.\n'
         'JSON 문자열 배열만 출력하세요.') % desc
    return key, call(p)


def en(key, desc):
    p = ('Write 15 different English questions an operator might ask an energy-management assistant, all asking: %s. '
         'Mix short and long, casual and formal. No numbers. Output a JSON array of strings only.') % desc
    return key, call(p)


def unknown():
    p = ('스마트 캠퍼스 에너지 대시보드의 AI 비서는 다음 데이터만 봅니다: %s.\n'
         '이 데이터로는 절대 답할 수 없는 운영자 질문 60개를 한국어로 만드세요. 예: 내일·다음 주 일정이나 날씨, 과거(어제·작년·지난달) 비교, '
         '고지서·계약 정보, 특정 사람, 설비 제조사·수리 이력, 다른 캠퍼스, 시장 가격. 지금 시점의 값으로 답할 수 있는 질문은 넣지 마세요. '
         'JSON 문자열 배열만 출력하세요.') % FIELDS
    return 'unknown', call(p, 6000)


if __name__ == '__main__':
    jobs = [(ko, k, d) for k, d in INTENTS.items()] + [(en, k, d) for k, d in EN.items()]
    out = {}
    with ThreadPoolExecutor(8) as ex:
        futs = [ex.submit(f, k, d) for f, k, d in jobs] + [ex.submit(unknown)]
        for f in futs:
            k, qs = f.result()
            out[k] = sorted(set(qs), key=qs.index)
            print(k, len(out[k]), out[k][:3], flush=True)
    json.dump(out, open(sys.argv[1], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
