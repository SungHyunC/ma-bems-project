"""Build fine-tuning data for the MA-BEMS assistant from simulator contexts (collect.mjs output).

    python make_data.py samples_train.jsonl train.jsonl [seed]

Each record is {"task", "kind", "messages": [system, user, assistant]} in exactly the format the gateway sends
(server/mabems_server.py chat(): system = SYSTEM_BASE + task note, user = <campus_state>…</campus_state> + question).
The assistant turns are written by rules from the context itself, so every number in them is a number in the data:
  chat     ~12 question types (peak headroom, cost, buildings, ESS, PV, comfort, agents, weather, DR, faults,
           forecast) plus questions the data cannot answer ("데이터에 없음"), a few in English
  brief    3-5 bullet briefing (load and headroom, tariff, the agents' latest actions, the next hour)
  explain  the selected building / zone / room
  propose  JSON proposals from an explicit policy (below), or none when nothing needs doing
Answers follow the system prompt's format: one conclusion sentence, then 2-4 lines starting with '- '.
"""
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
from mabems_server import SYSTEM_BASE, TASKS  # noqa: E402

TEMPS = ['%g' % (22 + 0.5 * i) for i in range(13)]


def n(x):
    """A number exactly as it appears in the data, with thousands separators (no new rounding)."""
    if x is None:
        return None
    if isinstance(x, int) or (isinstance(x, float) and x.is_integer()):
        return '{:,}'.format(int(round(x)))
    s = repr(float(x))
    if 'e' in s:
        s = '%.3f' % x
    head, _, tail = s.partition('.')
    sign = '-' if head.startswith('-') else ''
    return sign + '{:,}'.format(int(head.lstrip('-'))) + '.' + tail


def money(c, v):
    return ('₩' + n(v)) if c.get('tariff', {}).get('currency') == '₩' else ('$' + n(v))


def dec(c, who=None, k=1):
    """Latest decision log lines (optionally from one agent), with the agent prefix and clock kept."""
    out = [d for d in c.get('recentDecisions', []) if who is None or who in d]
    return out[-k:]


def short(d, limit=110):
    """A decision-log line without its clock, the agent's repeated prefix, and segments whose SOC or cap value
    belongs to an earlier minute (the number check holds those labels to the current value)."""
    d = re.sub(r'^\d{2}:\d{2}\s+', '', d)
    d = re.sub(r'^([^:]+): (?:EV|ESS|PV|HVAC|코디네이터|조명): ', r'\1: ', d)
    d = ' · '.join(s for s in d.split(' · ') if not re.search(r'SOC|상한|한도', s))
    return d if len(d) <= limit else d[:limit].rsplit(' ', 1)[0] + '…'


def ess_desc(cp):
    p = cp.get('essNowKW') or 0
    if p > 1:
        return 'ESS가 %s kW 방전 중' % n(p)
    if p < -1:
        return 'ESS가 %s kW 충전 중' % n(-p)
    return 'ESS는 대기 중'


def tier_name(c):
    t = c.get('tariff', {})
    tier = t.get('tier')
    return tier.get('name') if isinstance(tier, dict) else str(tier)


def fc_line(c):
    f = c.get('forecast') or {}
    if f.get('next4hMaxKW') is not None:
        return '향후 4시간 최대 %s kW가 %s에 예상되며 한도의 %s%% 수준입니다' % (n(f['next4hMaxKW']), f.get('next4hMaxAt'), n(f.get('next4hMaxPctOfLimit')))
    return None


def bullets(lines, lo=2, hi=4):
    lines = [l for l in lines if l][:hi]
    return '\n'.join('- ' + l for l in lines) if len(lines) >= lo else '\n'.join('- ' + l for l in lines)


