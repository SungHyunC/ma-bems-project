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


def _labelled(text, facts):
    bad = []
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
            if not _match(x, d, [abs(float(v))]):
                bad.append('%s %s%s (%s %s)' % (m.group(0).strip(), n.group(1) + (n.group(2) or ''), unit, 'data', ('%g' % v) + unit))
    return bad


# State contradiction: right numbers, wrong meaning. The 8B model twice called the headroom an excess ("한도를
# 154.2kW 초과" while 154.2 kW was the room left below the limit). A sentence that puts the limit and "over" together,
# with no negation, forecast or baseline word, contradicts a grid import that is below the limit.
_LIMIT_W = re.compile(r'상한|한도|peak\s*limit', re.I)
_OVER_W = re.compile(r'초과|넘(?:어|었|는|음|긴)|exceed|\bover\b', re.I)
_CALM_W = re.compile(r'예측|기준|BMS|않|없|방지|이내|미만|아래|위험|가능|우려|대비|막|피하|0\s*분|forecast|baseline|avoid|prevent|risk|below|within|not\b|never|no\b', re.I)


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
    lab = _labelled(text, facts) + _contradictions(text, facts)
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
