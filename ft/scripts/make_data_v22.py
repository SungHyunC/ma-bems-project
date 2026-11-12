"""v2.2 fine-tuning data: rule-written answers on fresh dashboard contexts, aimed at what v2.1 got wrong.

    python make_data_v22.py <samples_train.jsonl> <samples_eval.jsonl> <out_dir> [--check-only]

Every answer is still written by rules in this file from the context the model sees (no Claude output in the data);
question phrasings come from an open model on Fireworks (gen_paraphrases.py, gen_paraphrases_v22.py).

What changes from v2.1 (ft/README.md "v2.2"):
  1. Only lines that belong to the question. v2.1's templates mixed in loosely related figures, and the model copied the
     habit into answers for questions it had no template for ("연구동 냉방 전력은?" → a PV figure on the cooling line,
     "냉동기 전력" → "1,0157 kWh"). Each answer here carries the asked figure and its own context, nothing else, and every
     reference answer must pass the gateway's stricter number check (server/numcheck.py: values bound to their labels).
  2. New question kinds from the 66 visitor questions (ft/data/realq.json, never trained on): a building's or a floor's
     own figures, the chiller, the time of today's peak, the hottest / coolest floor, empty rooms with lights on, EV counts,
     the scenario, why the battery does what it does, savings in money, concept questions answered from the glossary the
     gateway adds (assist.augment), off-topic chat, short follow-ups and earlier turns in the conversation.
  3. Contexts exactly as the model receives them: the page context passed through the gateway (augment → answerFacts and
     glossary for chat, model_view → no tariff timetable). Questions the page or the gateway answers without the model
     (commands, small talk, timetable lookups, definitions, the forecast verdict) are left out.
  4. Proposals: the same policy, but (a) "already handled" rooms look like real ones (setback rooms have raised setpoints,
     v2.1's copies kept the cooling setpoint), (b) more contrast: all rooms handled, half, all but one, (c) the text the
     model writes first says why (pressure, the room id) before the target, (d) typed requests ("에어컨 좀 약하게") with
     only the action kinds the gateway allows for them, (e) English requests.
Outputs (out_dir): train_v22.jsonl and the held-out sets eval22_chat.jsonl, eval22_tasks.jsonl, eval22_nothing.jsonl,
eval22_request.jsonl (other simulator seeds and held-out phrasings), questions_split.json, stats.json. (Prefixed names:
modal_ft.py uploads data files flat into the volume's data/, next to v1's train.jsonl and v2's eval_nothing.jsonl.)
"""
import difflib
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'server'))
import make_data as v1  # noqa: E402
from make_data import n, money, tier_name, ess_desc, short, dec  # noqa: E402
import numcheck  # noqa: E402
import assist  # noqa: E402
from mabems_server import SYSTEM_BASE, TASKS  # noqa: E402

PROPOSE_Q = '앞으로 1시간 동안의 제어 조치를 제안해 줘.'
PROPOSE_Q_EN = 'Suggest control actions for the next hour.'
BRIEF_Q, BRIEF_Q_EN = '현재 운영 상황을 브리핑해 줘.', 'Brief me on current operations.'
BLD_EN = {'B1': 'office tower', 'B2': 'research building', 'B3': 'dormitory', 'B4': 'data centre'}
FLOORS = {'B1': 8, 'B2': 4, 'B3': 5, 'B4': 2}


# ================================================================ small helpers
def jo(word, with_final, without):
    """Korean particle by the last syllable: jo('연구동', '은', '는') → '은'."""
    w = re.sub(r'[\s)\]"\']+$', '', str(word or ''))
    if not w:
        return without
    ch = w[-1]
    if '가' <= ch <= '힣':
        return with_final if (ord(ch) - 0xAC00) % 28 else without
    return with_final if ch.isdigit() and ch in '013678' else without   # 영 일 삼 육 칠 팔 end in a consonant


def ro(word):
    w = str(word or '')
    if w and '가' <= w[-1] <= '힣':
        f = (ord(w[-1]) - 0xAC00) % 28
        return '로' if f in (0, 8) else '으로'
    return '로'


def sym(c):
    return '₩' if (c.get('tariff') or {}).get('currency') == '₩' else '$'


def A(head, lines):
    lines = [l for l in lines if l][:4]
    return head + ('\n' + '\n'.join('- ' + l for l in lines) if lines else '')


def dm(c, who='agent'):
    return ((c.get('dayMetrics') or {}).get(who)) or {}


def tier_key(c):
    t = (c.get('tariff') or {}).get('tier')
    return t.get('tier') if isinstance(t, dict) else t


def bld(c, bid):
    return next((b for b in c.get('buildingsByLoad') or [] if b.get('id') == bid), None)


def floors(c):
    return {f['id']: f for f in c.get('floors') or [] if isinstance(f, dict) and f.get('id')}


def head_only(ans):
    return ans.split('\n', 1)[0]


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


class Skip(Exception):
    """The context cannot answer this kind (field missing): pick another question."""


# ================================================================ chat answers (Korean)
def q_peak(c, r):
    cp, t = c['campus'], c['today']
    g, lim, h, pct = cp['gridImportNowKW'], cp['peakLimitKW'], cp['headroomNowKW'], cp['headroomNowPct']
    if h >= 0:
        head = r.choice(['{t} 현재 계통 수전은 {g} kW로, 피크 한도 {l} kW까지 {h} kW({p}%) 여유가 있습니다.',
                         '피크 한도 {l} kW까지 {h} kW({p}%)가 남았습니다 — {t} 현재 계통 수전 {g} kW 기준입니다.']).format(
            t=c['clock'], g=n(g), l=n(lim), h=n(h), p=n(pct))
    else:
        head = '%s 현재 계통 수전 %s kW로 피크 한도 %s kW보다 %s kW 높습니다.' % (c['clock'], n(g), n(lim), n(-h))
    dr = c.get('demandResponse') or {}
    lines = []
    if dr.get('active'):
        lines.append('DR 진행 중: %s–%s, %s kW 감축 요청' % (dr.get('start'), dr.get('end'), n(dr.get('shedKW'))))
    lines.append(v1.fc_line(c) or '향후 4시간 피크 예측은 아직 데이터에 없습니다')
    lines.append('오늘 최대 수전은 %s kW였습니다' % n(t['highestGridImportTodayKW']))
    lines.append('%s이고 SOC는 %s%%입니다' % (ess_desc(cp), n(cp['essSocPct'])))
    return A(head, lines)


def q_load(c, r):
    cp = c['campus']
    head = '%s 현재 캠퍼스 부하는 %s kW이고, 계통 수전은 %s kW입니다.' % (c['clock'], n(cp['loadNowKW']), n(cp['gridImportNowKW']))
    b1 = c['buildingsByLoad'][0]
    lines = ['태양광 %s kW를 자체 소비하고, %s입니다' % (n(cp['pvNowKW']), ess_desc(cp)),
             ('피크 한도 %s kW까지 %s kW(%s%%) 여유가 있습니다' % (n(cp['peakLimitKW']), n(cp['headroomNowKW']), n(cp['headroomNowPct']))
              if cp['headroomNowKW'] >= 0 else '피크 한도 %s kW보다 %s kW 높습니다' % (n(cp['peakLimitKW']), n(-cp['headroomNowKW']))),
             '가장 많이 쓰는 건물은 %s(%s) %s kW입니다' % (b1['name'], b1['id'], n(b1['loadKW']))]
    return A(head, lines)


def q_grid(c, r):
    cp = c['campus']
    head = '%s 현재 계통 수전은 %s kW입니다.' % (c['clock'], n(cp['gridImportNowKW']))
    lines = [('피크 한도 %s kW까지 %s kW(%s%%) 여유가 있습니다' % (n(cp['peakLimitKW']), n(cp['headroomNowKW']), n(cp['headroomNowPct']))
              if cp['headroomNowKW'] >= 0 else '피크 한도 %s kW보다 %s kW 높습니다' % (n(cp['peakLimitKW']), n(-cp['headroomNowKW']))),
             '캠퍼스 부하 %s kW 중 태양광이 %s kW를 대고 있고, %s입니다' % (n(cp['loadNowKW']), n(cp['pvNowKW']), ess_desc(cp))]
    if is_num(cp.get('baselineGridNowKW')):
        lines.append('같은 조건의 룰 기반 BMS라면 지금 %s kW를 받고 있습니다' % n(cp['baselineGridNowKW']))
    return A(head, lines)


def q_cost(c, r):
    t = c['today']
    if t['savingsPct'] >= 0:
        head = '%s까지 오늘 비용은 %s로, 같은 조건의 룰 기반 BMS(%s)보다 %s%% 적습니다.' % (c['clock'], money(c, t['costAgent']), money(c, t['costBaseline']), n(t['savingsPct']))
    else:
        head = '%s까지 오늘 비용은 %s로, 같은 조건의 룰 기반 BMS(%s)보다 많습니다.' % (c['clock'], money(c, t['costAgent']), money(c, t['costBaseline']))
    lines = []
    if t['costBaseline'] >= t['costAgent']:
        lines.append('아낀 금액은 %s입니다' % money(c, round(t['costBaseline'] - t['costAgent'], 2)))
    lines += ['오늘 사용 전력량은 %s kWh입니다' % n(t['energyKWh']),
              '지금은 %s 요금 구간으로 %s%s/kWh입니다' % (tier_name(c), sym(c), n(c['tariff']['pricePerKWh']))]
    return A(head, lines)


def q_savings(c, r):
    t = c['today']
    d = round(t['costBaseline'] - t['costAgent'], 2)
    if d >= 0:
        head = '%s까지 오늘은 같은 조건의 룰 기반 BMS보다 %s를 아꼈습니다(%s%%).' % (c['clock'], money(c, d), n(t['savingsPct']))
    else:
        head = '%s까지 오늘은 같은 조건의 룰 기반 BMS보다 %s를 더 썼습니다.' % (c['clock'], money(c, -d))
    lines = ['오늘 비용: 멀티에이전트 %s, 룰 기반 BMS %s' % (money(c, t['costAgent']), money(c, t['costBaseline']))]
    b = dm(c, 'baseline')
    if is_num(b.get('energyKWh')):
        lines.append('오늘 사용 전력량: 멀티에이전트 %s kWh, 룰 기반 BMS %s kWh' % (n(t['energyKWh']), n(b['energyKWh'])))
    lines.append('절감률은 같은 날씨·재실 조건으로 함께 돌린 룰 기반 BMS 대비 값입니다')
    return A(head, lines)


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
    return A(head, lines)