# ---------------------------------------------------------------- chat
def q_peak(c, r):
    cp = c['campus']
    g, lim, h, pct = cp['gridImportNowKW'], cp['peakLimitKW'], cp['headroomNowKW'], cp['headroomNowPct']
    b1 = c['buildingsByLoad'][0]
    if h >= 0:
        head = r.choice(['{t} 현재 계통 수전은 {g} kW로, 피크 한도 {l} kW까지 {h} kW({p}%) 여유가 있습니다.',
                         '피크 한도 {l} kW까지 {h} kW({p}%)가 남았습니다 — {t} 현재 계통 수전 {g} kW 기준입니다.']).format(
            t=c['clock'], g=n(g), l=n(lim), h=n(h), p=n(pct))
    else:
        head = '%s 현재 계통 수전 %s kW로 피크 한도 %s kW를 넘었습니다.' % (c['clock'], n(g), n(lim))
    dr = c.get('demandResponse') or {}
    lines = ['캠퍼스 부하 %s kW 중 태양광 %s kW를 자체 소비하고, %s입니다' % (n(cp['loadNowKW']), n(cp['pvNowKW']), ess_desc(cp)),
             '가장 큰 부하는 %s(%s) %s kW이고 냉동기가 %s kW를 쓰고 있습니다' % (b1['name'], b1['id'], n(b1['loadKW']), n(cp['chillerNowKW'])),
             fc_line(c) or '향후 4시간 피크 예측은 아직 데이터에 없습니다']
    if dr.get('active'):
        lines.insert(0, 'DR 진행 중: %s–%s, %s kW 감축 요청' % (dr.get('start'), dr.get('end'), n(dr.get('shedKW'))))
    return head + '\n' + bullets(lines)


def q_cost(c, r):
    t, cur = c['today'], c
    head = '%s까지 오늘 비용은 %s로, 같은 조건의 룰 기반 BMS(%s)보다 %s%% 적습니다.' % (c['clock'], money(cur, t['costAgent']), money(cur, t['costBaseline']), n(t['savingsPct']))
    if t['savingsPct'] < 0:
        head = '%s까지 오늘 비용은 %s로, 룰 기반 BMS(%s)보다 많습니다.' % (c['clock'], money(cur, t['costAgent']), money(cur, t['costBaseline']))
    sym = '₩' if c['tariff'].get('currency') == '₩' else '$'
    lines = ['오늘 사용 전력량은 %s kWh입니다' % n(t['energyKWh']),
             '지금은 %s 요금 구간으로 %s%s/kWh입니다' % (tier_name(c), sym, n(c['tariff']['pricePerKWh'])),
             '오늘 최대 수전은 %s kW였습니다(한도 %s kW)' % (n(t['highestGridImportTodayKW']), n(c['campus']['peakLimitKW']))]
    return head + '\n' + bullets(lines, hi=3)


def q_top(c, r):
    b = c['buildingsByLoad']
    b1, b2 = b[0], b[1]
    parts = ['냉방 %s kW' % n(b1['hvacKW']), '콘센트 %s kW' % n(b1['plugKW']), '조명 %s kW' % n(b1['lightKW'])]
    if b1.get('itKW'):
        parts.insert(0, 'IT %s kW' % n(b1['itKW']))
    head = '지금 가장 많이 쓰는 건물은 %s(%s)로 %s kW입니다.' % (b1['name'], b1['id'], n(b1['loadKW']))
    lines = ['구성: ' + ' · '.join(parts),
             '두 번째는 %s(%s) %s kW입니다' % (b2['name'], b2['id'], n(b2['loadKW'])),
             '%s의 재실률은 %s%%(%s명)입니다' % (b1['id'], n(b1['occupancyPct']), n(b1['people']))]
    if b1['id'] == 'B4':
        lines.append('데이터센터 냉방은 운영 규칙상 줄이지 않습니다')
    return head + '\n' + bullets(lines)


