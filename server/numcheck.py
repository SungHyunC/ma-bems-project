"""Numeric cross-check for LLM-written text.

Ported from multi-agent-bems backend/agents/numbers.py and adapted to MA-BEMS: ids look like
B1, B1-F3, B1-F3-R2, the facts are the campus_state JSON the model was given, and the question
counts as a fact too.

Every number in an answer must be backed by the facts (within rounding). The gateway escalates a
local answer that fails the check to Claude and marks a Claude answer that fails it, so the page
can warn the operator instead of showing an invented number as data.

    check(answer, facts_json, question, rules) -> {'ok': bool, 'checked': int, 'unmatched': [str]}

Backed values: every number in the facts (recursively, including inside strings), floor / room
numbers of ids, clock times, the question's own numbers, the numbers in the operating rules the model
was given (rules = the system prompt, e.g. the ±1.5 °C comfort band), small counts (0-10), plus differences and
sums of any two headline campus numbers (so '1,000 - 760 = 240 kW' passes).
Matching: x with d decimals matches v when |x - v| <= max(0.5 * 10^-d, 1% of |v|); 'x%' also
matches the fraction x/100; 'x시간' / 'x h' also match x*60 minutes and 'x분' also x/60 hours.
Labelled facts (peak limit / 상한·한도 in kW, SOC in %) must match their own field, not just any number,
and a sentence saying the limit is exceeded while grid import is below it fails as a contradiction.
"""
import json
import math
import re

_ID_RE = re.compile(r'\bB\d(?:-F\d{1,2}(?:-R\d{1,2})?)?\b|\b(?:AHU|CRAC|CRAH|EV|ESS|PV)-?\d+\b|\bqwen\S*|\bclaude\S*', re.I)
_IDNUM_RE = re.compile(r'\bB(\d)(?:-F(\d{1,2})(?:-R(\d{1,2}))?)?\b')
_TIME_RE = re.compile(r'(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])')
_NUM_RE = re.compile(r'(?<![A-Za-z0-9_.])([-+]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?')
_PCT = re.compile(r'^\s*%')
_HRS = re.compile(r'^\s*(?:시간|h\b|hr\b|hours?\b)')
_MIN = re.compile(r'^\s*(?:분|min\b|minutes?\b)')
REL = 0.01


def _num(m):
    return float(m.group(2).replace(',', '') + (m.group(3) or ''))


def _scan(text, values, times):
    for m in _IDNUM_RE.finditer(text):
        for g in m.groups():
            if g:
                values.append(float(g))
    for m in _TIME_RE.finditer(text):
        times.add('%02d:%02d' % (int(m.group(1)), int(m.group(2))))
        values.extend([float(m.group(1)), float(m.group(2))])
    stripped = _TIME_RE.sub(' ', _ID_RE.sub(' ', text))
    for m in _NUM_RE.finditer(stripped):
        values.append(_num(m))


def _walk(v, values, times, headline):
    if v is None or isinstance(v, bool):
        return
    if isinstance(v, (int, float)):
        if math.isfinite(v):
            values.append(abs(float(v)))
    elif isinstance(v, str):
        _scan(v, values, times)
    elif isinstance(v, dict):
        for k, item in v.items():
            _scan(str(k), values, times)
            _walk(item, values, times, headline)
    elif isinstance(v, (list, tuple)):
        for item in v:
            _walk(item, values, times, headline)


def _allowed(facts_json, question, rules=''):
    values, times, headline = [], set(), []
    try:
        facts = json.loads(facts_json) if facts_json else {}
    except ValueError:
        facts = facts_json or ''
    _walk(facts, values, times, headline)
    _scan(question or '', values, times)
    _scan(rules or '', values, times)                     # the system prompt's rules and campus description
    if isinstance(facts, dict):                           # headline numbers: campus totals + today's figures
        for key in ('campus', 'today', 'tariff'):
            part = facts.get(key)
            if isinstance(part, dict):
                headline.extend(abs(float(x)) for x in part.values() if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x))
    derived = []
    for i, a in enumerate(headline):
        for b in headline[i + 1:]:
            derived.extend((abs(a - b), a + b))
    values.extend(derived)
    values.extend(float(n) for n in range(0, 11))
    values.extend((24.0, 60.0, 100.0, 15.0))
    return values, times


