"""v2 fine-tuning data: v1's rule-written answers (make_data.py) plus the fixes the v1 evaluation asked for.

    python make_data_v2.py paraphrases.json samples_train.jsonl samples_eval.jsonl out_dir

What changes from v1 (ft/README.md "개선안(v2)"):
  1. Varied questions: each chat intent is asked with ~30 paraphrases written by an open-weight model
     (gen_paraphrases.py, DeepSeek on Fireworks; Claude output is still kept out of the data). 20 % of the
     paraphrases of every intent are held out for eval_gen.jsonl and never appear in training.
  2. Format instructions are followed: "한 문장으로만", "결론만" … → the conclusion sentence alone.
  3. Answerable questions are answered, not refused: new intents whose answer is in the data although they sound
     like they might not be (most expensive hours, outdoor temperature, today's highest import, CO2, EV, PV
     self-consumption). Refusals stay for questions the data really cannot answer (~60, model-written, reviewed).
  4. Proposal JSON is written with keys in alphabetical order, the order Ollama's grammar forces at inference
     (actions before summary, expected_effect … value inside an action), so the decision is learned in that order.
  5. More "nothing to do" proposals: contexts without pressure whose empty rooms are made dark and in setback, so
     the policy proposes nothing (about 1 in 6 proposals).
Outputs: train.jsonl, eval_gen.jsonl (unseen phrasings and the new behaviours on unseen conditions),
eval_nothing.jsonl (unseen conditions where nothing needs changing). v1's eval.jsonl stays the main comparison set.
"""
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_data as v1  # noqa: E402
from make_data import n, money, bullets, msg, ess_desc, tier_name  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
import numcheck  # noqa: E402


# ---------------------------------------------------------------- new answerable intents
def q_tariff(c, r):
    t = c['tariff']
    sym = '₩' if t.get('currency') == '₩' else '$'
    head = '요금이 가장 비싼 시간은 피크 시간대 %s이고, 지금 %s은 %s 구간으로 %s%s/kWh입니다.' % (t['peakHours'], c['clock'], tier_name(c), sym, n(t['pricePerKWh']))
    dm = (c.get('dayMetrics') or {}).get('agent') or {}
    lines = ['오늘 최대 수전은 %s kW였습니다(한도 %s kW)' % (n(c['today']['highestGridImportTodayKW']), n(c['campus']['peakLimitKW']))]
    if dm.get('avgPrice') is not None:
        lines.append('오늘 지금까지 평균 단가는 %s%s/kWh입니다' % (sym, n(dm['avgPrice'])))
    lines.append('오늘 비용은 %s입니다' % money(c, c['today']['costAgent']))
    return head + '\n' + bullets(lines)


def q_temp(c, r):
    w, cp = c['weather'], c['campus']
    head = '%s 현재 바깥 기온은 %s °C입니다.' % (c['clock'], n(w['outdoorC']))
    lines = ['일사량은 %s W/m²입니다' % n(w['irradianceWm2']), '냉동기는 %s kW를 쓰고 있습니다' % n(cp['chillerNowKW'])]
    return head + '\n' + bullets(lines)


def q_maxtoday(c, r):
    t, cp = c['today'], c['campus']
    dm = (c.get('dayMetrics') or {}).get('agent') or {}
    hi, lim = t['highestGridImportTodayKW'], cp['peakLimitKW']
    over = dm.get('minutesOverLimit')
    if hi <= lim:
        head = '오늘 최대 수전은 %s kW로, 피크 한도 %s kW를 넘지 않았습니다.' % (n(hi), n(lim))
    else:
        head = '오늘 최대 수전은 %s kW로, 피크 한도 %s kW보다 높았던 때가 있습니다.' % (n(hi), n(lim))   # numcheck flags 초과/넘 while import is below
    lines = ['지금 계통 수전은 %s kW입니다' % n(cp['gridImportNowKW'])]
    if over is not None:
        lines.append('오늘 피크 한도를 웃돈 시간은 모두 %s분입니다' % n(over))
    base = (c.get('dayMetrics') or {}).get('baseline') or {}
    if base.get('peakKW') is not None:
        lines.append('같은 조건의 룰 기반 BMS 최대 수전은 %s kW입니다' % n(base['peakKW']))
    return head + '\n' + bullets(lines)