def q_ess(c, r):
    cp = c['campus']
    head = '%s이고, 충전 상태(SOC)는 %s%%입니다.' % (ess_desc(cp), n(cp['essSocPct']))
    lines = ['지금은 %s 요금 구간입니다(피크 시간 %s)' % (tier_name(c), c['tariff']['peakHours'])]
    d = dec(c, 'ESS 에이전트')
    if d:
        lines.append('최근 ESS 에이전트 조치: ' + short(d[0]))
    lines.append('계통 수전 %s kW, 한도 %s kW입니다' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW'])))
    return head + '\n' + bullets(lines)


def q_pv(c, r):
    cp, w = c['campus'], c['weather']
    head = '태양광은 지금 %s kW를 발전하고 있습니다.' % n(cp['pvNowKW'])
    lines = ['일사량은 %s W/m²입니다' % n(w['irradianceWm2'])]
    d = dec(c, '태양광 에이전트')
    if d:
        lines.append('태양광 에이전트: ' + short(d[0]).split(': ', 1)[-1])
    lines.append('캠퍼스 부하는 %s kW입니다' % n(cp['loadNowKW']))
    return head + '\n' + bullets(lines)


def q_comfort(c, r):
    t = c['today']
    head = '오늘 쾌적 범위 유지율은 %s%%이고, 지금 %s개 구역 중 %s개가 범위 안에 있습니다.' % (n(t['comfortPct']), n(t['zonesCounted']), n(t['zonesInBand']))
    lines = ['쾌적 범위는 설정온도 ±1.5 °C 기준입니다']
    z = [x for x in c.get('zonesNeedingAttention', []) if x.get('inBand') is False] or c.get('zonesNeedingAttention', [])
    for x in z[:2]:
        lines.append('%s: %s °C(설정 %s °C), 재실 %s%%' % (x['id'], n(x['tempC']), n(x['setpointC']), n(x['occupancyPct'])))
    al = [a for a in c.get('alerts', []) if '쾌적' in a]
    if al:
        lines.append('경보: ' + al[0].split(': ', 1)[-1])
    return head + '\n' + bullets(lines)


def q_agents(c, r):
    ag = c.get('agents', [])
    stage = ag[0].split(': ', 1)[-1] if ag else '데이터에 없음'
    head = '여섯 에이전트는 지금 %s 상태이고, 최근 조치는 다음과 같습니다.' % stage
    return head + '\n' + bullets([short(d) for d in dec(c, k=3)], hi=3)


def q_weather(c, r):
    w, cp = c['weather'], c['campus']
    b = sorted(c['buildingsByLoad'], key=lambda x: -x['hvacKW'])[0]
    head = '바깥 기온은 %s °C, 일사량은 %s W/m²입니다.' % (n(w['outdoorC']), n(w['irradianceWm2']))
    lines = ['냉동기가 %s kW를 쓰고 있습니다' % n(cp['chillerNowKW']),
             '냉방이 가장 큰 건물은 %s(%s) %s kW입니다' % (b['name'], b['id'], n(b['hvacKW'])),
             '일사 덕분에 태양광이 %s kW를 냅니다' % n(cp['pvNowKW'])]
    return head + '\n' + bullets(lines)


def q_dr(c, r):
    dr, dm = c.get('demandResponse') or {}, (c.get('dayMetrics') or {}).get('agent') or {}
    if dr.get('active'):
        head = '네, DR 이벤트가 진행 중입니다: %s–%s 동안 %s kW 감축 요청입니다.' % (dr.get('start'), dr.get('end'), n(dr.get('shedKW')))
        lines = ['발령 주체: %s' % dr.get('source'), '지금 계통 수전은 %s kW입니다' % n(c['campus']['gridImportNowKW'])]
        d = dec(c, '코디네이터')
        if d:
            lines.append(short(d[0]))
    else:
        head = '아니요, 지금 진행 중인 DR 이벤트는 없습니다.'
        lines = []
        if dm.get('drRequestedKWh'):
            lines.append('오늘 DR 요청 %s kWh 중 %s kWh를 감축했습니다' % (n(dm['drRequestedKWh']), n(dm['drDeliveredKWh'])))
        lines += ['계통 수전 %s kW, 한도 %s kW입니다' % (n(c['campus']['gridImportNowKW']), n(c['campus']['peakLimitKW'])),
                  'DR이 오면 코디네이터가 ESS → EV → 조명 → HVAC 순서로 감축을 나눕니다']
    return head + '\n' + bullets(lines)


def q_faults(c, r):
    f = c.get('faults') or {}
    oa = f.get('openAlarms') or []
    al = c.get('alerts') or []
    if oa:
        head = '센서 이상 경보가 %s건 열려 있습니다.' % n(len(oa))
        kind = {'stuck': '고착', 'drift': '드리프트', 'dropout': '끊김'}
        state = {'pending': '운영자 승인 대기', 'virtual': '가상 센서로 대체 중'}
        lines = ['%s: 온도 센서 %s 의심 — 측정 %s °C, 가상 센서 %s °C (%s)' % (a.get('room'), kind.get(a.get('type'), a.get('type')), n(a.get('measuredC')), n(a.get('virtualC')), state.get(a.get('state'), a.get('state')))
                 if isinstance(a, dict) else str(a) for a in oa[:2]]
        lines.append('경보를 승인하면 그 방은 가상 센서로 제어합니다')
    else:
        head = '지금 열린 센서 이상 경보는 없습니다.'
        lines = ['경보: ' + a.split(': ', 1)[-1] for a in al[:2]] or ['다른 운영 경보도 없습니다']
        lines.append('고장 감지는 5분마다 각 실 온도 센서를 확인합니다')
    return head + '\n' + bullets(lines)


def q_forecast(c, r):
    f = c.get('forecast') or {}
    if f.get('next4hMaxKW') is None:
        return '향후 4시간 피크 예측은 아직 데이터에 없습니다.\n' + bullets([
            '예측 모델이 학습할 데이터가 더 쌓여야 합니다',
            '지금 계통 수전은 %s kW, 한도는 %s kW입니다' % (n(c['campus']['gridImportNowKW']), n(c['campus']['peakLimitKW']))])
    head = '향후 4시간 최대 수전은 %s kW로 %s에 예상되며, 한도의 %s%%입니다.' % (n(f['next4hMaxKW']), f.get('next4hMaxAt'), n(f.get('next4hMaxPctOfLimit')))
    lines = ['예측 방법: %s' % f.get('method')]
    if f.get('band90KW') is not None:
        lines.append('예측 불확실성 폭은 ±%s kW입니다' % n(f['band90KW']))
    acc = f.get('accuracy1hAhead')
    if acc:
        lines.append('1시간 앞 예측 정확도: CV(RMSE) %s%%, NMBE %s%%' % (n(acc.get('cvrmsePct')), n(acc.get('nmbePct'))))
    return head + '\n' + bullets(lines)


def q_unknown(c, r, q):
    return ('그 정보는 데이터에 없어 답할 수 없습니다.\n' + bullets([
        '지금 데이터에는 %s 시점의 운영 값만 있습니다' % c['clock'],
        '예: 바깥 기온 %s °C, 오늘 비용 %s' % (n(c['weather']['outdoorC']), money(c, c['today']['costAgent'])),
        '%s에 대해서는 지어내지 않겠습니다' % q]))


def q_peak_en(c, r):
    cp = c['campus']
    head = 'At %s grid import is %s kW, so %s kW (%s%%) is left below the %s kW peak limit.' % (c['clock'], n(cp['gridImportNowKW']), n(cp['headroomNowKW']), n(cp['headroomNowPct']), n(cp['peakLimitKW']))
    if cp['headroomNowKW'] < 0:
        head = 'At %s grid import is %s kW, above the %s kW peak limit.' % (c['clock'], n(cp['gridImportNowKW']), n(cp['peakLimitKW']))
    b1 = c['buildingsByLoad'][0]
    lines = ['Campus load %s kW, solar %s kW, battery %s kW (positive = discharging)' % (n(cp['loadNowKW']), n(cp['pvNowKW']), n(cp['essNowKW'])),
             'Largest load: %s %s kW; chiller %s kW' % (b1['id'], n(b1['loadKW']), n(cp['chillerNowKW']))]
    return head + '\n' + bullets(lines)


def q_cost_en(c, r):
    t = c['today']
    head = 'Cost so far today is %s against %s for the rule-based BMS, %s%% lower.' % (money(c, t['costAgent']), money(c, t['costBaseline']), n(t['savingsPct']))
    lines = ['Energy today: %s kWh' % n(t['energyKWh']), 'Highest grid import today: %s kW (limit %s kW)' % (n(t['highestGridImportTodayKW']), n(c['campus']['peakLimitKW']))]
    return head + '\n' + bullets(lines)


CHAT = [
    (q_peak, ['피크 한도까지 여유가 얼마나 남았어?', '지금 한도 넘을 위험 있어?', '수전 여유 알려줘', '피크 여유?']),
    (q_cost, ['오늘 비용은 얼마고 기준 BMS보다 얼마나 아꼈어?', '오늘 전기요금 얼마나 절감했어?', '비용 절감 현황 알려줘']),
    (q_top, ['지금 전력을 제일 많이 쓰는 건물은 어디야?', '어느 건물이 부하가 제일 커?']),
    (q_ess, ['배터리(ESS) 상태 알려줘', 'ESS 지금 뭐 하고 있어?']),
    (q_pv, ['태양광 발전은 지금 얼마나 돼?', 'PV 발전량 알려줘']),
    (q_comfort, ['지금 쾌적성은 괜찮아?', '더운 구역 있어?']),
    (q_agents, ['에이전트들이 지금 뭐 하고 있어?', '최근에 어떤 조치를 했어?']),
    (q_weather, ['바깥 날씨가 부하에 어떤 영향을 줘?', '날씨 때문에 냉방이 많이 돌아?']),
    (q_dr, ['DR(수요반응) 이벤트 진행 중이야?', 'DR 상황 알려줘']),
    (q_faults, ['센서 고장이나 경보 있어?', '이상 감지된 거 있어?']),
    (q_forecast, ['앞으로 4시간 피크 예측은 어때?', '오후 피크 예측 알려줘']),
    (q_peak_en, ['How much headroom is left to the peak limit?']),
    (q_cost_en, ['How much have we saved today compared with the BMS?']),
]
UNKNOWN = ['내일 날씨는 어때?', '이번 달 전기요금 고지서는 얼마야?', '작년 같은 날과 비교하면 어때?', '건물별 탄소 배출권 가격은?', '다음 주 DR 일정 알려줘']


# ---------------------------------------------------------------- brief
def brief(c, r):
    cp = c['campus']
    lines = ['부하·여유: 캠퍼스 부하 %s kW, 계통 수전 %s kW로 한도 %s kW까지 %s kW(%s%%) 여유' % (n(cp['loadNowKW']), n(cp['gridImportNowKW']), n(cp['peakLimitKW']), n(cp['headroomNowKW']), n(cp['headroomNowPct']))
             if cp['headroomNowKW'] >= 0 else '부하·한도: 계통 수전 %s kW로 한도 %s kW 초과' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW'])),
             '요금: %s 구간(피크 %s), 태양광 %s kW, %s(SOC %s%%)' % (tier_name(c), c['tariff']['peakHours'], n(cp['pvNowKW']), ess_desc(cp), n(cp['essSocPct']))]
    dr = c.get('demandResponse') or {}
    if dr.get('active'):
        lines.append('DR 진행 중: %s–%s, %s kW 감축 요청' % (dr.get('start'), dr.get('end'), n(dr.get('shedKW'))))
    for d in dec(c, k=2):
        lines.append('조치: ' + short(d, 120))
    lines.append('앞으로 1시간: ' + (fc_line(c) or '피크 예측 데이터가 아직 없어 현재 여유를 계속 확인합니다'))
    return '\n'.join('- ' + l for l in lines[:5])


# ---------------------------------------------------------------- explain
def explain(c, sel, r):
    k = sel.get('kind')
    if k == 'building':
        parts = ['냉방 %s' % n(sel['hvacKW']), '콘센트 %s' % n(sel['plugKW']), '조명 %s' % n(sel['lightKW'])] + (['IT %s' % n(sel['itKW'])] if sel.get('itKW') else [])
        head = '%s는 지금 %s kW를 쓰고 있습니다(%s kW).' % (sel['label'], n(sel['loadKW']), ' · '.join(parts))
        off = sel.get('setpointOffsetC') or 0
        lines = ['재실률 %s%%(%s명), 태양광 %s kW' % (n(sel['occupancyPct']), n(sel['people']), n(sel['pvKW'])),
                 '에이전트 설정온도 조정: ' + ('+%s °C 완화 중' % n(off) if off > 0 else '%s °C 사전 냉방 중' % n(off) if off < 0 else '조정 없음')]
        bad = [z for z in sel.get('zones', []) if z.get('inBand') is False]
        lines.append('쾌적 범위를 벗어난 층: ' + ', '.join('%s %s °C' % (z['id'], n(z['tempC'])) for z in bad[:3]) if bad else '모든 층이 쾌적 범위 안에 있습니다')
        lines.append('데이터센터 냉방은 줄이지 않습니다' if sel['id'] == 'B4' else '필요하면 층별 설정온도를 허용 범위 안에서 조정할 수 있습니다')
        return head + '\n' + bullets(lines)
    if k == 'zone':
        ok = sel.get('inBand')
        head = '%s 층은 %s °C(설정 %s °C)로 %s.' % (sel['id'], n(sel['tempC']), n(sel['setpointC']), '쾌적 범위 안에 있습니다' if ok else '쾌적 범위를 벗어났습니다')
        rooms = sel.get('rooms') or []
        empty = [x for x in rooms if x and not x.get('people')]
        lines = ['재실률 %s%%, 전력 %s kW' % (n(sel['occupancyPct']), n(sel['kW'])),
                 '방 %s곳 중 %s곳이 비어 있습니다' % (n(len(rooms)), n(len(empty)))]
        if sel.get('userSetpointC') is not None and sel['userSetpointC'] != sel['setpointC']:
            lines.append('운영자 설정 %s °C에 에이전트 조정이 더해져 %s °C로 운전 중입니다' % (n(sel['userSetpointC']), n(sel['setpointC'])))
        lines.append('설정온도는 허용 범위 안에서 바꿀 수 있습니다' if not sel['id'].startswith('B4') else '데이터센터 층 냉방은 줄이지 않습니다')
        return head + '\n' + bullets(lines)
    R = sel.get('room') or {}
    mode = {'cooling': '냉방 중', 'setback': '셋백(절약 운전)', 'off': '공조 꺼짐'}.get(R.get('hvacMode'), R.get('hvacMode'))
    head = '%s(%s)은 지금 %s명, %s °C(설정 %s °C)이고 %s kW를 씁니다.' % (R.get('name'), R.get('id'), n(R.get('people') or 0), n(R.get('tempC')), n(R.get('setpointC')), n(R.get('kW')))
    lines = ['공조: %s, 조명 %s(%s%%), 콘센트 %s' % (mode, R.get('lights'), n(R.get('lightLevelPct')), R.get('plugMode'))]
    if R.get('vacantMin'):
        lines.append('%s분째 비어 있습니다' % n(R['vacantMin']))
    if R.get('lastAction'):
        lines.append('최근 조치: ' + R['lastAction'])
    lines.append('필요하면 이 방의 설정온도나 조명(auto·on·off)을 바꿀 수 있습니다')
    return head + '\n' + bullets(lines)


# ---------------------------------------------------------------- propose
def propose(p, r):
    """Policy: (1) under pressure (DR, headroom < 12 %, forecast ≥ 95 % of the limit, or peak tariff with < 20 % headroom)
    relax low-occupancy zones by 1 °C (max 27 °C); (2) empty rooms with lights on → lights off; (3) empty rooms still in
    full cooling, outside zones being pre-conditioned for a booking → setback (+2 °C, max 28 °C). Nothing that would not
    change anything. B4 and cold rooms are never candidates."""
    cp, f, dr = p['campus'], p.get('forecast') or {}, p.get('demandResponse') or {}
    tier = (p['tariff'].get('tier') or {}).get('tier') if isinstance(p['tariff'].get('tier'), dict) else p['tariff'].get('tier')
    pct = cp['headroomNowPct']
    fpct = f.get('next4hMaxPctOfLimit')
    pressure = dr.get('active') or pct < 12 or (fpct is not None and fpct >= 95) or (tier == 'peak' and pct < 20)
    precond = set(re.findall(r'(B\d-F\d+) \d{2}:\d{2} 회의 예약', ' '.join(p.get('recentDecisions', []))))
    why_p = ('DR %s kW 감축 요청 중' % n(dr.get('shedKW')) if dr.get('active') else
             '한도 여유 %s%%(%s kW)' % (n(pct), n(cp['headroomNowKW'])) if pct < 12 or tier == 'peak' else
             '향후 4시간 최대 %s kW(한도의 %s%%) 예측' % (n(f.get('next4hMaxKW')), n(fpct)))
    acts = []
    if pressure:
        for z in sorted(p.get('candidateZones', []), key=lambda z: -z['kW']):
            if z['occupancyPct'] < 60 and z['tempC'] <= z['setpointC'] + 0.7 and z['setpointC'] < 27:
                v = min(27.0, round((z['setpointC'] + 1.0) * 2) / 2)
                acts.append({'type': 'setpoint', 'target': z['id'], 'value': '%g' % v,
                             'expected_effect': '%s 냉방 부하를 줄여 피크 여유를 늘림' % z['id'],
                             'reason': '%s, 재실 %s%%로 낮고 %s °C(설정 %s °C)라 1 °C 완화 여지가 있음' % (why_p, n(z['occupancyPct']), n(z['tempC']), n(z['setpointC']))})
            if len(acts) >= 2:
                break
    rooms = sorted(p.get('candidateRooms', []), key=lambda x: -x['kW'])
    for x in rooms:
        if len(acts) >= 4:
            break
        if not x.get('people') and x.get('lights') != 'off' and (x.get('lightLevelPct') or 0) >= 50:
            acts.append({'type': 'roomLights', 'target': x['id'], 'value': 'off',
                         'expected_effect': '빈 방 조명 전력 절감',
                         'reason': '재실 0명인데 조명이 %s%% 켜져 있음' % n(x['lightLevelPct'])})
    for x in rooms:
        if len(acts) >= 4:
            break
        zone = x['id'].rsplit('-', 1)[0]
        if not x.get('people') and x.get('hvacMode') == 'cooling' and zone not in precond and x['setpointC'] < 27.5:
            v = min(28.0, round((x['setpointC'] + 2.0) * 2) / 2)
            if any(a['target'] == x['id'] for a in acts):
                continue
            acts.append({'type': 'roomSetpoint', 'target': x['id'], 'value': '%g' % v,
                         'expected_effect': '빈 방 냉방을 셋백으로 낮춰 %s kW 중 일부 절감' % n(x['kW']),
                         'reason': '재실 0명인데 %s °C(설정 %s °C)로 냉방 중이고 회의 예약 사전 공조 대상이 아님' % (n(x['tempC']), n(x['setpointC']))})
    acts = acts[:4]
    if acts:
        kinds = []
        if any(a['type'] == 'setpoint' for a in acts):
            kinds.append('재실이 낮은 층의 설정온도를 1 °C 올려 피크 여유를 확보')
        if any(a['type'] == 'roomLights' for a in acts):
            kinds.append('빈 방 조명을 끄기')
        if any(a['type'] == 'roomSetpoint' for a in acts):
            kinds.append('빈 방 냉방을 셋백')
        summary = ', '.join(kinds) + '를 제안합니다.'
    else:
        summary = '지금은 바꿀 필요가 없습니다: 한도 여유 %s%%(%s kW), 빈 방들은 이미 셋백·소등 상태입니다.' % (n(pct), n(cp['headroomNowKW']))
    return {'summary': summary, 'actions': acts}


# ---------------------------------------------------------------- assemble
def msg(task, ctx, question, answer):
    system = SYSTEM_BASE + TASKS[task]['note']
    user = '<campus_state>\n' + ctx + '\n</campus_state>\n\n' + question
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}, {'role': 'assistant', 'content': answer}]