def q_ess(c, r):
    cp = c['campus']
    head = '%s이고, 충전 상태(SOC)는 %s%%입니다.' % (ess_desc(cp), n(cp['essSocPct']))
    lines = ['지금은 %s 요금 구간입니다(피크 시간 %s)' % (tier_name(c), c['tariff']['peakHours'])]
    d = dec(c, 'ESS 에이전트')
    if d:
        lines.append('최근 ESS 에이전트 조치: ' + short(d[0]))
    lines.append('계통 수전 %s kW, 한도 %s kW입니다' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW'])))
    return A(head, lines)


def q_why_ess(c, r, q=''):
    cp, t = c['campus'], tier_key(c)
    p, soc = cp.get('essNowKW') or 0, cp['essSocPct']
    lim, g = cp['peakLimitKW'], cp['gridImportNowKW']
    dr = (c.get('demandResponse') or {}).get('active')
    state = 'dis' if p > 1 else 'ch' if p < -1 else 'idle'
    asked = 'ch' if re.search(r'충전(?! *상태)', q) and not re.search(r'방전', q) else 'dis' if re.search(r'방전', q) else 'idle' if re.search(r'대기|쉬|안 ?(움직|돌)|멈', q) else None
    now = {'dis': '%s kW 방전 중' % n(p), 'ch': '%s kW 충전 중' % n(-p), 'idle': '대기 중'}[state]
    d = dec(c, 'ESS 에이전트')
    log = d[0] if d else ''
    if state == 'dis':
        why = ('DR 감축 요청에 맞춰 방전하고 있습니다.' if dr else
               '단가가 가장 비싼 %s 구간이라 방전해 요금과 피크를 줄이고 있습니다.' % tier_name(c) if t == 'peak' else
               '피크 한도를 지키려고 방전을 늘렸습니다.' if '피크 가드' in log else
               '저녁 부하를 줄이려고 방전하고 있습니다.' if '저녁 부하' in log else
               '계통 수전이 피크 한도에 가까워 방전으로 수전을 낮추고 있습니다.' if g >= 0.9 * lim else None)
    elif state == 'ch':
        why = ('단가가 싼 %s 구간이라 충전하고 있습니다.' % tier_name(c) if t == 'off' else
               '목표 충전량까지 채우려고 충전하고 있습니다.' if '충전 중' in log and '목표' in log else None)
    else:
        why = ('SOC가 %s%%로 낮아 방전을 멈췄습니다.' % n(soc) if soc <= 12 else
               'SOC가 예비 하한이라 방전을 제한하고 있습니다.' if '예비 하한' in log else
               '곧 올 피크 시간에 대비해 충전량을 유지하고 있습니다.' if '피크 대비' in log else
               '충전량을 유지하고 있습니다.' if '유지' in log else None)
    lead = '지금 ESS는 %s입니다' % now
    if asked and asked != state:                          # "왜 충전 중이야?" while it discharges: correct the premise first
        lead = '지금 ESS는 %s 중이 아니라 %s입니다' % ({'dis': '방전', 'ch': '충전', 'idle': '대기'}[asked], now)
    head = lead + '.' + ((' ' + why) if why else '')
    lines = []
    if d:
        lines.append('ESS 에이전트 최근 판단: ' + short(d[0]))
    lines.append('지금은 %s 요금 구간(%s%s/kWh)이고 피크 시간은 %s입니다' % (tier_name(c), sym(c), n(c['tariff']['pricePerKWh']), c['tariff']['peakHours']))
    lines.append('SOC %s%%, 계통 수전 %s kW(한도 %s kW)입니다' % (n(soc), n(g), n(lim)))
    return A(head, lines)


def q_pv(c, r):
    cp, w = c['campus'], c['weather']
    a = dm(c)
    head = '태양광은 지금 %s kW를 발전하고 있습니다.' % n(cp['pvNowKW'])
    lines = ['일사량은 %s W/m²입니다' % n(w['irradianceWm2'])]
    if is_num(a.get('pvGenKWh')):
        lines.append('오늘 지금까지 태양광 발전량은 %s kWh입니다' % n(a['pvGenKWh']))
    d = dec(c, '태양광 에이전트')
    if d:
        lines.append('태양광 에이전트: ' + short(d[0]).split(': ', 1)[-1])
    return A(head, lines)


def q_comfort(c, r):
    t = c['today']
    head = '오늘 쾌적 범위 유지율은 %s%%이고, 지금 %s개 구역 중 %s개가 범위 안에 있습니다.' % (n(t['comfortPct']), n(t['zonesCounted']), n(t['zonesInBand']))
    lines = ['쾌적 범위는 설정온도 ±1.5 °C 기준입니다']
    z = [x for x in c.get('zonesNeedingAttention', []) if x.get('inBand') is False] or c.get('zonesNeedingAttention', [])
    for x in z[:2]:
        lines.append('%s: %s °C(설정 %s °C), 재실 %s%%' % (x['id'], n(x['tempC']), n(x['setpointC']), n(x['occupancyPct'])))
    if len(lines) < 2:
        lines.append('쾌적 범위를 벗어난 재실 구역은 없습니다')
    return A(head, lines)


def q_agents(c, r):
    ag = c.get('agents', [])
    stage = ag[0].split(': ', 1)[-1] if ag else None
    ds = [x for x in (short(d) for d in dec(c, k=6)) if x.split(': ', 1)[-1].strip()][-3:]   # short() can empty a line
    if len(ds) < 2:                                       # a short log: the agents' stages fill in
        ds += ['%s' % a for a in ag[1:4 - len(ds)]]
    if len(ds) < 2:
        raise Skip
    head = ('여섯 에이전트는 지금 %s 상태이고, 최근 조치는 다음과 같습니다.' % stage) if stage else '에이전트들의 최근 조치는 다음과 같습니다.'
    return A(head, ds)


def q_weather(c, r):
    w, cp = c['weather'], c['campus']
    b = sorted(c['buildingsByLoad'], key=lambda x: -x['hvacKW'])[0]
    head = '바깥 기온은 %s °C, 일사량은 %s W/m²입니다.' % (n(w['outdoorC']), n(w['irradianceWm2']))
    lines = ['냉동기가 %s kW를 쓰고 있습니다' % n(cp['chillerNowKW']),
             '일사 덕분에 태양광이 %s kW를 냅니다' % n(cp['pvNowKW']),
             '냉방이 가장 큰 건물은 %s(%s) %s kW입니다' % (b['name'], b['id'], n(b['hvacKW']))]
    return A(head, lines)


def q_temp(c, r):
    w, cp = c['weather'], c['campus']
    head = '%s 현재 바깥 기온은 %s °C입니다.' % (c['clock'], n(w['outdoorC']))
    return A(head, ['일사량은 %s W/m²입니다' % n(w['irradianceWm2']), '냉동기는 %s kW를 쓰고 있습니다' % n(cp['chillerNowKW'])])


def q_chiller(c, r):
    w, cp = c['weather'], c['campus']
    b = sorted(c['buildingsByLoad'], key=lambda x: -x['hvacKW'])[0]
    head = '냉동기는 지금 %s kW를 쓰고 있습니다.' % n(cp['chillerNowKW'])
    lines = ['바깥 기온은 %s °C, 일사량은 %s W/m²입니다' % (n(w['outdoorC']), n(w['irradianceWm2'])),
             '냉방 전력이 가장 큰 건물은 %s(%s) %s kW입니다' % (b['name'], b['id'], n(b['hvacKW']))]
    return A(head, lines)


def q_dr(c, r):
    dr, a = c.get('demandResponse') or {}, dm(c)
    if dr.get('active'):
        head = '네, DR 이벤트가 진행 중입니다: %s–%s 동안 %s kW 감축 요청입니다.' % (dr.get('start'), dr.get('end'), n(dr.get('shedKW')))
        lines = ['발령 주체: %s' % dr.get('source'), '지금 계통 수전은 %s kW입니다' % n(c['campus']['gridImportNowKW'])]
        d = dec(c, '코디네이터')
        if d:
            lines.append(short(d[0]))
    else:
        head = '아니요, 지금 진행 중인 DR 이벤트는 없습니다.'
        lines = []
        if a.get('drRequestedKWh'):
            lines.append('오늘 DR 요청 %s kWh 중 %s kWh를 감축했습니다' % (n(a['drRequestedKWh']), n(a['drDeliveredKWh'])))
        lines += ['DR이 오면 코디네이터가 ESS → EV → 조명 → HVAC 순서로 감축을 나눕니다',
                  '계통 수전 %s kW, 한도 %s kW입니다' % (n(c['campus']['gridImportNowKW']), n(c['campus']['peakLimitKW']))]
    return A(head, lines)


def q_faults(c, r):
    f = c.get('faults') or {}
    oa = f.get('openAlarms') or []
    al = c.get('alerts') or []
    if oa:
        head = '센서 이상 경보가 %s건 열려 있습니다.' % n(len(oa))
        kind = {'stuck': '고착', 'drift': '드리프트', 'dropout': '끊김'}
        state = {'pending': '운영자 승인 대기', 'virtual': '가상 센서로 대체 중'}
        lines = ['%s: 온도 센서 %s 의심 — 측정 %s °C, 가상 센서 %s °C (%s)' % (a.get('room'), kind.get(a.get('type'), a.get('type')),
                                                                n(a.get('measuredC')) if a.get('measuredC') is not None else '값 없음', n(a.get('virtualC')), state.get(a.get('state'), a.get('state')))
                 for a in oa[:2] if isinstance(a, dict)]
        lines.append('경보를 승인하면 그 방은 가상 센서로 제어합니다')
    else:
        head = '지금 열린 센서 이상 경보는 없습니다.'
        lines = ['경보: ' + a.split(': ', 1)[-1] for a in al[:2]] or ['다른 운영 경보도 없습니다']   # quotes that fail the check are dropped by fit()
        lines.append('고장 감지는 5분마다 각 실 온도 센서를 확인합니다')
    return A(head, lines)


def q_forecast(c, r):
    f, cp = c.get('forecast') or {}, c['campus']
    if f.get('next4hMaxKW') is None:
        return A('향후 4시간 피크 예측은 아직 데이터에 없습니다.', ['예측 모델이 쓸 데이터가 더 쌓여야 합니다',
                                                     '지금 계통 수전은 %s kW, 한도는 %s kW입니다' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW']))])
    head = '향후 4시간 최대 수전은 %s kW로 %s에 예상되며, 한도의 %s%%입니다.' % (n(f['next4hMaxKW']), f.get('next4hMaxAt'), n(f.get('next4hMaxPctOfLimit')))
    lines = []
    if f.get('band90KW') is not None:
        lines.append('예측 불확실성 폭은 ±%s kW입니다' % n(f['band90KW']))
    acc = f.get('accuracy1hAhead')
    if acc:
        lines.append('1시간 앞 예측 정확도: CV(RMSE) %s%%, NMBE %s%%' % (n(acc.get('cvrmsePct')), n(acc.get('nmbePct'))))
    lines.append('지금 계통 수전은 %s kW, 한도는 %s kW입니다' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW'])))
    if len(lines) < 2:
        lines.append('오늘 최대 수전은 %s kW였습니다' % n(c['today']['highestGridImportTodayKW']))
    return A(head, lines)


def q_tariff(c, r):
    t = c['tariff']
    head = '요금이 가장 비싼 시간은 피크 시간대 %s이고, 지금 %s은 %s 구간으로 %s%s/kWh입니다.' % (t['peakHours'], c['clock'], tier_name(c), sym(c), n(t['pricePerKWh']))
    a = dm(c)
    lines = []
    if a.get('avgPrice') is not None:
        lines.append('오늘 지금까지 평균 단가는 %s%s/kWh입니다' % (sym(c), n(a['avgPrice'])))
    lines.append('오늘 비용은 %s입니다' % money(c, c['today']['costAgent']))
    return A(head, lines)


def q_maxtoday(c, r):
    t, cp = c['today'], c['campus']
    a, b = dm(c), dm(c, 'baseline')
    hi, lim = t['highestGridImportTodayKW'], cp['peakLimitKW']
    at = (' %s 무렵' % t['highestGridImportAt']) if t.get('highestGridImportAt') else ''
    if hi <= lim:
        head = '오늘 최대 수전은%s %s kW로, 피크 한도 %s kW를 넘지 않았습니다.' % (at, n(hi), n(lim))
    else:
        head = '오늘 최대 수전은%s %s kW로, 피크 한도 %s kW보다 높았던 때가 있습니다.' % (at, n(hi), n(lim))
    lines = []
    if a.get('minutesOverLimit') is not None:
        lines.append('오늘 피크 한도를 웃돈 시간은 모두 %s분입니다' % n(a['minutesOverLimit']))
    if b.get('peakKW') is not None:
        lines.append('같은 조건의 룰 기반 BMS 최대 수전은 %s kW입니다' % n(b['peakKW']))
    lines.append('지금 계통 수전은 %s kW입니다' % n(cp['gridImportNowKW']))
    return A(head, lines)


def q_peak_time(c, r):
    t, cp = c['today'], c['campus']
    if not t.get('highestGridImportAt'):
        raise Skip
    a, b = dm(c), dm(c, 'baseline')
    head = '오늘 최대 수전 %s kW는 %s 무렵(15분 평균 기준)에 기록됐습니다.' % (n(t['highestGridImportTodayKW']), t['highestGridImportAt'])
    lines = ['피크 한도는 %s kW입니다' % n(cp['peakLimitKW'])]
    if is_num(a.get('minutesOverLimit')) and is_num(b.get('minutesOverLimit')):
        lines.append('오늘 한도를 웃돈 시간: 멀티에이전트 %s분, 같은 조건의 룰 기반 BMS %s분' % (n(a['minutesOverLimit']), n(b['minutesOverLimit'])))
    lines.append('지금 계통 수전은 %s kW입니다' % n(cp['gridImportNowKW']))
    return A(head, lines)


def q_co2(c, r):
    a, b = dm(c), dm(c, 'baseline')
    if a.get('co2Kg') is None:
        raise Skip
    head = '%s까지 오늘 탄소 배출량은 %s kg입니다.' % (c['clock'], n(a['co2Kg']))
    lines = ['같은 조건의 룰 기반 BMS는 %s kg입니다' % n(b['co2Kg'])] if b.get('co2Kg') is not None else []
    lines.append('오늘 사용 전력량은 %s kWh입니다' % n(c['today']['energyKWh']))
    if a.get('pvUsedKWh') is not None:
        lines.append('자체 소비한 태양광 전력량은 %s kWh입니다' % n(a['pvUsedKWh']) if a.get('pvUsedKWh') != a.get('pvGenKWh') else
                     '태양광 %s kWh를 모두 자체 소비했습니다' % n(a['pvUsedKWh']))
    return A(head, lines)


def q_ev(c, r):
    cp, a, ev = c['campus'], dm(c), c.get('ev') or {}
    head = ('EV 충전기는 지금 %s kW를 쓰고 있습니다.' % n(cp['evNowKW'])) if cp.get('evNowKW') else '지금 충전 중인 EV는 없습니다(충전 전력 0 kW).'
    lines = []
    if ev.get('chargers') is not None:
        lines.append('충전기 %s기 중 %s대 연결, %s대 충전 중입니다' % (n(ev['chargers']), n(ev.get('carsConnected', 0)), n(ev.get('charging', 0))))
    if a.get('evSessions') is not None:
        lines.append('오늘 충전 세션 %s건 중 %s건이 목표를 채웠습니다(%s%%)' % (n(a['evSessions']), n(a.get('evMet', 0)), n(a.get('evMetPct', 0))))
    d = dec(c, 'EV 충전 에이전트')
    if d:
        lines.append('EV 충전 에이전트: ' + short(d[0]).split(': ', 1)[-1])
    if len(lines) < 2:
        lines.append('계통 수전 %s kW, 한도 %s kW입니다' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW'])))
    return A(head, lines)


def q_ev_count(c, r):
    ev, cp = c.get('ev') or {}, c['campus']
    if ev.get('chargers') is None:
        raise Skip
    k, ch = ev.get('carsConnected', 0), ev.get('charging', 0)
    head = ('지금 충전기 %s기 중 %s대에 전기차가 연결돼 있고, %s대가 충전 중입니다.' % (n(ev['chargers']), n(k), n(ch)) if k else
            '지금 충전기에 연결된 전기차는 없습니다(충전기 %s기).' % n(ev['chargers']))
    lines = ['EV 충전 전력은 합계 %s kW입니다' % n(ev.get('totalKW', cp.get('evNowKW') or 0))]
    a = dm(c)
    if a.get('evSessions') is not None:
        lines.append('오늘 충전 세션은 %s건이고 %s건이 출차 목표를 채웠습니다' % (n(a['evSessions']), n(a.get('evMet', 0))))
    d = dec(c, 'EV 충전 에이전트')
    if d:
        lines.append('EV 충전 에이전트: ' + short(d[0]).split(': ', 1)[-1])
    if len(lines) < 2:
        lines.append('EV 에이전트는 최대부하 시간에 출차 시각을 지키는 최소 전력으로 충전을 미룹니다')
    return A(head, lines)


def q_pvself(c, r):
    a = dm(c)
    if a.get('pvGenKWh') is None:
        raise Skip
    head = '오늘 태양광은 %s kWh를 발전했고, 그중 %s%%를 캠퍼스에서 자체 소비했습니다.' % (n(a['pvGenKWh']), n(a['pvSelfPct']))
    return A(head, ['자체 소비량은 %s kWh입니다' % n(a['pvUsedKWh']), '지금 발전량은 %s kW입니다' % n(c['campus']['pvNowKW'])])


def q_hot(c, r, cold=False):
    fl = [f for f in floors(c).values() if (f.get('occupancyPct') or 0) > 0 and is_num(f.get('tempC'))]
    if len(fl) < 2:
        raise Skip
    fl.sort(key=lambda f: f['tempC'], reverse=not cold)
    f, g = fl[0], fl[1]
    word = '시원한' if cold else '더운'
    head = '재실 층 중 지금 가장 %s 곳은 %s로 %s °C(설정 %s °C)입니다.' % (word, f['id'], n(f['tempC']), n(f['setpointC']))
    lines = ['%s 쾌적 범위 %s, 재실률은 %s%%입니다' % (f['id'], '안에 있고' if f.get('inBand') else '를 벗어났고', n(f['occupancyPct'])),
             '오늘 쾌적 범위 유지율은 %s%%입니다' % n(c['today']['comfortPct']),
             '다음은 %s %s °C(설정 %s °C)입니다' % (g['id'], n(g['tempC']), n(g['setpointC']))]
    return A(head, lines)


def q_cold(c, r):
    return q_hot(c, r, cold=True)


def q_vacant_lights(c, r):
    rm = c.get('rooms') or {}
    if 'vacantWithLightsOn' not in rm:
        raise Skip
    k = rm.get('vacantWithLightsOn') or 0
    lst = rm.get('vacantWithLightsOnRooms') or []
    if k:
        head = '빈 방인데 조명이 켜진 방은 %s개입니다.' % n(k)
        lines = ['%s(%s): %s분째 빈 방' % (x.get('id'), x.get('name'), n(x.get('vacantMin') or 0)) for x in lst[:3]]
    else:
        head = '지금 빈 방인데 조명이 켜진 방은 없습니다.'
        lines = ['전체 %s개 방 중 %s개에 사람이 있습니다' % (n(rm.get('total', 0)), n(rm.get('occupied', 0)))]
    if rm.get('note'):
        lines.append(rm['note'])
    if len(lines) < 2:
        lines.append('전체 %s개 방 중 %s개에 사람이 있습니다' % (n(rm.get('total', 0)), n(rm.get('occupied', 0))))
    return A(head, lines)


def q_scenario(c, r):
    sc = c.get('scenario') or {}
    if not sc.get('name'):
        raise Skip
    head = '지금 시나리오는 "%s"입니다.' % sc['name']
    lines = []
    if sc.get('whatIsDifferent'):
        lines.append(str(sc['whatIsDifferent']).rstrip('.'))
    for x in (sc.get('howAgentsRespond') or [])[:2]:
        lines.append(str(x).rstrip('.'))
    if sc.get('settings'):
        lines.append('설정: ' + str(sc['settings']).rstrip('.'))
    if len(lines) < 2:
        lines.append('같은 조건의 룰 기반 BMS도 함께 시뮬레이션해 비교합니다')
    return A(head, lines)


def q_capabilities(c, r):
    return A('이런 일을 할 수 있습니다.', ['지금 상태: 부하·피크 여유·요금 구간·배터리·태양광·EV·층별 온도·고장 경보를 실시간 데이터로 답합니다',
                                      '운영 브리핑과 지도에서 고른 건물·층·방 설명을 합니다',
                                      '제어 조치를 제안합니다(운영자가 적용을 눌러야 실행됩니다)',
                                      '용어와 원리(DR, ESS, 피크 한도, 절감률 계산)를 설명합니다'])


def q_request_chat(c, r, q=''):
    """A request to change something that the page sends to chat, not to the proposal task (its patterns miss about half
    of the request phrasings): chat changes nothing, so say how changes are made and name the candidates in the data."""
    fl = [f for f in floors(c).values() if not f['id'].startswith('B4') and is_num(f.get('tempC')) and is_num(f.get('setpointC'))]
    if not fl and not (c.get('rooms') or {}).get('total'):
        raise Skip
    cool, light = re.search(r'냉방|에어컨|온도|설정|공조|춥|덥|시원', q), re.search(r'불|조명|전등', q)
    lines = []
    if cool or not light:
        cand = sorted([f for f in fl if (f.get('occupancyPct') or 0) < 60 and f['tempC'] <= f['setpointC'] + 0.7 and f['setpointC'] < 27], key=lambda f: -(f.get('kW') or 0))[:2]
        lines += ['%s: 재실 %s%%, %s °C(설정 %s °C)라 설정온도를 1도 올릴 여지가 있습니다' % (f['id'], n(f['occupancyPct']), n(f['tempC']), n(f['setpointC'])) for f in cand]
    if light or not cool:
        rm = c.get('rooms') or {}
        lst = rm.get('vacantWithLightsOnRooms') or []
        if lst:
            lines.append('빈 방인데 조명이 켜진 방 %s개: %s' % (n(rm.get('vacantWithLightsOn', len(lst))), ', '.join(x['id'] for x in lst[:3])))
    if lines:
        lines.append('제어 제안을 요청하면 이 후보로 적용 카드를 만듭니다')
        head = '채팅으로는 설비를 바로 바꾸지 않으니, 아래 후보를 제어 제안으로 만들어 운영자가 승인하면 적용됩니다.'
    else:
        head = '지금 데이터로는 바로 바꿀 만한 후보가 없습니다.'
        lines = ['재실이 낮으면서 설정온도를 올릴 여지가 있는 층이나, 조명이 켜진 빈 방이 없습니다', '채팅으로는 설비를 바꾸지 않고, 바꿀 때는 제어 제안에서 운영자가 승인합니다']
    return A(head, lines)


def q_offtopic(c, r):
    return A('그 질문은 캠퍼스 에너지 운영과 관계가 없어 답하기 어렵습니다.',
             ['저는 Helio Campus의 부하·요금·쾌적·에이전트 동작에 답하고, 운영자가 승인할 제어 조치를 제안합니다',
              '에너지 운영에 관해 궁금한 것을 물어봐 주세요'])


# questions the data cannot answer: the closest figure that is in the data, or none
UNK_TOPIC = [
    (r'피크 ?(요금 ?)?시간', lambda c: '요금 피크 시간대는 매일 %s입니다(요금표 기준)' % c['tariff']['peakHours']),
    (r'요금|비용|전기료|전기세|고지서|청구|요금제|정산|단가', lambda c: '오늘 %s까지 비용은 %s입니다' % (c['clock'], money(c, c['today']['costAgent']))),
    (r'탄소|CO2|이산화탄소|배출|나무', lambda c: ('오늘 탄소 배출량은 %s kg입니다' % n(dm(c)['co2Kg'])) if is_num(dm(c).get('co2Kg')) else None),
    (r'날씨|기온|예보|비가|눈|습도|미세먼지|기상', lambda c: '지금 바깥 기온은 %s °C입니다' % n(c['weather']['outdoorC'])),
    (r'태양광|PV|발전', lambda c: '지금 태양광은 %s kW를 발전하고 있습니다' % n(c['campus']['pvNowKW'])),
    (r'배터리|ESS', lambda c: '지금 %s이고 SOC는 %s%%입니다' % (ess_desc(c['campus']), n(c['campus']['essSocPct']))),
    (r'EV|전기차|충전', lambda c: '지금 EV 충전 전력은 %s kW입니다' % n(c['campus'].get('evNowKW') or 0)),
    (r'DR|수요반응', lambda c: '지금 진행 중인 DR은 %s' % ('있습니다(%s–%s)' % (c['demandResponse'].get('start'), c['demandResponse'].get('end')) if (c.get('demandResponse') or {}).get('active') else '없습니다')),
    (r'피크|수전|최대|부하|사용량|전력량|kWh', lambda c: '오늘 최대 수전은 %s kW, 지금 계통 수전은 %s kW입니다' % (n(c['today']['highestGridImportTodayKW']), n(c['campus']['gridImportNowKW']))),
    (r'고장|센서|수리|정비|제조사|점검|교체|설비', lambda c: '지금 열린 센서 이상 경보는 %s건입니다' % n(len((c.get('faults') or {}).get('openAlarms') or []))),
    (r'온도|냉방|쾌적|에어컨', lambda c: '오늘 쾌적 범위 유지율은 %s%%입니다' % n(c['today']['comfortPct'])),
]


def q_unknown(c, r, q=''):
    lines = ['지금 데이터에는 %s 시점의 캠퍼스 운영 값만 있습니다' % c['clock']]
    for rx, f in UNK_TOPIC:
        if re.search(rx, q, re.I):
            x = f(c)
            if x:
                lines.append('대신 지금 데이터로는: ' + x)
            break
    if len(lines) < 2:
        lines.append('예보·과거 기록·고지서·설비 이력 같은 정보는 들어 있지 않습니다')
    return A('그 정보는 데이터에 없어 답할 수 없습니다.', lines)


# building and floor figures
def q_bld(c, r, bid, metric):
    b = bld(c, bid)
    if not b:
        raise Skip
    nm = '%s(%s)' % (b['name'], bid)
    comp = ['냉방 %s kW' % n(b['hvacKW']), '조명 %s kW' % n(b['lightKW']), '콘센트 %s kW' % n(b['plugKW'])] + (['IT %s kW' % n(b['itKW'])] if b.get('itKW') else [])
    occ = '재실률 %s%%(%s명)입니다' % (n(b['occupancyPct']), n(b['people']))
    if metric == 'load':
        head = '%s 부하는 지금 %s kW입니다.' % (nm, n(b['loadKW']))
        lines = ['구성: ' + ' · '.join(comp), '캠퍼스 건물 중 %s번째로 많이 씁니다' % n(b['rank']), occ]
    elif metric == 'hvac':
        head = '%s 냉방 전력은 지금 %s kW입니다.' % (nm, n(b['hvacKW']))
        lines = ['건물 전체 부하는 %s kW입니다' % n(b['loadKW']), occ]
    elif metric == 'light':
        head = '%s 조명 전력은 지금 %s kW입니다.' % (nm, n(b['lightKW']))
        lines = ['건물 전체 부하는 %s kW입니다' % n(b['loadKW']), occ]
        if is_num(b.get('lightLevelPct')):
            lines.insert(1, '조명 밝기는 평균 %s%%입니다' % n(b['lightLevelPct']))
    else:
        head = '%s에는 지금 %s명이 있습니다(재실률 %s%%).' % (nm, n(b['people']), n(b['occupancyPct']))
        lines = ['건물 전체 부하는 %s kW입니다' % n(b['loadKW']), '냉방 %s kW, 조명 %s kW입니다' % (n(b['hvacKW']), n(b['lightKW']))]
    if bid == 'B4' and metric in ('hvac', 'load'):
        lines.append('데이터센터 냉방은 운영 규칙상 줄이지 않습니다')
    return A(head, lines)


def floor_phrase(r, bid, k, style=None):
    style = style if style is not None else r.random()
    name = {'B1': '오피스 타워', 'B2': '연구동', 'B3': '기숙사', 'B4': '데이터센터'}[bid]
    return ('%s %d층' % (bid, k)) if style < 0.5 else ('%s %d층' % (name, k)) if style < 0.85 else ('%s-F%d' % (bid, k))


def q_floor(c, r, fid, metric):
    fl = floors(c)
    if not fl:
        raise Skip
    bid = fid.split('-')[0]
    f = fl.get(fid)
    if not f:                                         # a floor the building does not have
        top = max(int(x.split('-F')[1]) for x in fl if x.startswith(bid + '-'))
        return A('%s 층은 데이터에 없습니다.' % fid, ['%s 건물은 %s-F1부터 %s-F%d까지 있습니다' % (bid, bid, bid, top),
                                                  '있는 층을 물어보면 온도·재실·전력을 알려 드립니다'])
    band = '쾌적 범위 안에 있습니다' if f.get('inBand') else '쾌적 범위를 벗어났습니다'
    if metric == 'temp':
        head = '%s 층은 지금 %s °C(설정 %s °C)입니다.' % (fid, n(f['tempC']), n(f['setpointC']))
        lines = ['재실률 %s%%, 전력 %s kW' % (n(f['occupancyPct']), n(f['kW'])), band]
    elif metric == 'occ':
        head = '%s 층 재실률은 지금 %s%%입니다.' % (fid, n(f['occupancyPct']))
        lines = ['온도 %s °C(설정 %s °C)' % (n(f['tempC']), n(f['setpointC'])), '전력 %s kW' % n(f['kW'])]
    elif metric == 'power':
        head = '%s 층은 지금 %s kW를 쓰고 있습니다.' % (fid, n(f['kW']))
        lines = ['재실률 %s%%, 온도 %s °C(설정 %s °C)' % (n(f['occupancyPct']), n(f['tempC']), n(f['setpointC'])), band]
    else:
        head = '%s 층은 %s °C(설정 %s °C)로 %s.' % (fid, n(f['tempC']), n(f['setpointC']), band)
        lines = ['재실률 %s%%, 전력 %s kW' % (n(f['occupancyPct']), n(f['kW'])), '오늘 캠퍼스 쾌적 범위 유지율은 %s%%입니다' % n(c['today']['comfortPct'])]
    return A(head, lines)


# ================================================================ concept answers (glossary from assist.augment)
GKEY = {'c_dr': 'DR(수요반응)', 'c_ess': 'ESS(에너지저장장치)', 'c_limit': '피크 한도', 'c_savings': '절감률 계산', 'c_negotiation': '에이전트 협상',
        'c_tou': '계시별 요금(TOU)', 'c_setback': '셋백·사전 냉방', 'c_fdd': '고장 감지(FDD)', 'c_rules': '운영 우선순위', 'c_selfcons': '자가소비율',
        'c_grid': '수전', 'c_comfort': '쾌적 범위', 'c_forecast': '수요 예측', 'c_mabems': 'MA-BEMS', 'c_heatwave': '폭염 대응',
        'c_cloudy': '흐린 날 대응', 'c_evrush': 'EV 몰림 대응', 'c_holiday': '휴일·방학 대응', 'c_whatif': '설정 변경 효과'}
GKEY_EN = {'c_savings_en': 'How savings are computed', 'c_dr_en': 'DR (demand response)', 'c_ess_en': 'ESS (energy storage system)'}


def sentences(text):
    text = re.sub(r'한도 (\d+)%를 넘는 동안', r'한도의 \1% 이상인 동안', text)   # numcheck reads "한도…넘는" as an excess claim
    return [s.strip() for s in re.split(r'(?<=[다.])\.\s+|(?<=\.)\s+', text.strip()) if s.strip()]


def concept_values(kind, c):
    cp, t, a = c['campus'], c['today'], dm(c)
    dr = c.get('demandResponse') or {}
    if kind == 'c_dr':
        out = ['지금 DR 진행 중: %s–%s, %s kW 감축 요청' % (dr.get('start'), dr.get('end'), n(dr.get('shedKW'))) if dr.get('active') else '지금 진행 중인 DR은 없습니다']
        if a.get('drRequestedKWh'):
            out.append('오늘 DR 요청 %s kWh 중 %s kWh를 감축했습니다' % (n(a['drRequestedKWh']), n(a['drDeliveredKWh'])))
        return out
    if kind == 'c_ess':
        return ['지금 %s이고 SOC는 %s%%입니다' % (ess_desc(cp), n(cp['essSocPct']))]
    if kind in ('c_limit', 'c_rules'):
        out = [('지금 계통 수전은 %s kW로 피크 한도 %s kW까지 %s kW 여유가 있습니다' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW']), n(cp['headroomNowKW'])))
               if cp['headroomNowKW'] >= 0 else '지금 계통 수전 %s kW는 피크 한도 %s kW보다 높습니다' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW']))]
        out.append('오늘 쾌적 범위 유지율은 %s%%입니다' % n(t['comfortPct']) if kind == 'c_rules' else '오늘 최대 수전은 %s kW였습니다' % n(t['highestGridImportTodayKW']))
        return out
    if kind in ('c_savings', 'c_mabems'):
        s = ('오늘 비용은 멀티에이전트 %s, 룰 기반 BMS %s로 %s%% 적습니다' % (money(c, t['costAgent']), money(c, t['costBaseline']), n(t['savingsPct']))
             if t['savingsPct'] >= 0 else '오늘 비용은 멀티에이전트 %s, 룰 기반 BMS %s입니다' % (money(c, t['costAgent']), money(c, t['costBaseline'])))
        out = [s]
        b = dm(c, 'baseline')
        if kind == 'c_savings' and is_num(a.get('minutesOverLimit')) and is_num(b.get('minutesOverLimit')):
            out.append('오늘 한도를 웃돈 시간은 멀티에이전트 %s분, 룰 기반 BMS %s분입니다' % (n(a['minutesOverLimit']), n(b['minutesOverLimit'])))
        return out
    if kind == 'c_negotiation':
        out = []
        ag = c.get('agents') or []
        if ag:
            out.append('지금 코디네이터 상태: %s' % ag[0].split(': ', 1)[-1])
        d = dec(c, '코디네이터')
        if d:
            out.append('코디네이터 최근 판단: ' + short(d[0]).split(': ', 1)[-1])
        return out
    if kind in ('c_tou', 'c_setback'):
        return ['지금은 %s 구간(%s%s/kWh)이고, 피크 시간은 %s입니다' % (tier_name(c), sym(c), n(c['tariff']['pricePerKWh']), c['tariff']['peakHours'])]
    if kind == 'c_fdd':
        f = c.get('faults') or {}
        out = ['지금 열린 센서 이상 경보는 %s건입니다' % n(len(f.get('openAlarms') or []))]
        ds = f.get('drillStats') or {}
        if ds.get('injected'):
            out.append('오늘 고장 주입 %s건 중 %s건을 감지했습니다' % (n(ds['injected']), n(ds.get('detected', 0))))
        return out
    if kind == 'c_selfcons':
        return ['오늘 태양광 발전량은 %s kWh이고, 그중 %s%%를 캠퍼스에서 바로 썼습니다' % (n(a['pvGenKWh']), n(a['pvSelfPct']))] if is_num(a.get('pvGenKWh')) else []
    if kind == 'c_grid':
        return ['지금 캠퍼스 부하 %s kW, 태양광 %s kW, %s이라 계통 수전은 %s kW입니다' % (n(cp['loadNowKW']), n(cp['pvNowKW']), ess_desc(cp), n(cp['gridImportNowKW']))]
    if kind == 'c_comfort':
        return ['오늘 쾌적 범위 유지율은 %s%%이고, 지금 %s개 구역 중 %s개가 범위 안입니다' % (n(t['comfortPct']), n(t['zonesCounted']), n(t['zonesInBand']))]
    if kind == 'c_forecast':
        f = c.get('forecast') or {}
        acc = f.get('accuracy1hAhead') or {}
        out = []
        if f.get('next4hMaxKW') is not None:
            out.append('지금 향후 4시간 최대 수전 예측은 %s kW(%s)입니다' % (n(f['next4hMaxKW']), f.get('next4hMaxAt')))
        if acc:
            out.append('최근 1시간 앞 예측 정확도는 CV(RMSE) %s%%, NMBE %s%%입니다' % (n(acc.get('cvrmsePct')), n(acc.get('nmbePct'))))
        return out
    if kind == 'c_heatwave':
        return ['지금 바깥 기온은 %s °C이고, 계통 수전은 %s kW(한도 %s kW)입니다' % (n(c['weather']['outdoorC']), n(cp['gridImportNowKW']), n(cp['peakLimitKW']))]
    if kind == 'c_cloudy':
        return ['지금 일사량은 %s W/m²이고, 태양광은 %s kW를 발전하고 있습니다' % (n(c['weather']['irradianceWm2']), n(cp['pvNowKW']))]
    if kind == 'c_evrush':
        ev = c.get('ev') or {}
        return ['지금 EV 충전 전력은 %s kW입니다' % n(cp.get('evNowKW') or 0)] + (
            ['충전기 %s기 중 %s대가 연결돼 있습니다' % (n(ev['chargers']), n(ev.get('carsConnected', 0)))] if ev.get('chargers') is not None else [])
    if kind == 'c_holiday':
        rm = c.get('rooms') or {}
        return ['지금 전체 %s개 방 중 %s개에 사람이 있습니다' % (n(rm['total']), n(rm.get('occupied', 0)))] if rm.get('total') else []
    return []


# without a glossary entry (the gateway attaches one only when its patterns match the question) four concepts are still
# stated in the system prompt the model sees: answer those from it, skip the rest
SYS_FALLBACK = {
    'c_rules': '운영 우선순위는 1) 피크 한도 초과 방지 2) 재실 구역 쾌적 범위(설정온도 ±1.5 °C) 3) 비용·탄소 순서입니다.',
    'c_mabems': 'MA-BEMS는 에이전트 6개(코디네이터·HVAC·조명·태양광·ESS·EV 충전)가 15분마다 관찰→계획→협상→실행→검증을 되풀이하는 구조입니다.',
    'c_savings': '절감률은 같은 날씨로 함께 시뮬레이션한 룰 기반 BMS(기준선) 대비 값입니다.',
    'c_negotiation': '에이전트 6개(코디네이터·HVAC·조명·태양광·ESS·EV 충전)는 15분마다 관찰→계획→협상→실행→검증을 되풀이합니다.',
}
SYS_EXTRA = {'c_rules': '데이터센터(B4)·서버실·전기실 냉방은 운영 규칙상 줄이지 않습니다', 'c_mabems': '같은 날씨의 룰 기반 BMS(기준선)를 나란히 시뮬레이션해 비교합니다'}


def concept(kind, c, r, gl):
    key = GKEY[kind]
    body = gl.get(key)
    if not body and kind in SYS_FALLBACK:
        lines = ([SYS_EXTRA[kind]] if kind in SYS_EXTRA else []) + concept_values(kind, c)
        if len(lines) < 2:
            raise Skip
        return A(SYS_FALLBACK[kind], lines[:3])
    if not body:
        raise Skip
    ss = sentences(body)
    head = '%s: %s%s' % (key, ss[0], '' if ss[0].endswith('.') else '.')
    lines = [s.rstrip('.') for s in ss[1:3]] + concept_values(kind, c)
    if len(lines) < 2:
        lines.append('수치는 모두 실시간 시뮬레이션 데이터에서 가져옵니다' if kind != 'c_whatif' else '같은 조건의 비교 결과는 대시보드 그래프에서 확인할 수 있습니다')
    return A(head, lines[:4])


# ================================================================ English answers
def en_ess(cp):
    p = cp.get('essNowKW') or 0
    return ('the battery is discharging %s kW' % n(p)) if p > 1 else ('the battery is charging %s kW' % n(-p)) if p < -1 else 'the battery is idle'


def q_peak_en(c, r):
    return v1.q_peak_en(c, r)


def q_cost_en(c, r):
    t = c['today']
    if t['savingsPct'] >= 0:
        head = 'Cost so far today is %s against %s for the rule-based BMS, %s%% lower.' % (money(c, t['costAgent']), money(c, t['costBaseline']), n(t['savingsPct']))
    else:
        head = 'Cost so far today is %s, more than the rule-based BMS (%s).' % (money(c, t['costAgent']), money(c, t['costBaseline']))
    lines = ['Saved so far: %s' % money(c, round(t['costBaseline'] - t['costAgent'], 2))] if t['costBaseline'] >= t['costAgent'] else []
    lines += ['Energy today: %s kWh' % n(t['energyKWh']), 'Both run under the same weather and occupancy, so the difference is the control']
    return A(head, lines)


def q_load_en(c, r):
    cp = c['campus']
    b1 = c['buildingsByLoad'][0]
    head = 'At %s the campus load is %s kW and grid import is %s kW.' % (c['clock'], n(cp['loadNowKW']), n(cp['gridImportNowKW']))
    return A(head, ['Solar covers %s kW and %s' % (n(cp['pvNowKW']), en_ess(cp)),
                    ('Headroom: %s kW (%s%%) below the %s kW peak limit' % (n(cp['headroomNowKW']), n(cp['headroomNowPct']), n(cp['peakLimitKW'])))
                    if cp['headroomNowKW'] >= 0 else 'The peak limit is %s kW, and import is %s kW above it' % (n(cp['peakLimitKW']), n(-cp['headroomNowKW'])),
                    'Largest load: %s (%s) at %s kW' % (b1['id'], BLD_EN.get(b1['id'], b1['id']), n(b1['loadKW']))])


def q_top_en(c, r):
    b1, b2 = c['buildingsByLoad'][0], c['buildingsByLoad'][1]
    parts = (['IT %s kW' % n(b1['itKW'])] if b1.get('itKW') else []) + ['HVAC %s kW' % n(b1['hvacKW']), 'plug loads %s kW' % n(b1['plugKW']), 'lighting %s kW' % n(b1['lightKW'])]
    head = 'The largest load right now is %s (%s) at %s kW.' % (b1['id'], BLD_EN.get(b1['id'], b1['id']), n(b1['loadKW']))
    lines = ['Breakdown: ' + ', '.join(parts), 'Second: %s (%s) at %s kW' % (b2['id'], BLD_EN.get(b2['id'], b2['id']), n(b2['loadKW']))]
    if b1['id'] == 'B4':
        lines.append('Data-centre cooling is never cut under the operating rules')
    return A(head, lines)


def q_ess_en(c, r):
    cp = c['campus']
    head = 'Right now %s; state of charge is %s%%.' % (en_ess(cp), n(cp['essSocPct']))
    tier = {'peak': 'peak', 'mid': 'mid-peak', 'off': 'off-peak'}.get(tier_key(c), tier_name(c))
    return A(head, ['Tariff period: %s (%s%s/kWh), peak hours %s' % (tier, sym(c), n(c['tariff']['pricePerKWh']), c['tariff']['peakHours']),
                    'Grid import %s kW against a %s kW limit' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW']))])


def q_pv_en(c, r):
    cp, w, a = c['campus'], c['weather'], dm(c)
    lines = ['Irradiance is %s W/m²' % n(w['irradianceWm2'])]
    if is_num(a.get('pvGenKWh')):
        lines.append('Solar generation so far today: %s kWh' % n(a['pvGenKWh']))
    if len(lines) < 2:
        lines.append('All of it is used on campus first')
    return A('Solar is generating %s kW right now.' % n(cp['pvNowKW']), lines)


def q_faults_en(c, r):
    oa = (c.get('faults') or {}).get('openAlarms') or []
    if oa:
        kind = {'stuck': 'stuck', 'drift': 'drifting', 'dropout': 'dropped out'}
        lines = ['%s: temperature sensor suspected %s (reading %s °C, virtual sensor %s °C)' % (a.get('room'), kind.get(a.get('type'), a.get('type')),
                 n(a.get('measuredC')) if a.get('measuredC') is not None else 'none', n(a.get('virtualC'))) for a in oa[:2] if isinstance(a, dict)]
        lines.append('Approving the alarm switches that room to its virtual sensor')
        return A('%s sensor fault alarm%s open.' % (n(len(oa)), ' is' if len(oa) == 1 else 's are'), lines)
    return A('No sensor fault alarm is open right now.', ['Fault detection checks every room temperature sensor every 5 minutes',
                                                         '%s other operating alert%s in the data' % (n(len(c.get('alerts') or [])), '' if len(c.get('alerts') or []) == 1 else 's')])


def q_dr_en(c, r):
    dr = c.get('demandResponse') or {}
    cp = c['campus']
    if dr.get('active'):
        return A('Yes, a demand response event is active: %s–%s, cutting %s kW.' % (dr.get('start'), dr.get('end'), n(dr.get('shedKW'))),
                 ['Grid import is %s kW now' % n(cp['gridImportNowKW']), 'The coordinator splits the cut: battery, then EV, lighting and HVAC'])
    return A('No, no demand response event is active now.', ['Grid import %s kW, limit %s kW' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW'])),
                                                           'When one comes, the coordinator splits the cut: battery, then EV, lighting and HVAC'])


def q_unknown_en(c, r, q=''):
    return A('That is not in the data, so I cannot answer it.', ['The data only holds the live campus values at %s' % c['clock'],
                                                                 'Forecasts beyond 4 hours, past days, bills and equipment history are not included'])


def q_offtopic_en(c, r):
    return A('That is outside what I can help with here.', ['I answer questions about the Helio Campus energy operation: loads, cost, comfort and what the agents are doing',
                                                           'I can also draft control actions for the operator to approve'])


def concept_en(kind, c, r, gl):
    key = GKEY_EN[kind]
    body = gl.get(key)
    if not body:
        raise Skip
    ss = [s.strip() for s in re.split(r'(?<=\.)\s+', body) if s.strip()]
    cp, t = c['campus'], c['today']
    if kind == 'c_savings_en':
        val = ['Today: %s with the agents against %s for the rule-based BMS' % (money(c, t['costAgent']), money(c, t['costBaseline']))]
    elif kind == 'c_dr_en':
        dr = c.get('demandResponse') or {}
        val = ['Now: an event is active, %s–%s, cutting %s kW' % (dr.get('start'), dr.get('end'), n(dr.get('shedKW'))) if dr.get('active') else 'No event is active now']
    else:
        val = ['Now %s; state of charge %s%%' % (en_ess(cp), n(cp['essSocPct']))]
    lines = [s.rstrip('.') for s in ss[1:3]] + val
    return A('%s: %s%s' % (key, ss[0], '' if ss[0].endswith('.') else '.'), lines)


def brief_en(c, r):
    cp = c['campus']
    tier = {'peak': 'peak', 'mid': 'mid-peak', 'off': 'off-peak'}.get(tier_key(c), tier_name(c))
    lines = [('Load %s kW, grid import %s kW: %s kW (%s%%) below the %s kW limit' % (n(cp['loadNowKW']), n(cp['gridImportNowKW']), n(cp['headroomNowKW']), n(cp['headroomNowPct']), n(cp['peakLimitKW'])))
             if cp['headroomNowKW'] >= 0 else 'Grid import %s kW is above the %s kW limit' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW'])),
             'Solar %s kW; %s (state of charge %s%%); tariff: %s period, peak hours %s' % (n(cp['pvNowKW']), en_ess(cp), n(cp['essSocPct']), tier, c['tariff']['peakHours'])]
    dr = c.get('demandResponse') or {}
    if dr.get('active'):
        lines.append('Demand response active: %s–%s, %s kW cut requested' % (dr.get('start'), dr.get('end'), n(dr.get('shedKW'))))
    f = c.get('forecast') or {}
    if f.get('next4hMaxKW') is not None:
        lines.append('Next hours: forecast peak %s kW at %s (%s%% of the limit)' % (n(f['next4hMaxKW']), f.get('next4hMaxAt'), n(f.get('next4hMaxPctOfLimit'))))
    lines.append("Today's cost so far %s, %s%% below the rule-based BMS" % (money(c, c['today']['costAgent']), n(c['today']['savingsPct']))
                 if c['today']['savingsPct'] >= 0 else "Today's cost so far %s" % money(c, c['today']['costAgent']))
    return '\n'.join('- ' + l for l in lines[:5])


# ================================================================ kinds, phrasings and routing
KO = {f.__name__: f for f in [q_peak, q_load, q_grid, q_cost, q_savings, q_top, q_ess, q_pv, q_comfort, q_agents, q_weather, q_temp,
                               q_chiller, q_dr, q_faults, q_forecast, q_tariff, q_maxtoday, q_peak_time, q_co2, q_ev, q_ev_count,
                               q_pvself, q_hot, q_cold, q_vacant_lights, q_scenario, q_capabilities, q_offtopic]}
EN = {f.__name__: f for f in [q_peak_en, q_cost_en, q_load_en, q_top_en, q_ess_en, q_pv_en, q_faults_en, q_dr_en, q_offtopic_en]}
NEEDS_Q = {'q_why_ess': q_why_ess, 'unknown': q_unknown, 'q_unknown_en': q_unknown_en, 'q_request_chat': q_request_chat}
OLD_KINDS = ['q_peak', 'q_cost', 'q_top', 'q_ess', 'q_pv', 'q_comfort', 'q_agents', 'q_weather', 'q_dr', 'q_faults', 'q_forecast',
             'q_tariff', 'q_temp', 'q_maxtoday', 'q_co2', 'q_ev', 'q_pvself']

# paraphrases that ask for something the kind's answer does not contain (v2's filters, kept)
DROP = {
    'q_ev': re.compile(r'자리|몇 개|목록|대기|충전소별|고장|붐비|완료된|중단|이용률|예약|한가|포트|시작 가능|구분|점검|문제|끊긴|공간|현황판|충전기별|돌아가나요|몇 대'),
    'q_weather': re.compile(r'예측|예상|얼마나 더|변동 폭|민감|상관관계|분석|떨어지면|오르면|높아지면'),
    'q_forecast': re.compile(r'그래프|어디서|업데이트|계산|어떻게 예측|방법|정확'),
    'q_agents': re.compile(r'큐|프로세스|협상|어떻게'),
    'q_why_ess': re.compile(r'얼마나|몇 ?%|SOC|잔량'),
    'q_scenario': re.compile(r'바꾸|변경|선택|추천'),
}
DROP_UNKNOWN = {'다음 주 월요일 피크 시간대는 언제인가요?', '캠퍼스가 속한 지역의 시간대별 요금표 원본은?', '현재 전기 계약 종류와 계약전력은?',
                '전기요금 누진제 적용 구간은?', '오늘 이후 5시간 뒤 피크 예측은?', '오늘 이전의 에이전트 조치 로그 전체는?'}
UNKNOWN_ANSWERABLE = re.compile(r'오늘.*(최대|피크|요금|비용|사용량)|지금|현재|시나리오|몇 시에|회의실 예약|예약 현황')   # the data has these now


def norm(q):
    return re.sub(r'[\s?？.!,~…"\'“”]+', '', str(q).lower())


def bucket(q, salt=''):
    return int(hashlib.md5((salt + norm(q)).encode('utf-8')).hexdigest(), 16) % 100


# ---- the page's routing (build/ai_module.js aiRoute / aiFocus / aiParseCommand), ported so that the data only holds
# questions that reach the model as the task they are trained for
F = re.I | re.A
RX = {
    'greet': re.compile(r'^\s*(안녕|안뇽|하이|헬로|반가|hi\b|hello|hey\b|good (morning|afternoon|evening))', F),
    'thanks': re.compile(r'(고마워|고맙|감사|땡큐|thank|thx)', F),
    'bye': re.compile(r'^\s*(잘 ?가|바이|bye|수고(했|하셨|해))', F),
    'help': re.compile(r'(뭘|무엇을|뭐|어떤 걸|어떤 것을?)\s*(할 수|도와|해 ?줄 수|물어)|할 수 있는 (일|것|게|기능)|사용법|도움말|기능(이|은|을)?\s*(뭐|알려)|what can you|how (do|can) i use|\bhelp\b', F),
    'cmd': re.compile(r"(?:꺼|켜|끄|올려|내려|낮춰|높여|줄여|늘려|바꿔|맞춰|아껴|틀어|잡아|돌려|당겨|미뤄|멈춰|약하게 해|세게 해|강하게 해|(?:조절|조정|설정|해제|전환|완화|절약|절감|제어|차단|중지|정지|운영|감축|축소)\s?해)\s*(?:줘|주세요|주라|줄래|줄 ?수|봐|달라|주실|주시(?:겠|고|기|면\s?좋)|주면\s?좋|부탁)|(?:약하게|세게|강하게|어둡게|밝게|높게|낮게|덜\s?\S{1,4}게)\s*(?:해|틀어|돌려|맞춰|만들어)?\s*(?:줘|주세요|주시|주실|줄래|달라|부탁)|\b(turn|switch)\s+(on|off)\b|\bset\b.+\bto\b|\b(lower|raise|dim)\b|\b(please|can you|could you|would you|can we|could we|you could|let['’]?s|go ahead and)\s+(?:kindly\s+|please\s+|just\s+|maybe\s+)?(?:ease|dial|turn|lower|raise|reduce|cut|adjust|warm|cool|soften|switch|dim|bump|tone|make\s+(?:it|things|the\s+\w+)\s+(?:less|more|warmer|cooler|darker|dimmer|brighter)|bring\s+(?:it|the\s+\w+(?:\s+\w+)?)\s+(?:down|up))\b", F),
    'advice': re.compile(r'(줄이려면|낮추려면|아끼려면|절약하려면|절감하려면|막으려면|피하려면).*(뭘|무엇|어떻게|방법|조치|할\s?일|해야)|(줄이려면|낮추려면|아끼려면|절약하려면|절감하려면)\s*[?？]?\s*$|(뭘|무엇을|어떻게)\s*해야|(조치|제어)(를|가|는|은)?\s*(뭐|무엇|뭔|추천|제안|필요)|(해야\s?할|할\s?수\s?있는|취할|취해야\s?할)\s?(일|조치)|(줄일|낮출|아낄|절약할|절감할|막을|피할)\s?(수\s?있는\s?)?(방법|조치)|what should (we|i) (do|adjust|change|turn)|what to do\b|how (can|do|should) (we|i) (cut|reduce|lower|save|shave|bring down|avoid|keep)|\b(steps|actions|ways?|plan|list of actions)\s+(to|for)\b.{0,30}\b(cut|reduce|lower|save|shave|bring down)\b|\b(advise|recommend|suggest)\b.{0,50}\b(cut|reduce|lower|save|shave)\b', F),
    'energy': re.compile(r'(피크|전력|전기|요금|비용|부하|수전|냉방|난방|조명|전등|밝기|불|온도|에너지|탄소|한도|kW|절약|절감|에어컨|공조|배터리|ESS|EV|peak|power|load|cost|cooling|light|energy|temperature|air ?con|\bAC\b|HVAC|setpoint|thermostat|electric|bill|demand)', F),
    'b4': re.compile(r'(데이터 ?센터|\bB4\b|서버실|전기실|data ?cent|server room)', F),
    'cool': re.compile(r'(냉방|에어컨|공조|cool|\bAC\b|HVAC)', F),
    'down': re.compile(r'(꺼|끄|줄|낮|중지|멈|off|cut|reduce|lower|stop)', F),
    'overview': re.compile(r'(괜찮|상태\s?(어때|어떄|어떻|좋|는\s?어)|문제\s?(없|있)|이상\s?(없|있)|잘\s?(돌아|되고)|어떻게\s?돌아가|전반적|상황\s?(어때|어떻|좀)|how\s+are\s+(we|things)|everything\s+ok|overall|overview)', F),
    'subject': re.compile(r'(배터리|ESS|태양광|PV|EV|전기차|충전|건물|층|B[1-4]|방|조명|냉방|난방|요금|비용|탄소|날씨|DR|고장|센서|피크|한도|에이전트|한\s?(줄|문장)|one\s+(line|sentence)|battery|solar|building|floor|room|cost|price|carbon|weather|fault|sensor|peak|limit|agent)', F),
}
_BLD_RX = [(re.compile(r'오피스|타워|본관|office', re.I), 'B1'), (re.compile(r'연구동|lab\b|research', re.I), 'B2'),
           (re.compile(r'기숙사|dorm', re.I), 'B3'), (re.compile(r'데이터 ?센터|data ?cent', re.I), 'B4')]


def page_route(q, history=False):
    q = str(q or '').strip()
    short_q, energy = len(q) <= 24, bool(RX['energy'].search(q))
    if short_q and RX['thanks'].search(q):
        return 'thanks'
    if short_q and RX['bye'].search(q):
        return 'bye'
    if short_q and RX['greet'].search(q) and not energy:
        return 'greet'
    if RX['help'].search(q) and not energy:
        return 'help'
    if RX['b4'].search(q) and RX['cool'].search(q) and RX['down'].search(q):
        return 'b4'
    if RX['cmd'].search(q) and energy:
        return 'command' if page_command(q) else 'propose'
    if RX['advice'].search(q) and (energy or history):
        return 'command' if page_command(q) else 'propose'
    if RX['overview'].search(q) and not RX['subject'].search(q):
        return 'brief'
    return 'chat'


def page_command(q):
    """True when aiParseCommand would turn the request into cards without the model."""
    zones, rooms, blds = set(), set(), set()
    for m in re.finditer(r'\bB([1-4])\s*-?\s*F\s*(\d{1,2})(?:\s*-?\s*R\s*(\d{1,2}))?', q, F):
        zones.add('B%s-F%d' % (m.group(1), int(m.group(2))))
        if m.group(3):
            rooms.add('B%s-F%d-R%d' % (m.group(1), int(m.group(2)), int(m.group(3))))
    blds |= {'B' + m.group(1) for m in re.finditer(r'\bB([1-4])(?![-\d])', q, F)}
    blds |= {b for rx, b in _BLD_RX if rx.search(q)}
    fl = re.search(r'(\d{1,2})\s*층', q)
    if fl:
        zones |= {'%s-F%d' % (b, int(fl.group(1))) for b in blds}
    vacant = bool(re.search(r'(불|조명|전등|라이트|light)', q, re.I) and re.search(r'(빈|공실|아무도|비어|empty|vacant|unoccupied)', q, re.I))
    num = re.search(r'(\d{2}(?:\.\d)?)\s*(?:도|°\s*C|℃|degrees?\b)', q, re.I)
    temp = re.search(r'(온도|설정|냉방|난방|에어컨|공조|temperature|setpoint|cooling|heating|\bAC\b)', q, F) or re.search(r'(°|℃|\d\s*도\s*(로|까지|에))', q)
    light, off = re.search(r'(불|조명|전등|라이트|light)', q, re.I), re.search(r'(꺼|끄|소등|\boff\b)', q, F)
    on = not off and re.search(r'(켜|점등|\bon\b)', q, F)
    if num and temp and (zones or rooms):
        return True
    return bool(light and (off or on) and (rooms or zones or vacant))


def gateway_fixed(q, raw):
    """The gateway answers these without the model (server/mabems_server.py chat())."""
    return bool(assist.PROMPT_ASK.search(q) or assist.forecast_answer(q, raw) or assist.lookup_answer(q, raw)
                or assist.define_answer(q, raw) or assist.faq_answer(q, raw))


# ================================================================ assembling examples
def system_for(task):
    return SYSTEM_BASE + TASKS[task]['note']


DROPPED = Counter()                                   # bullet lines removed by fit(), per kind: fix the template if it grows


def fit(ans, ctx, q, task, kind):
    """The answer as the gateway's number check accepts it: optional support lines that fail it (a quoted alert whose room
    reading binds to its zone, ...) are dropped one by one. None when the conclusion itself fails or too little is left."""
    system = system_for(task)
    lines = ans.split('\n')
    head, bl = (None, lines) if task == 'brief' else (lines[0], lines[1:])
    if head is not None and not numcheck.check(head, ctx, q, rules=system)['ok']:
        DROPPED['head:' + kind] += 1
        return None
    kept = []
    for b in bl:
        trial = '\n'.join(([head] if head is not None else []) + kept + [b])
        if numcheck.check(trial, ctx, q, rules=system)['ok']:
            kept.append(b)
        else:
            DROPPED[kind] += 1
    need = 3 if task == 'brief' else 2
    if len(bl) >= need and len(kept) < need:
        DROPPED['lost:' + kind] += 1
        return None
    return '\n'.join(([head] if head is not None else []) + kept)


def chat_ctx(q, raw):
    """campus_state exactly as the gateway hands it to the model for a typed question."""
    return assist.model_view(assist.augment(q, raw))


def msg(task, ctx, question, answer, history=()):
    m = [{'role': 'system', 'content': system_for(task)}]
    for hq, ha in history:
        m += [{'role': 'user', 'content': hq}, {'role': 'assistant', 'content': ha}]
    m += [{'role': 'user', 'content': '<campus_state>\n' + ctx + '\n</campus_state>\n\n' + question}, {'role': 'assistant', 'content': answer}]
    return m


def answer(kind, c, r, q, gl):
    """(answer text, language) for a chat kind on context c (the parsed model-view context)."""
    if kind in KO:
        return KO[kind](c, r)
    if kind in EN:
        return EN[kind](c, r)
    if kind in NEEDS_Q:
        return NEEDS_Q[kind](c, r, q)
    if kind in GKEY:
        return concept(kind, c, r, gl)
    if kind in GKEY_EN:
        return concept_en(kind, c, r, gl)
    m = re.match(r'q_bld_(\w+)_(B\d)$', kind)
    if m:
        return q_bld(c, r, m.group(2), m.group(1))
    raise KeyError(kind)


class Bank:
    """Phrasings per kind, split into train / held-out. Old phrasings keep v2's split (v2.1 trained on its train part),
    new ones are split by a stable hash; the 66 real questions and near copies of them are never used; a phrasing that
    two kinds share is dropped (its intent is ambiguous). Only model-written phrasings are used: v1's hand-written seed
    questions (make_data.CHAT, UNKNOWN) and v2's hand-written one-sentence instructions are left out of v2.2."""

    def __init__(self, par_v2, split_v2, par_v22, realq, held_pct=25):
        rq = [norm(it['q']) for it in realq['items']] + [norm(h['content']) for it in realq['items'] for h in it.get('history', [])]
        self.realq = set(rq)
        self._rq = rq
        self.train, self.held, self.dropped = defaultdict(list), defaultdict(list), Counter()
        seen = {}
        old_train = {k: set(map(norm, v)) for k, v in split_v2['train'].items()}

        def add(kind, q, where):
            q = q.strip()
            k = norm(q)
            if not k:
                return
            if k in self.realq or any(difflib.SequenceMatcher(None, k, x).ratio() >= 0.88 for x in self._rq):
                self.dropped['realq'] += 1
                return
            if k in seen and seen[k][0] != kind:
                self.dropped['ambiguous'] += 1
                other = seen[k]
                for pool in (self.train, self.held):
                    if other[1] in pool[other[0]]:
                        pool[other[0]].remove(other[1])
                seen[k] = ('#', q)
                return
            if k in seen:
                return
            seen[k] = (kind, q)
            (self.train if where == 'train' else self.held)[kind].append(q)

        for k in OLD_KINDS + ['q_peak_en', 'q_cost_en']:
            pool = list(par_v2.get(k, [])) + list(par_v22.get(k + '@v22', []))
            if k in DROP:
                pool = [q for q in pool if not DROP[k].search(q)]
            for q in pool:
                where = 'train' if (norm(q) in old_train.get(k, set())) else 'held' if q in split_v2['held'].get(k, []) else ('held' if bucket(q) < held_pct else 'train')
                add(k, q, where)
        unk = [q for q in par_v2.get('unknown', []) if q not in DROP_UNKNOWN] + list(par_v22.get('unknown@v22', []))
        unk = [q for q in unk if not UNKNOWN_ANSWERABLE.search(q)]
        for q in unk:
            where = 'train' if norm(q) in old_train.get('unknown', set()) else 'held' if q in split_v2['held'].get('unknown', []) else ('held' if bucket(q) < held_pct else 'train')
            add('unknown', q, where)
        for k, qs in par_v22.items():
            if k.endswith('@v22') or k in OLD_KINDS or k in ('one_ko2', 'one_en2'):
                continue
            kind = k
            if k in DROP:
                qs = [q for q in qs if not DROP[k].search(q)]
            for q in qs:
                add(kind, q, 'held' if bucket(q) < held_pct else 'train')
        for k, base in (('one_ko2', 'one_ko'), ('one_en2', 'one_en')):   # run 2: more instructions, training only (after
            for q in par_v22.get(k, []):                                   # the split above, so held ones stay held)
                add(base, q, 'train')
        for pool in (self.train, self.held):
            for k in list(pool):
                pool[k] = [q for q in pool[k] if seen.get(norm(q), ('#',))[0] != '#']
            # request phrasings the page routes to chat (not to the proposal task) form their own chat kind
            pool['q_request_chat'] = [q for k in ('req_cool', 'req_light', 'req_advice') for q in pool.get(k, []) if page_route(q) == 'chat']


# chat kind weights (relative): the questions visitors ask most get more examples
def weights(bank):
    w = {k: 1.0 for k in OLD_KINDS}
    w.update({'q_load': 1.3, 'q_grid': 0.7, 'q_chiller': 0.8, 'q_peak_time': 1.0, 'q_savings': 1.0, 'q_why_ess': 1.0, 'q_hot': 0.8,
              'q_cold': 0.5, 'q_vacant_lights': 1.0, 'q_ev_count': 0.7, 'q_scenario': 0.7, 'q_capabilities': 0.5,
              'unknown': 1.6, 'q_offtopic': 1.3, 'followup': 1.0, 'q_request_chat': 0.8})
    blds = [k for k in bank.train if k.startswith('q_bld_')]
    w.update({k: 5.0 / max(1, len(blds)) for k in blds})       # run 2: 3.2 -> 5.0 (v2.2 improvised support lines here)
    fls = [k for k in bank.train if k.startswith('q_floor_')]
    w.update({k: 2.6 / max(1, len(fls)) for k in fls})
    w.update({k: 5.5 / len(GKEY) for k in GKEY})
    en = [k for k in list(EN) + ['q_unknown_en'] + list(GKEY_EN)]
    w.update({k: 3.2 / len(en) for k in en})
    return {k: v for k, v in w.items() if (bank.train.get(k) or k == 'followup') and k not in REQ_KINDS}


SUFFIX_KINDS = ('one_ko', 'one_en')                 # "answer in one sentence" instructions appended to questions (model-written)
FOLLOW_FROM = ['q_top', 'q_dr', 'q_ess', 'q_faults', 'q_peak', 'q_cost', 'q_forecast', 'q_maxtoday', 'q_comfort', 'q_chiller', 'q_load', 'q_hot']
# a short follow-up by what it asks → {previous kind: the kind whose answer answers it}
FOLLOW_KIND = [(re.compile(r'자세|구체|더 (알려|말해|설명)|풀어'), {k: k for k in FOLLOW_FROM}),
               (re.compile(r'언제까지|언제 끝|끝나'), {'q_dr': 'q_dr'}),
               (re.compile(r'왜|이유|어째서'), {'q_top': 'q_top', 'q_ess': 'q_why_ess', 'q_chiller': 'q_chiller', 'q_comfort': 'q_comfort'})]


def follow_target(f, prev):
    for rx, m in FOLLOW_KIND:
        if rx.search(f):
            return m.get(prev)
    return None


class Maker:
    def __init__(self, bank, pools, r, one, one_en, expect=False, p_one=0.18):
        self.bank, self.pools, self.r, self.one, self.one_en, self.expect = bank, pools, r, one, one_en, expect
        self.p_one = p_one
        self.skipped = Counter()

    def pick(self, kind, raw):
        """A phrasing of kind that reaches the model as a chat question on this context."""
        qs = self.pools.get(kind) or []
        for _ in range(12):
            if not qs:
                return None
            q = self.r.choice(qs)
            if kind.startswith('q_floor_'):
                q = self.floor_q(q)
            if page_route(q[0] if isinstance(q, tuple) else q) != 'chat':
                self.skipped['routed'] += 1
                continue
            qq = q[0] if isinstance(q, tuple) else q
            if gateway_fixed(qq, raw):
                self.skipped['gateway'] += 1
                continue
            return q
        return None

    def floor_q(self, tpl):
        bid = self.r.choice(['B1', 'B1', 'B2', 'B3', 'B3', 'B4'])
        top = FLOORS[bid]
        k = self.r.randint(1, top) if self.r.random() > 0.1 else top + self.r.randint(1, 3)
        return (tpl.replace('{층}', floor_phrase(self.r, bid, k)), '%s-F%d' % (bid, k))

    def chat(self, s, kind, history=None):
        """One chat example (dict) or None."""
        raw = s['chat']
        r = self.r
        if kind == 'followup':
            return self.followup(s)
        got = self.pick(kind, raw)
        if got is None:
            self.skipped['nophrasing'] += 1
            return None
        q, fid = (got if isinstance(got, tuple) else (got, None))
        ctx = chat_ctx(q, raw)
        c = json.loads(ctx)
        gl = c.get('glossary') or {}
        try:
            if fid:
                ans = q_floor(c, r, fid, kind.split('_')[-1])
            else:
                ans = answer(kind, c, r, q, gl)
        except Skip:
            self.skipped['skip:' + kind] += 1
            return None
        tag = kind
        en = bool(re.search(r'[A-Za-z]', q)) and not re.search(r'[가-힣]', q)
        if r.random() < self.p_one and kind not in ('q_offtopic', 'q_offtopic_en', 'q_capabilities', 'q_request_chat'):
            q = q + ' ' + r.choice(self.one_en if en else self.one)
            ctx = chat_ctx(q, raw)
            c2 = json.loads(ctx)
            if (c2.get('glossary') or {}) != gl:                      # the instruction changed what the gateway adds
                return None
            ans = head_only(ans)
            tag = kind + '+one'
        ans = fit(ans, ctx, q, 'chat', kind)
        if ans is None:
            return None
        hist = []
        if history is None and r.random() < 0.08:                       # an earlier turn in the conversation
            hist = self.prev_turn(s, kind)
        if hist:                                                        # the gateway prefixes short questions with the previous one
            turns = [{'role': 'user', 'content': hist[0][0]}, {'role': 'assistant', 'content': hist[0][1]}, {'role': 'user', 'content': q}]
            qf = assist.contextualize(turns)[-1]['content']
            if qf != q:
                ctxf = chat_ctx(qf, raw)
                gf = json.loads(ctxf).get('glossary') or {}
                key = GKEY.get(kind) or GKEY_EN.get(kind)
                ansf = None if (gateway_fixed(qf, raw) or (key and key not in gf)) else fit(ans, ctxf, qf, 'chat', kind)
                if ansf is None:
                    hist = []
                else:
                    q, ctx, ans = qf, ctxf, ansf
        row = {'task': 'chat', 'kind': tag, 'messages': msg('chat', ctx, q, ans, hist)}
        if hist:
            row['kind'] = tag + '+hist'
        return row

    def prev_turn(self, s, kind):
        r = self.r
        k2 = r.choice([k for k in FOLLOW_FROM if k != kind and self.pools.get(k)])
        q2 = self.pick(k2, s['chat'])
        if not q2:
            return []
        c2 = json.loads(chat_ctx(q2, s['chat']))
        try:
            return [(q2, answer(k2, c2, r, q2, c2.get('glossary') or {}))]
        except Skip:
            return []

    def followup(self, s):
        """A short follow-up, as the gateway rewrites it (assist.contextualize): '(앞 질문: …)\\n왜 그런 거야?'. The answer is
        the previous question's answer on the current data (its figures are what the follow-up is about)."""
        r = self.r
        fq = self.pools.get('followup') or []
        if not fq:
            return None
        f = r.choice(fq)
        k2 = r.choice([k for k in FOLLOW_FROM if self.pools.get(k)])
        k3 = follow_target(f, k2)
        if not k3:
            return None
        q2 = self.pick(k2, s['chat'])
        if not q2 or page_route(f, history=True) != 'chat':
            return None
        msgs = assist.contextualize([{'role': 'user', 'content': q2}, {'role': 'assistant', 'content': 'x'}, {'role': 'user', 'content': f}])
        q = msgs[-1]['content']
        if q == f:                                                        # not treated as a follow-up by the gateway
            return None
        raw = s['chat']
        if gateway_fixed(q, raw):
            return None
        ctx = chat_ctx(q, raw)
        c = json.loads(ctx)
        c_prev = json.loads(chat_ctx(q2, raw))
        try:
            prev = answer(k2, c_prev, r, q2, c_prev.get('glossary') or {})
            ans = answer(k3, c, r, q2, c.get('glossary') or {})
        except Skip:
            return None
        ans = fit(ans, ctx, q, 'chat', 'followup:' + k3)
        if ans is None:
            return None
        return {'task': 'chat', 'kind': 'followup:' + k3, 'messages': msg('chat', ctx, q, ans, [(q2, prev)])}


# ================================================================ proposals
def pressure(p):
    cp, f, dr = p['campus'], p.get('forecast') or {}, p.get('demandResponse') or {}
    tier = tier_key(p)
    fpct = f.get('next4hMaxPctOfLimit')
    return bool(dr.get('active') or cp['headroomNowPct'] < 12 or (fpct is not None and fpct >= 95) or (tier == 'peak' and cp['headroomNowPct'] < 20))


def needs(x, precond):
    """What the policy would do to this candidate room, ignoring the 4-action cap."""
    zone = x['id'].rsplit('-', 1)[0]
    out = []
    if not x.get('people') and x.get('lights') != 'off' and (x.get('lightLevelPct') or 0) >= 50:
        out.append('lights')
    if not x.get('people') and x.get('hvacMode') == 'cooling' and zone not in precond and x['setpointC'] < 27.5:
        out.append('setback')
    return out


def precond_zones(p):
    return set(re.findall(r'(B\d-F\d+) \d{2}:\d{2} 회의 예약', ' '.join(p.get('recentDecisions', []))))


def handle(x, r):
    """Make an empty room look the way the agents leave it: dark, and in setback (setpoint raised) or off."""
    x['lightLevelPct'] = 0
    if x.get('hvacMode') == 'cooling':
        if r.random() < 0.75:
            x['hvacMode'] = 'setback'
            x['setpointC'] = round(min(27.4, x['setpointC'] + r.choice([1.5, 2.0, 2.0, 2.5])), 1)
        else:
            x['hvacMode'] = 'off'
            x['setpointC'] = round(r.choice([26.0, 26.0, 26.5]), 1)
            x['kW'] = round(x['kW'] * 0.3, 2)


def variant(p, r, mode, fix_rooms=False):
    """quiet: every empty candidate room handled; partial: about half; single: all but one room that still needs action.
    None when the variant would not differ from the original or (single) no room needs anything. fix_rooms (run 2, training
    only): the page's rooms summary (vacantWithLightsOn and its list) drops the rooms that were switched off, as it would."""
    p = json.loads(json.dumps(p))
    lit_before = {x['id'] for x in p.get('candidateRooms', []) if not x.get('people') and (x.get('lightLevelPct') or 0) > 5}
    pre = precond_zones(p)
    rooms = [x for x in p.get('candidateRooms', []) if not x.get('people') and needs(x, pre)]
    if not rooms:
        return None
    if mode == 'single':
        keep = r.choice(rooms)
        for x in rooms:
            if x is not keep:
                handle(x, r)
    elif mode == 'partial':
        picked = [x for x in rooms if r.random() < 0.5]
        if not picked or len(picked) == len(rooms):
            return None
        for x in picked:
            handle(x, r)
    else:
        for x in rooms:
            handle(x, r)
    rm = p.get('rooms')
    if fix_rooms and isinstance(rm, dict):
        off = {x['id'] for x in p.get('candidateRooms', []) if x['id'] in lit_before and not (x.get('lightLevelPct') or 0) > 5}
        if off:
            listed = rm.get('vacantWithLightsOnRooms') or []
            rm['vacantWithLightsOnRooms'] = [y for y in listed if y.get('id') not in off]
            rm['vacantWithLightsOn'] = max(0, (rm.get('vacantWithLightsOn') or 0) - len(off))
    return p


def perturb(p, r):
    """Run 2, training only: drop the page's rooms / ev / assets summaries from some proposal contexts. v2.2 (run 1) tied its
    act-or-not decision to their presence: without them it proposed nothing in 47 of 57 old-format contexts that needed
    actions, and in 76 % of current ones (ablation). The policy reads only candidate rooms and zones, so the answer stays."""
    u = r.random()
    if u < 0.35:
        drop = ('rooms', 'ev', 'assets')
    elif u < 0.50:
        drop = (r.choice(['rooms', 'ev', 'assets']),)
    else:
        return p
    p = dict(p)
    for k in drop:
        p.pop(k, None)
    return p


def policy(p, r, kinds=('setpoint', 'roomSetpoint', 'roomLights'), request=None, en=False):
    """v1's policy (make_data.propose) with the text reordered: what the model writes first (expected_effect) names the
    reason and the target, so the decision is grounded before the target id. request='cool' relaxes zones without
    pressure (the operator asked for weaker cooling); request='light' allows light actions only."""
    cp, f, dr = p['campus'], p.get('forecast') or {}, p.get('demandResponse') or {}
    pct, tier = cp['headroomNowPct'], tier_key(p)
    fpct = f.get('next4hMaxPctOfLimit')
    press = pressure(p)
    pre = precond_zones(p)
    if en:
        why_p = ('demand response asks for %s kW' % n(dr.get('shedKW')) if dr.get('active') else
                 '%s%% (%s kW) headroom to the limit' % (n(pct), n(cp['headroomNowKW'])) if pct < 12 or tier == 'peak' else
                 'forecast peak %s kW (%s%% of the limit)' % (n(f.get('next4hMaxKW')), n(fpct)))
    else:
        why_p = ('DR %s kW 감축 요청 중' % n(dr.get('shedKW')) if dr.get('active') else
                 '한도 여유 %s%%(%s kW)' % (n(pct), n(cp['headroomNowKW'])) if pct < 12 or tier == 'peak' else
                 '향후 4시간 최대 %s kW(한도의 %s%%) 예측' % (n(f.get('next4hMaxKW')), n(fpct)))
    acts = []
    relax = 'setpoint' in kinds and (press or request == 'cool')
    if relax:
        for z in sorted(p.get('candidateZones', []), key=lambda z: -z['kW']):
            if z['occupancyPct'] < 60 and z['tempC'] <= z['setpointC'] + 0.7 and z['setpointC'] < 27:
                v = min(27.0, round((z['setpointC'] + 1.0) * 2) / 2)
                if en:
                    eff = ('%s: raise %s by 1 °C to cut its cooling load' % (why_p, z['id'])) if press else ('as requested, raise %s by 1 °C for weaker cooling' % z['id'])
                    why = '%s%% occupied, %s °C against a %s °C setpoint, so there is room to relax' % (n(z['occupancyPct']), n(z['tempC']), n(z['setpointC']))
                else:
                    eff = ('%s: %s 냉방 부하를 줄여 피크 여유를 늘림' % (why_p, z['id'])) if press else ('요청대로 %s 설정온도를 1 °C 올려 냉방을 약하게 함' % z['id'])
                    why = '재실 %s%%로 낮고 %s °C(설정 %s °C)라 1 °C 완화 여지가 있음' % (n(z['occupancyPct']), n(z['tempC']), n(z['setpointC']))
                acts.append({'type': 'setpoint', 'target': z['id'], 'value': '%g' % v, 'expected_effect': eff, 'reason': why})
            if len(acts) >= 2:
                break
    rooms = sorted(p.get('candidateRooms', []), key=lambda x: -x['kW'])
    if 'roomLights' in kinds:
        for x in rooms:
            if len(acts) >= 4:
                break
            if 'lights' in needs(x, pre):
                acts.append({'type': 'roomLights', 'target': x['id'], 'value': 'off',
                             'expected_effect': ('%s: switch off the lights of an empty room' % x['id']) if en else '%s 빈 방 조명을 꺼 조명 전력 절감' % x['id'],
                             'reason': ('nobody inside, lights at %s%%' % n(x['lightLevelPct'])) if en else '재실 0명인데 조명이 %s%% 켜져 있음' % n(x['lightLevelPct'])})
    if 'roomSetpoint' in kinds:
        for x in rooms:
            if len(acts) >= 4:
                break
            if 'setback' in needs(x, pre) and not any(a['target'] == x['id'] for a in acts):
                v = min(28.0, round((x['setpointC'] + 2.0) * 2) / 2)
                acts.append({'type': 'roomSetpoint', 'target': x['id'], 'value': '%g' % v,
                             'expected_effect': ('%s: set back an empty room still in full cooling, part of its %s kW' % (x['id'], n(x['kW']))) if en else
                                                '%s 빈 방 냉방을 셋백으로 낮춰 %s kW 중 일부 절감' % (x['id'], n(x['kW'])),
                             'reason': ('nobody inside, HVAC mode cooling at %s °C (setpoint %s °C), no booking pre-conditioning' % (n(x['tempC']), n(x['setpointC']))) if en else
                                       '재실 0명이고 공조가 cooling(냉방 중) 상태로 %s °C(설정 %s °C)이며 회의 예약 사전 공조 대상이 아님' % (n(x['tempC']), n(x['setpointC']))})
    acts = acts[:4]
    has = lambda t: any(a['type'] == t for a in acts)   # noqa: E731
    if acts:
        if en:
            parts = (['raise low-occupancy zones by 1 °C' + (' for peak headroom' if press else '')] if has('setpoint') else []) + \
                    (['switch off lights in empty rooms'] if has('roomLights') else []) + (['set back empty rooms still cooling'] if has('roomSetpoint') else [])
            summary = ('As requested: ' if request else 'Proposed: ') + ', '.join(parts) + '.'
        else:
            parts = (['재실이 낮은 층의 설정온도를 1 °C 올려 ' + ('피크 여유를 확보' if press else '냉방을 약하게')] if has('setpoint') else []) + \
                    (['빈 방 조명을 끄기'] if has('roomLights') else []) + (['빈 방 냉방을 셋백'] if has('roomSetpoint') else [])
            summary = ('요청에 맞춰 ' if request else '') + ', '.join(parts) + '를 제안합니다.'
    else:
        if en:
            what = {'light': 'no empty room has its lights on', 'cool': 'no low-occupancy zone can be relaxed and empty rooms are already set back'}.get(
                request, 'empty rooms are already dark and set back' + ('' if not press else ', and no low-occupancy zone can be relaxed'))
            summary = 'Nothing needs changing now: %s (headroom %s%%, %s kW).' % (what, n(pct), n(cp['headroomNowKW']))
        else:
            what = {'light': '조명이 켜진 빈 방이 없습니다', 'cool': '완화할 수 있는 재실 낮은 층이 없고 빈 방은 이미 셋백 상태입니다'}.get(
                request, ('피크 압박이 있지만 완화할 수 있는 재실 낮은 층이 없고 빈 방은 이미 셋백·소등 상태입니다' if press else '피크 압박이 없고 빈 방은 이미 셋백·소등 상태입니다'))
            summary = '지금은 바꿀 필요가 없습니다: 한도 여유 %s%%(%s kW), %s.' % (n(pct), n(cp['headroomNowKW']), what)
    return {'summary': summary, 'actions': acts}


def propose_row(p, r, kind, question=PROPOSE_Q, kinds=('setpoint', 'roomSetpoint', 'roomLights'), request=None, en=False):
    ctx = assist.model_view(json.dumps(p, ensure_ascii=False, separators=(',', ':')))
    ans = policy(json.loads(ctx), r, kinds, request, en)
    return {'task': 'propose', 'kind': kind, 'messages': msg('propose', ctx, question, json.dumps(ans, ensure_ascii=False, sort_keys=True))}


REQ_KINDS = {'req_cool': ('setpoint', 'roomSetpoint'), 'req_light': ('roomLights',), 'req_advice': ('setpoint', 'roomSetpoint', 'roomLights'),
             'req_cool_en': ('setpoint', 'roomSetpoint'), 'req_advice_en': ('setpoint', 'roomSetpoint', 'roomLights')}


def request_row(p, r, pools, kind):
    qs = [q for q in pools.get(kind, []) if page_route(q) == 'propose']
    if not qs:
        return None
    q = r.choice(qs)
    req = 'cool' if 'cool' in kind else 'light' if 'light' in kind else None
    row = propose_row(p, r, 'request:' + kind, q, REQ_KINDS[kind], req, en=kind.endswith('_en'))
    return row


# ================================================================ build
def explain_row(s, r):
    e = s['explain']
    ctx = assist.model_view(e['ctx'])
    c = json.loads(ctx)
    sel = c['selected']
    q = '설명해 줘: ' + sel.get('label', e['id'])
    ans = fit(v1.explain(c, sel, r), ctx, q, 'explain', 'explain-' + e['kind'])
    if ans is None:
        return None
    return {'task': 'explain', 'kind': 'explain-' + e['kind'], 'messages': msg('explain', ctx, q, ans)}


def brief_row(s, r, en=False):
    ctx = assist.model_view(s['chat'])
    c = json.loads(ctx)
    q, ans, kind = (BRIEF_Q_EN, brief_en(c, r), 'brief-en') if en else (BRIEF_Q, v1.brief(c, r), 'brief')
    ans = fit(ans, ctx, q, 'brief', kind)
    if ans is None:
        return None
    return {'task': 'brief', 'kind': kind, 'messages': msg('brief', ctx, q, ans)}


def build_train(samples, bank, seed, chat_per_sample=2, run2=False):
    r = random.Random(seed)
    W = weights(bank)
    mk = Maker(bank, bank.train, r, bank.train['one_ko'], bank.train['one_en'], p_one=0.22 if run2 else 0.18)
    out = []
    pt = (lambda q: perturb(q, r)) if run2 else (lambda q: q)
    for s in samples:
        p = json.loads(s['propose'])
        if r.random() < 0.32:
            out.append(propose_row(pt(p), r, 'propose'))
        calm = not pressure(p)                            # "nothing to change" needs no pressure: more quiet copies there
        for mode, prob in (('quiet', 0.65 if calm else 0.15), ('partial', 0.18), ('single', 0.22)):
            if r.random() < prob:
                v = variant(p, r, mode, fix_rooms=run2)
                if v:
                    out.append(propose_row(pt(v), r, 'propose-' + mode))
        if r.random() < 0.12:
            kind = r.choices(list(REQ_KINDS), weights=[3, 2, 3, 1, 1])[0]
            base = p if r.random() < 0.6 else (variant(p, r, r.choice(['quiet', 'partial']), fix_rooms=run2) or p)
            row = request_row(pt(base), r, bank.train, kind)
            if row:
                out.append(row)
        if r.random() < 0.04:
            out.append(propose_row(pt(p), r, 'propose-en', PROPOSE_Q_EN, en=True))
        if r.random() < 0.15:
            out.append(brief_row(s, r, en=r.random() < 0.12))
        if s.get('explain') and r.random() < 0.20:
            out.append(explain_row(s, r))
        out = [x for x in out if x]
        made, want = 0, chat_per_sample + (r.random() < 0.3)    # 2.3 chat questions per context on average
        for _ in range(want * 3):
            if made >= want:
                break
            kind = r.choices(list(W), weights=list(W.values()))[0]
            row = mk.chat(s, kind)
            if row:
                out.append(row)
                made += 1
    r.shuffle(out)
    return out, mk.skipped


def all_chat_kinds(bank):
    return sorted(k for k in set(bank.held) | {'followup'} if (bank.held.get(k) or k == 'followup') and k not in REQ_KINDS and k not in SUFFIX_KINDS)


def build_eval(samples, bank, seed):
    """Held-out sets on held-out conditions: every chat kind in turn (unseen phrasings), the tasks with the trained
    question, proposals where nothing needs changing, and typed requests."""
    r = random.Random(seed)
    mk = Maker(bank, bank.held, r, bank.held['one_ko'], bank.held['one_en'])
    kinds = all_chat_kinds(bank)
    chat, tasks, nothing, request = [], [], [], []
    ki = 0
    for i, s in enumerate(samples):
        made, tries = 0, 0
        while made < 3 and tries < 12:
            kind = kinds[ki % len(kinds)]
            ki += 1
            tries += 1
            row = mk.chat(s, kind, history=None)
            if row:
                chat.append(row)
                made += 1
        p = json.loads(s['propose'])
        if i % 2 == 0:
            tasks.append(propose_row(p, r, 'propose'))
        if i % 4 == 1:
            tasks.append(brief_row(s, r))
        if s.get('explain') and i % 4 == 3:
            tasks.append(explain_row(s, r))
        tasks = [x for x in tasks if x]
        if not pressure(p):
            v = variant(p, r, 'quiet')
            if v:
                nothing.append(propose_row(v, r, 'propose-quiet'))
        if i % 3 == 0:
            v = variant(p, r, 'single')
            if v:
                nothing.append(propose_row(v, r, 'propose-single'))
        if i % 3 == 2:
            kind = ['req_cool', 'req_light', 'req_advice', 'req_cool', 'req_advice', 'req_advice_en'][(i // 3) % 6]
            row = request_row(p, r, bank.held, kind)
            if row:
                request.append(row)
    return {'eval22_chat.jsonl': chat, 'eval22_tasks.jsonl': tasks, 'eval22_nothing.jsonl': nothing, 'eval22_request.jsonl': request}, mk.skipped


# ================================================================ checks
def split_user(x):
    user = x['messages'][-2]['content']
    ctx = user.split('<campus_state>\n', 1)[1].split('\n</campus_state>', 1)[0]
    return ctx, user.split('\n</campus_state>\n\n', 1)[1]


def signatures(system):
    """The system-prompt line prefixes the gateway's SafeStream stops streaming at (server/assist.py)."""
    return [ln.strip(' -')[:40] for ln in system.splitlines() if len(ln.strip(' -')) >= 24]


def verify(rows, show=6):
    """Every text answer must pass the gateway's number check against the context the model sees, and no answer may
    quote a system-prompt line (the gateway cuts the stream there and would replace two such lines with a refusal)."""
    bad = []
    for x in rows:
        a = x['messages'][-1]['content']
        sig = [s for s in signatures(x['messages'][0]['content']) if s in a]
        if sig:
            bad.append((x['kind'], ['quotes the system prompt: ' + sig[0]], a))
        if x['task'] == 'propose':
            continue
        ctx, q = split_user(x)
        chk = numcheck.check(a, ctx, q, rules=x['messages'][0]['content'])
        if not chk['ok']:
            bad.append((x['kind'], chk['unmatched'], a))
    for b in bad[:show]:
        print('  numcheck FAIL', b[0], b[1], b[2].replace('\n', ' / ')[:260])
    return bad


def fmt_ok(x):
    a = x['messages'][-1]['content']
    lines = [l for l in a.splitlines() if l.strip()]
    bl = [l for l in lines if l.startswith('- ')]
    if x['task'] == 'brief':
        return 3 <= len(bl) <= 5
    if '+one' in x['kind']:
        return len(lines) == 1
    return bool(lines) and not lines[0].startswith('-') and 2 <= len(bl) <= 4


def stats(rows):
    tok = sum(len(m['content']) for x in rows for m in x['messages'])
    empty = sum(1 for x in rows if x['task'] == 'propose' and not json.loads(x['messages'][-1]['content'])['actions'])
    return {'n': len(rows), 'tasks': dict(Counter(x['task'] for x in rows)), 'empty_proposals': empty,
            'kinds': dict(Counter(re.sub(r'\+.*|:.*', '', x['kind']) for x in rows).most_common()),
            'chars': tok, 'format_ok': sum(fmt_ok(x) for x in rows if x['task'] != 'propose')}


def main():
    tr_path, ev_path, out_dir = sys.argv[1:4]
    data = ROOT / 'ft' / 'data'
    bank = Bank(json.load(open(data / 'paraphrases.json', encoding='utf-8')), json.load(open(data / 'v2' / 'questions_split.json', encoding='utf-8')),
                json.load(open(data / 'v22' / 'paraphrases_v22.json', encoding='utf-8')), json.load(open(data / 'realq.json', encoding='utf-8')))
    tr = [json.loads(l) for l in open(tr_path, encoding='utf-8')]
    ev = [json.loads(l) for l in open(ev_path, encoding='utf-8')]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run2 = '--run2' in sys.argv
    train, sk_t = build_train(tr, bank, 1, run2=run2)
    sets, sk_e = build_eval(ev, bank, 2)
    if run2:                                          # the evaluated sets must stay exactly as they are
        import hashlib as _h
        for name, rows in sets.items():
            text = ''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows)
            old = (out / name).read_text(encoding='utf-8') if (out / name).exists() else ''
            print('eval set %s unchanged: %s' % (name, _h.md5(text.encode()).hexdigest() == _h.md5(old.encode()).hexdigest()))
    train_name = 'train_v22b.jsonl' if run2 else 'train_v22.jsonl'
    sets = {train_name: train, **({} if run2 else sets)}
    report = {'phrasings': {'train': sum(map(len, bank.train.values())), 'held': sum(map(len, bank.held.values())), 'dropped': dict(bank.dropped)},
              'skipped_train': dict(sk_t), 'skipped_eval': dict(sk_e)}
    print('phrasings', report['phrasings'])
    # held-out integrity: no evaluation question was trained on, and none of the 66 real questions is in training
    fixed = {norm(PROPOSE_Q), norm(PROPOSE_Q_EN), norm(BRIEF_Q), norm(BRIEF_Q_EN)}
    def asked(rows):
        out = set()
        for x in rows:
            q = split_user(x)[1].rsplit('\n', 1)[-1]                 # the typed question (follow-ups: after the lead line)
            for one in bank.train['one_ko'] + bank.held['one_ko'] + bank.train['one_en'] + bank.held['one_en']:
                q = q.replace(' ' + one, '')
            if not q.startswith('설명해 줘:') and norm(q) not in fixed:
                out.add(norm(q))
        return out
    q_train = asked(train)
    q_eval = set().union(*(asked(v) for v in build_eval(ev, bank, 2)[0].values()))
    leak = q_train & q_eval
    real = q_train & bank.realq
    report['heldout'] = {'train_questions': len(q_train), 'eval_questions': len(q_eval), 'overlap': sorted(leak)[:20], 'realq_in_train': sorted(real)}
    print('held-out check: %d train questions, %d eval questions, overlap %d, real questions in train %d' % (len(q_train), len(q_eval), len(leak), len(real)))
    failed = 0
    for name, rows in sets.items():
        bad = verify(rows)
        failed += len(bad)
        st = stats(rows)
        st['numcheck_fail'] = len(bad)
        report[name] = st
        print(name, st['n'], st['tasks'], 'empty proposals', st['empty_proposals'], 'numcheck failures', len(bad), 'format ok', st['format_ok'])
        if '--check-only' not in sys.argv:
            with open(out / name, 'w', encoding='utf-8') as f:
                for x in rows:
                    f.write(json.dumps(x, ensure_ascii=False) + '\n')
    if '--check-only' not in sys.argv:
        if not run2:
            json.dump({'train': bank.train, 'held': bank.held}, open(out / 'questions_split.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        json.dump(report, open(out / ('stats_v22b.json' if run2 else 'stats.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('lines dropped by the number check', dict(DROPPED.most_common(15)))
    report['dropped_lines'] = dict(DROPPED)
    print('skipped train', dict(sk_t.most_common(12)))
    print('skipped eval', dict(sk_e.most_common(12)))
    if failed:
        print('NUMCHECK FAILURES:', failed)


if __name__ == '__main__':
    main()