def q_co2(c, r):
    dm = c.get('dayMetrics') or {}
    a, b = dm.get('agent') or {}, dm.get('baseline') or {}
    if a.get('co2Kg') is None:
        return v1.q_unknown(c, r, '오늘 탄소 배출량')
    head = '%s까지 오늘 탄소 배출량은 %s kg입니다.' % (c['clock'], n(a['co2Kg']))
    lines = ['같은 조건의 룰 기반 BMS는 %s kg입니다' % n(b['co2Kg'])] if b.get('co2Kg') is not None else []
    lines.append('오늘 사용 전력량은 %s kWh입니다' % n(c['today']['energyKWh']))
    if a.get('pvUsedKWh') is not None:
        lines.append('태양광 %s kWh를 자체 소비했습니다' % n(a['pvUsedKWh']))
    return head + '\n' + bullets(lines)


def q_ev(c, r):
    cp = c['campus']
    a = (c.get('dayMetrics') or {}).get('agent') or {}
    head = ('EV 충전기는 지금 %s kW를 쓰고 있습니다.' % n(cp['evNowKW'])) if cp.get('evNowKW') else '지금 충전 중인 EV는 없습니다(충전 전력 0 kW).'
    lines = []
    if a.get('evSessions') is not None:
        lines.append('오늘 충전 세션 %s건 중 %s건이 목표를 채웠습니다(%s%%)' % (n(a['evSessions']), n(a.get('evMet', 0)), n(a.get('evMetPct', 0))))
    d = v1.dec(c, 'EV 충전 에이전트')
    if d:
        lines.append('EV 충전 에이전트: ' + v1.short(d[0]).split(': ', 1)[-1])
    lines.append('계통 수전 %s kW, 한도 %s kW입니다' % (n(cp['gridImportNowKW']), n(cp['peakLimitKW'])))
    return head + '\n' + bullets(lines)


def q_pvself(c, r):
    a = (c.get('dayMetrics') or {}).get('agent') or {}
    if a.get('pvGenKWh') is None:
        return v1.q_unknown(c, r, '태양광 자가소비율')
    head = '오늘 태양광은 %s kWh를 발전했고, 그중 %s%%를 캠퍼스에서 자체 소비했습니다.' % (n(a['pvGenKWh']), n(a['pvSelfPct']))
    lines = ['자체 소비량은 %s kWh입니다' % n(a['pvUsedKWh']), '지금 발전량은 %s kW입니다' % n(c['campus']['pvNowKW'])]
    return head + '\n' + bullets(lines)


FN = {f.__name__: f for f in [v1.q_peak, v1.q_cost, v1.q_top, v1.q_ess, v1.q_pv, v1.q_comfort, v1.q_agents, v1.q_weather,
                               v1.q_dr, v1.q_faults, v1.q_forecast, v1.q_peak_en, v1.q_cost_en,
                               q_tariff, q_temp, q_maxtoday, q_co2, q_ev, q_pvself]}

# paraphrases that ask for something the intent's answer does not contain (per-charger status, what-if, analysis)
DROP = {
    'q_ev': re.compile(r'자리|몇 개|목록|대기|충전소별|고장|붐비|완료된|중단|이용률|예약|한가|포트|시작 가능|구분|점검|문제|끊긴|공간|현황판|충전기별|돌아가나요'),
    'q_weather': re.compile(r'예측|예상|얼마나 더|변동 폭|민감|상관관계|분석|떨어지면'),
    'q_forecast': re.compile(r'그래프|어디서|업데이트|계산'),
    'q_agents': re.compile(r'큐|프로세스'),
}
DROP_UNKNOWN = {'다음 주 월요일 피크 시간대는 언제인가요?', '캠퍼스가 속한 지역의 시간대별 요금표 원본은?', '현재 전기 계약 종류와 계약전력은?',
                '전기요금 누진제 적용 구간은?', '오늘 이후 5시간 뒤 피크 예측은?', '오늘 이전의 에이전트 조치 로그 전체는?'}