def build(samples, seed, mix):
    r = random.Random(seed)
    out = []
    for s in samples:
        c, p = json.loads(s['chat']), json.loads(s['propose'])
        if r.random() < mix['propose']:
            out.append({'task': 'propose', 'kind': 'propose', 'messages': msg('propose', s['propose'], '앞으로 1시간 동안의 제어 조치를 제안해 줘.', json.dumps(propose(p, r), ensure_ascii=False))})
        if r.random() < mix['brief']:
            out.append({'task': 'brief', 'kind': 'brief', 'messages': msg('brief', s['chat'], '현재 운영 상황을 브리핑해 줘.', brief(c, r))})
        if s.get('explain') and r.random() < mix['explain']:
            e = s['explain']
            sel = json.loads(e['ctx'])['selected']
            out.append({'task': 'explain', 'kind': 'explain-' + e['kind'], 'messages': msg('explain', e['ctx'], '설명해 줘: ' + sel.get('label', e['id']), explain(c, sel, r))})
        for _ in range(mix['chat']):
            if r.random() < 0.1:
                q = r.choice(UNKNOWN)
                out.append({'task': 'chat', 'kind': 'unknown', 'messages': msg('chat', s['chat'], q, q_unknown(c, r, q))})
            else:
                fn, qs = r.choice(CHAT)
                out.append({'task': 'chat', 'kind': fn.__name__, 'messages': msg('chat', s['chat'], r.choice(qs), fn(c, r))})
    r.shuffle(out)
    return out


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    samples = [json.loads(l) for l in open(src, encoding='utf-8')]
    mix = {'propose': 0.45, 'brief': 0.25, 'explain': 0.3, 'chat': 1}
    rows = build(samples, seed, mix)
    with open(dst, 'w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    from collections import Counter
    print(dst, len(rows), dict(Counter(x['task'] for x in rows)))