def _match(x, decimals, values):
    tol = max(0.5 * 10 ** -decimals, 1e-9)
    for v in values:
        if abs(x - v) <= max(tol, REL * v):
            return True
    return False


# Labelled facts: a number written right after one of these labels must match that very field, not merely
# some number in the data. The loose rule above accepts any value within 1 % of any of the hundreds of numbers
# in campus_state, so an 8B answer saying "상한 940 kW" (limit is 1000 kW) passed it: 940 sat near an unrelated
# value. Only unambiguous single facts are listed; loose words such as 수전 / 여유 legitimately carry several values.
_LABELS = [
    (re.compile(r'(?:피크\s*)?(?:상한|한도)|peak\s*limit', re.I), 'kW', ('campus', 'peakLimitKW')),
    (re.compile(r'(?<![A-Za-z])SOC(?![A-Za-z])|충전\s*상태', re.I), '%', ('campus', 'essSocPct')),   # not \b: Hangul particles are word characters
]
_AFTER_LABEL = re.compile(r'\s*(?:of|is|은|는|이|가|:|=|\()?\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(kW|%)', re.I)


_SQUASH = re.compile(r'[\s,]')


def _labelled(text, facts, facts_text=''):
    bad, quoted = [], _SQUASH.sub('', facts_text or '')
    for label, unit, (grp, key) in _LABELS:
        part = facts.get(grp) if isinstance(facts, dict) else None
        v = part.get(key) if isinstance(part, dict) else None
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        for m in label.finditer(text):
            n = _AFTER_LABEL.match(text, m.end())
            if not n or n.group(3).lower() != unit.lower():
                continue
            x = float(n.group(1).replace(',', '') + (n.group(2) or ''))
            d = len(n.group(2)) - 1 if n.group(2) else 0
            # quoted from the data, e.g. the coordinator's log line "상한 940 kW 이내" (its own 94 % cap): not a misread limit
            if quoted and _SQUASH.sub('', text[m.start():n.end()]) in quoted:
                continue
            if not _match(x, d, [abs(float(v))]):
                bad.append('%s %s%s (%s %s)' % (m.group(0).strip(), n.group(1) + (n.group(2) or ''), unit, 'data', ('%g' % v) + unit))
    return bad


# State contradiction: right numbers, wrong meaning. The 8B model twice called the headroom an excess ("한도를
# 154.2kW 초과" while 154.2 kW was the room left below the limit). A sentence that puts the limit and "over" together,
# with no negation, forecast or baseline word, contradicts a grid import that is below the limit.
_LIMIT_W = re.compile(r'상한|한도|peak\s*limit', re.I)
_OVER_W = re.compile(r'초과|넘(?:어|었|는|음|긴)|exceed|\bover\b', re.I)
# rule wording is calm too: "한도 92% 넘는 부분을 깎음", "한도를 넘으면 기본요금이 오릅니다" (glossary sentences)
_CALM_W = re.compile(r'예측|기준|BMS|않|없|방지|이내|미만|아래|위험|가능|우려|대비|막|피하|0\s*분|넘으면|넘을\s?때|넘는\s?부분|깎|'
                     r'forecast|baseline|avoid|prevent|risk|below|within|not\b|never|no\b|shav|when\b|if\b', re.I)