ONE_TRAIN = ['한 문장으로만 답해줘.', '한 줄로 요약해 줘.', '결론만 짧게 말해줘.', '근거는 빼고 결론만.', '짧게 한 문장으로.', '길게 말고 한 문장만.']
ONE_EVAL = ['딱 한 문장으로.', '요약 한 줄만 부탁해.']
ONE_EN = ['Answer in one sentence.', 'Just one line, please.']


def split_questions(par, seed):
    r = random.Random(seed)
    train, held = {}, {}
    for k, qs in par.items():
        if k == 'unknown':
            qs = [q for q in qs if q not in DROP_UNKNOWN]
        elif k in DROP:
            qs = [q for q in qs if not DROP[k].search(q)]
        qs = list(qs)
        r.shuffle(qs)
        cut = max(1, round(len(qs) * 0.2))
        held[k], train[k] = qs[:cut], qs[cut:]
    for fn, seeds in v1.CHAT:                 # v1's own questions stay in training
        train[fn.__name__] = list(dict.fromkeys(train.get(fn.__name__, []) + seeds))
    train['unknown'] = list(dict.fromkeys(train['unknown'] + v1.UNKNOWN))
    held['q_tariff'] = list(dict.fromkeys(held['q_tariff'] + ['오늘 가장 비싼 시간대는?']))   # the v1 over-refusal case
    train['q_tariff'] = [q for q in train['q_tariff'] if q != '오늘 가장 비싼 시간대는?']
    return train, held


def head_only(ans):
    return ans.split('\n', 1)[0]


def chat_rows(c, s, r, qs, one, kinds_weight):
    """One chat example: an intent, a phrasing, and in ~20 % of cases a one-sentence instruction."""
    kind = r.choices(list(kinds_weight), weights=list(kinds_weight.values()))[0]
    q = r.choice(qs[kind])
    ans = v1.q_unknown(c, r, q) if kind == 'unknown' else FN[kind](c, r)
    tag = kind
    if r.random() < 0.2:
        en = kind.endswith('_en')
        q = q + ' ' + r.choice(ONE_EN if en else one)
        ans = head_only(ans)
        tag = kind + '+one'
    return {'task': 'chat', 'kind': tag, 'messages': msg('chat', s['chat'], q, ans)}


def pressure(p):
    cp, f, dr = p['campus'], p.get('forecast') or {}, p.get('demandResponse') or {}
    tier = p['tariff']['tier'].get('tier') if isinstance(p['tariff'].get('tier'), dict) else p['tariff'].get('tier')
    fpct = f.get('next4hMaxPctOfLimit')
    return bool(dr.get('active') or cp['headroomNowPct'] < 12 or (fpct is not None and fpct >= 95) or (tier == 'peak' and cp['headroomNowPct'] < 20))


def quiet(s, r=None, share=1.0):
    """The same context with empty rooms already dark and in setback (all of them, or a random share of them when r is
    given), so the policy has nothing, or less, to do. Returns None under pressure (zones would still be relaxed) and,
    for a partial copy, when no room was changed."""
    p = json.loads(s['propose'])
    if pressure(p):
        return None
    changed = 0
    for x in p.get('candidateRooms', []):
        if not x.get('people') and (r is None or r.random() < share):
            if x.get('lights') != 'off' and (x.get('lightLevelPct') or 0) > 0:
                x['lightLevelPct'] = 0
                changed += 1
            if x.get('hvacMode') == 'cooling':
                x['hvacMode'] = 'setback'
                changed += 1
    if r is not None and not changed:
        return None
    return json.dumps(p, ensure_ascii=False, separators=(',', ':'))


def propose_row(ctx, r, kind='propose'):
    ans = v1.propose(json.loads(ctx), r)
    return {'task': 'propose', 'kind': kind, 'messages': msg('propose', ctx, '앞으로 1시간 동안의 제어 조치를 제안해 줘.', json.dumps(ans, ensure_ascii=False, sort_keys=True))}


WEIGHTS = {k: 1.0 for k in FN}
WEIGHTS.update({'q_peak_en': 0.6, 'q_cost_en': 0.6, 'unknown': 1.6})


def build_train(samples, qs, seed):
    r = random.Random(seed)
    out = []
    for s in samples:
        c = json.loads(s['chat'])
        if r.random() < 0.40:
            out.append(propose_row(s['propose'], r))
        if r.random() < 0.35:                    # v2.1: 0.10 left "nothing to do" at 0 of 33 on unseen conditions
            qctx = quiet(s)
            if qctx:
                out.append(propose_row(qctx, r, 'propose-quiet'))
        if r.random() < 0.20:                    # some rooms already handled: the policy must read each room's state
            qctx = quiet(s, r, 0.5)
            if qctx:
                out.append(propose_row(qctx, r, 'propose-partial'))
        if r.random() < 0.20:
            out.append({'task': 'brief', 'kind': 'brief', 'messages': msg('brief', s['chat'], '현재 운영 상황을 브리핑해 줘.', v1.brief(c, r))})
        if s.get('explain') and r.random() < 0.25:
            e = s['explain']
            sel = json.loads(e['ctx'])['selected']
            out.append({'task': 'explain', 'kind': 'explain-' + e['kind'], 'messages': msg('explain', e['ctx'], '설명해 줘: ' + sel.get('label', e['id']), v1.explain(c, sel, r))})
        for _ in range(2):
            out.append(chat_rows(c, s, r, qs, ONE_TRAIN, WEIGHTS))
    r.shuffle(out)
    return out


def build_eval_gen(samples, held, seed):
    """Unseen conditions × unseen phrasings: every intent, the one-sentence instruction, unknowns, the new intents."""
    r = random.Random(seed)
    out = []
    kinds = [k for k in FN] + ['unknown']
    for i, s in enumerate(samples):
        c = json.loads(s['chat'])
        for k in r.sample(kinds, 2):
            row = chat_rows(c, s, r, held, ONE_EVAL, {k: 1})
            out.append(row)
    return out


def build_eval_nothing(samples, seed):
    r = random.Random(seed)
    out = []
    for s in samples:
        q = quiet(s)
        if q:
            out.append(propose_row(q, r, 'propose-quiet'))
    return out


def verify(rows):
    bad = 0
    for x in rows:
        if x['task'] == 'propose':
            continue
        user = x['messages'][1]['content']
        ctx = user.split('<campus_state>\n', 1)[1].split('\n</campus_state>', 1)[0]
        q = user.rsplit('\n\n', 1)[-1]
        chk = numcheck.check(x['messages'][2]['content'], ctx, q, rules=x['messages'][0]['content'])
        if not chk['ok']:
            bad += 1
            if bad <= 5:
                print('numcheck fail', x['kind'], chk['unmatched'], x['messages'][2]['content'][:200])
    return bad


if __name__ == '__main__':
    par_path, tr_path, ev_path, out_dir = sys.argv[1:5]
    par = json.load(open(par_path, encoding='utf-8'))
    qs, held = split_questions(par, 7)
    tr = [json.loads(l) for l in open(tr_path, encoding='utf-8')]
    ev = [json.loads(l) for l in open(ev_path, encoding='utf-8')]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sets = {'train.jsonl': build_train(tr, qs, 1), 'eval_gen.jsonl': build_eval_gen(ev, held, 2), 'eval_nothing.jsonl': build_eval_nothing(ev, 3)}
    for name, rows in sets.items():
        with open(out / name, 'w', encoding='utf-8') as f:
            for x in rows:
                f.write(json.dumps(x, ensure_ascii=False) + '\n')
        text = [x for x in rows if x['task'] != 'propose']
        empty = sum(1 for x in rows if x['task'] == 'propose' and not json.loads(x['messages'][2]['content'])['actions'])
        print(name, len(rows), dict(Counter(x['task'] for x in rows)), 'empty proposals', empty,
              'numcheck failures %d/%d' % (verify(rows), len(text)))
    json.dump({'train': qs, 'held': held}, open(out / 'questions_split.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