def _contradictions(text, facts):
    campus = facts.get('campus') if isinstance(facts, dict) else None
    if not isinstance(campus, dict):
        return []
    g, lim = campus.get('gridImportNowKW'), campus.get('peakLimitKW')
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (g, lim)) or g > lim:
        return []                                         # really over the limit (or unknown): nothing to contradict
    for sent in re.split(r'(?<=[.!?])\s+|\n+', text):
        if _LIMIT_W.search(sent) and _OVER_W.search(sent) and not _CALM_W.search(sent):
            return ['"초과/over" ↔ %g kW < %g kW' % (g, lim)]
    return []


def check(text, facts_json, question='', rules=''):
    values, times = _allowed(facts_json, question, rules)
    unmatched, checked = [], 0
    try:
        facts = json.loads(facts_json) if facts_json else {}
    except ValueError:
        facts = {}
    malformed = [m[0] for m in re.finditer(r'(?<![\w.])\d+(?:,\d+)+', text) if ',' in m[0] and not re.fullmatch(r'\d{1,3}(?:,\d{3})+', m[0])]
    unmatched.extend('malformed number: ' + x for x in malformed)
    unmatched.extend(_bindings(text, facts))
    lab = _labelled(text, facts, facts_json if isinstance(facts_json, str) else '') + _contradictions(text, facts)
    checked += len(lab)
    unmatched.extend(lab)
    for m in _TIME_RE.finditer(text):
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh < 24 and mm < 60:
            checked += 1
            t = '%02d:%02d' % (hh, mm)
            if t not in times:
                unmatched.append(t)
    stripped = _TIME_RE.sub(' ', _ID_RE.sub(' ', text))
    for m in _NUM_RE.finditer(stripped):
        x = _num(m)
        frac = m.group(3)
        d = len(frac) - 1 if frac else 0
        after = stripped[m.end():m.end() + 12]
        checked += 1
        cands = [x]
        if _PCT.match(after):
            cands.append(x / 100.0)
        if _HRS.match(after):
            cands.append(x * 60.0)
        if _MIN.match(after):
            cands.append(x / 60.0)
        if not any(_match(c, d if c == x else 3, values) for c in cands):
            unmatched.append(m.group(0).lstrip('+'))
    return {'ok': not unmatched, 'checked': checked, 'unmatched': unmatched[:8]}

# Only bind explicit measurements; prose predictions, quoted decisions and proposed
# changes are not current observations. Keep entity identity across adjacent bullets.
_MEASURE = re.compile(r'(?<![\w.])([+-]?\d[\d,]*(?:\.\d+)?)\s*(kWh|kW|°C|%|명)')
_METRICS = [(r'냉방|공조|HVAC|cooling', 'hvacKW'), (r'조명|lighting', 'lightKW'),
            (r'콘센트|plug', 'plugKW'), (r'\bIT\b', 'itKW'),
            (r'태양광|solar|\bPV\b', 'pvKW')]


def _bindings(text, facts):
    if not isinstance(facts, dict):
        return []
    records = {}
    def visit(v):
        if isinstance(v, dict):
            if isinstance(v.get('id'), str) and re.fullmatch(r'B\d(?:-F\d+(?:-R\d+)?)?', v['id']):
                records.setdefault(v['id'], {}).update(v)
            for child in v.values():
                visit(child)
        elif isinstance(v, list):
            for child in v:
                visit(child)
    visit(facts)
    # Unknown floor/room IDs must not accidentally match their building prefix.
    aliases = {k: k for k in records}
    aliases.update({v['name']: k for k, v in records.items() if v.get('name')})
    entity_rx = re.compile('|'.join(re.escape(k) + (r'(?!-F|-R|[0-9])' if k.startswith('B') else '') for k in sorted(aliases, key=len, reverse=True))) if aliases else None
    cp, today = facts.get('campus') or {}, facts.get('today') or {}
    dm = (facts.get('dayMetrics') or {}).get('agent') or {}
    quoted = json.dumps(facts.get('recentDecisions', []), ensure_ascii=False)
    bad, entity = [], None
    for line in text.splitlines():
        if re.search(r'에이전트:|agent:|예측|향후|예상|forecast|최근 조치|운영자 설정|설정.*(?:바꾸|제안)|propos', line, re.I):
            continue
        if line.strip('- ').strip() in quoted:
            continue
        previous = 0
        for m in _MEASURE.finditer(line):
            prefix = line[previous:m.start()]
            previous = m.end()
            hits = list(entity_rx.finditer(prefix)) if entity_rx else []
            if hits:
                entity = aliases[hits[-1].group()]
                # Preserve metric qualifiers before the entity (e.g. cooling at B4).
                pass
            if re.search(r'B\d-F\d', prefix) and not hits:
                continue
            record = records.get(entity, {})
            value, unit = float(m[1].replace(',', '')), m[2]
            decimals = len(m[1].split('.')[1]) if '.' in m[1] else 0
            expected = None
            label = prefix
            if re.search(r'합계|합산|차이|여유|headroom|sum|difference|total of|절감|감축', prefix, re.I):
                continue
            if unit == 'kW':
                metric_hits = [(hit.start(), key) for rx, key in _METRICS for hit in re.finditer(rx, prefix, re.I)]
                metric = max(metric_hits)[1] if metric_hits else None
                if re.search(r'냉방 전력.*태양광', prefix):
                    metric = 'hvacKW'
                # In English enumerations the label follows its measurement.
                suffix = line[m.end():].split(',')[0].split(';')[0]
                post = re.match(r'\s+(?:is\s+)?(HVAC|lighting|plug loads|IT)\b', suffix, re.I)
                if post:
                    metric = {'hvac': 'hvacKW', 'lighting': 'lightKW', 'plug loads': 'plugKW', 'it': 'itKW'}[post[1].lower()]
                if metric:
                    expected = record.get(metric) if entity and not re.search(r'일사 덕분', prefix) else cp.get({'pvKW': 'pvNowKW'}.get(metric, ''))
                elif hits:
                    expected = record.get('loadKW', record.get('kW'))
                elif re.search(r'냉동기|chiller', prefix, re.I):
                    expected = cp.get('chillerNowKW')
                elif re.search(r'수전|grid import', prefix, re.I):
                    expected = today.get('highestGridImportTodayKW') if re.search(r'최대|highest|peak', prefix, re.I) else cp.get('gridImportNowKW')
                    if re.search(r'BMS|baseline', prefix, re.I):
                        expected = ((facts.get('dayMetrics') or {}).get('baseline') or {}).get('peakKW')
                elif re.search(r'캠퍼스.*부하|campus load', prefix, re.I):
                    expected = cp.get('loadNowKW')
                elif re.search(r'ESS|배터리|battery', prefix, re.I):
                    expected = cp.get('essNowKW')
                elif re.search(r'전력|power', prefix, re.I) and entity:
                    expected = record.get('loadKW', record.get('kW'))
                if re.search(r'오늘.*최대.*발전|maximum.*generation|peak.*solar', prefix, re.I):
                    bad.append('unsupported daily PV maximum: ' + m[0])
                if re.search(r'비용.*(?:비싼|최대)|cost.*(?:highest|expensive)', line, re.I):
                    bad.append('cost labelled as power: ' + m[0])
            elif unit == 'kWh':
                if re.search(r'태양광|solar|PV', prefix, re.I):
                    expected = dm.get('pvGenKWh')
                elif re.search(r'냉동기|chiller', prefix, re.I):
                    bad.append('unsupported chiller energy: ' + m[0])
            elif unit == '°C' and entity:
                expected = record.get('setpointC' if re.search(r'설정|setpoint', prefix, re.I) else 'tempC')
            elif unit == '%' and entity and re.search(r'재실|occupancy', prefix, re.I):
                expected = record.get('occupancyPct')
            elif unit == '명' and entity:
                expected = record.get('people')
            if isinstance(expected, (int, float)) and not _match(abs(value), decimals, [abs(expected)]):
                bad.append('%s %s: expected %g' % (entity or label.strip(), m[0], expected))
    return bad
