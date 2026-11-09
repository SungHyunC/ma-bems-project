"""A/B evaluation of local models on the held-out MA-BEMS assistant set (eval.jsonl, unseen scenario conditions).

    ..\\.venv\\Scripts\\python scripts\\eval_ab.py data\\eval.jsonl out\\eval_<model>.json <ollama model>

Calls Ollama exactly like the gateway does (same system prompt, <campus_state> user turn, think=false, temperature 0.3,
the per-task token cap, and for proposals the per-request enum schema), then scores:
  text tasks  number check (server/numcheck.py with the rules), format (conclusion + 2-4 '- ' lines; brief 3-5 lines;
              no headings or tables), answers in the question's language, refusals on questions the data cannot answer,
              key numbers of the reference answer's first line present in the model's answer
  proposals   valid JSON, no-op actions (lights off in a dark room, a setpoint equal to the current one), actions that add
              load under pressure, agreement with the reference policy (precision / recall on type+target), correct
              "nothing to do"
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
import numcheck  # noqa: E402
from mabems_server import TASKS, proposal_schema  # noqa: E402

src, dst, model = sys.argv[1], sys.argv[2], sys.argv[3]
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 0
rows = [json.loads(line) for line in open(src, encoding='utf-8')]
if limit:
    rows = rows[:limit]
NUM = re.compile(r'(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?')
HANGUL = re.compile(r'[가-힣]')


def ollama(messages, task, ctx):
    payload = {'model': model, 'stream': False, 'think': False, 'keep_alive': '30m', 'messages': messages,
               'options': {'temperature': 0.3, 'num_predict': TASKS[task]['max_local'], 'num_ctx': 8192}}   # as the gateway
    if task == 'propose':
        payload['format'] = proposal_schema(ctx)
    req = urllib.request.Request('http://127.0.0.1:11434/api/chat', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
    t0 = time.time()
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=300).read().decode('utf-8'))
    except urllib.error.HTTPError as e:                  # keep going; the failure is scored and its reason kept
        err = e.read().decode('utf-8', 'replace')[:200]
        print('HTTP %d on %s: %s' % (e.code, task, err), flush=True)
        return '', time.time() - t0, 0
    text = re.sub(r'<think>.*?</think>', '', (d.get('message') or {}).get('content') or '', flags=re.S).strip()
    return text, time.time() - t0, d.get('eval_count', 0)


def nums(s):
    return {float(m.group(1).replace(',', '') + (m.group(2) or '')) for m in NUM.finditer(s)}


def score_text(r, ans, ctx, question, system):
    ref = r['messages'][2]['content']
    lines = [l for l in ans.splitlines() if l.strip()]
    bl = [l for l in lines if l.lstrip().startswith('- ')]
    if r['task'] == 'brief':
        fmt_ok = 3 <= len(bl) <= 5
    else:
        fmt_ok = bool(lines) and not lines[0].lstrip().startswith('-') and 2 <= len(bl) <= 4
    fmt_ok = fmt_ok and not any(l.lstrip().startswith('#') or '|' in l for l in lines)
    want_ko = bool(HANGUL.search(question))
    lang_ok = bool(HANGUL.search(ans)) == want_ko
    chk = numcheck.check(ans, ctx, question, rules=system)
    key = nums(ref.splitlines()[0]) if r['kind'] != 'unknown' else set()
    got = nums(ans)
    key_recall = (len([k for k in key if any(abs(k - g) <= max(0.051, 0.01 * abs(k)) for g in got)]) / len(key)) if key else None
    refusal = ('데이터에 없' in ans or 'not in the data' in ans.lower()) if r['kind'] == 'unknown' else None
    return {'num_ok': chk['ok'], 'unmatched': chk['unmatched'], 'fmt_ok': fmt_ok, 'lang_ok': lang_ok, 'key_recall': key_recall, 'refusal': refusal}


def score_propose(r, ans, ctx):
    ref = json.loads(r['messages'][2]['content'])
    c = json.loads(ctx)
    try:
        data = json.loads(ans)
        acts = [a for a in data.get('actions', []) if isinstance(a, dict)]
    except ValueError:
        return {'json_ok': False}
    rooms = {x['id']: x for x in c.get('candidateRooms', [])}
    zones = {x['id']: x for x in c.get('candidateZones', [])}
    cp, f, dr = c['campus'], c.get('forecast') or {}, c.get('demandResponse') or {}
    tier = c['tariff']['tier']['tier'] if isinstance(c['tariff'].get('tier'), dict) else c['tariff'].get('tier')
    pressure = dr.get('active') or cp['headroomNowPct'] < 12 or (f.get('next4hMaxPctOfLimit') or 0) >= 95 or (tier == 'peak' and cp['headroomNowPct'] < 20)
    noop = adds = 0
    for a in acts:
        t, tg, v = a.get('type'), a.get('target'), str(a.get('value'))
        if t == 'roomLights' and tg in rooms and v == 'off' and ((rooms[tg].get('lightLevelPct') or 0) == 0 or rooms[tg].get('lights') == 'off'):
            noop += 1
        elif t == 'roomSetpoint' and tg in rooms and v not in ('null', 'auto') and abs(float(v) - rooms[tg]['setpointC']) < 0.05:
            noop += 1
        elif t == 'setpoint' and tg in zones and abs(float(v) - zones[tg]['setpointC']) < 0.05:
            noop += 1
        if pressure and t in ('setpoint', 'roomSetpoint') and v not in ('null', 'auto'):
            cur = (zones.get(tg) or rooms.get(tg) or {}).get('setpointC')
            if cur is not None and float(v) < cur - 0.05:
                adds += 1
    mine = {(a.get('type'), a.get('target')) for a in acts}
    gold = {(a['type'], a['target']) for a in ref['actions']}
    hit = len(mine & gold)
    return {'json_ok': True, 'n': len(acts), 'noop': noop, 'adds_load': adds, 'hit': hit, 'n_gold': len(gold),
            'empty_ok': (not gold and not acts) if not gold else None, 'pressure': bool(pressure)}


results = []
t_all = time.time()
for i, r in enumerate(rows):
    system, user = r['messages'][0]['content'], r['messages'][1]['content']
    ctx = user.split('<campus_state>\n', 1)[1].split('\n</campus_state>', 1)[0]
    question = user.rsplit('\n\n', 1)[-1]
    ans, secs, out_tok = ollama(r['messages'][:2], r['task'], ctx)
    s = score_propose(r, ans, ctx) if r['task'] == 'propose' else score_text(r, ans, ctx, question, system)
    results.append({'i': i, 'task': r['task'], 'kind': r['kind'], 'secs': round(secs, 2), 'out_tokens': out_tok, 'answer': ans, **s})
    if (i + 1) % 20 == 0:
        print('%d/%d  %.0fs' % (i + 1, len(rows), time.time() - t_all), flush=True)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(100.0 * sum(xs) / len(xs), 1) if xs else None


T = [x for x in results if x['task'] != 'propose']
P = [x for x in results if x['task'] == 'propose']
summary = {
    'model': model, 'n': len(results), 'minutes': round((time.time() - t_all) / 60, 1),
    'text': {'n': len(T), 'number_check_pct': mean([x['num_ok'] for x in T]), 'format_pct': mean([x['fmt_ok'] for x in T]),
             'language_pct': mean([x['lang_ok'] for x in T]), 'key_number_recall_pct': mean([x['key_recall'] for x in T]),
             'refusal_pct': mean([x['refusal'] for x in T]), 'secs_mean': round(sum(x['secs'] for x in T) / max(1, len(T)), 2)},
    'propose': {'n': len(P), 'json_ok_pct': mean([x['json_ok'] for x in P]),
                'noop_actions': sum(x.get('noop', 0) for x in P), 'actions': sum(x.get('n', 0) for x in P),
                'adds_load_actions': sum(x.get('adds_load', 0) for x in P),
                'precision_pct': round(100.0 * sum(x.get('hit', 0) for x in P) / max(1, sum(x.get('n', 0) for x in P)), 1),
                'recall_pct': round(100.0 * sum(x.get('hit', 0) for x in P) / max(1, sum(x.get('n_gold', 0) for x in P)), 1),
                'nothing_to_do_ok_pct': mean([x.get('empty_ok') for x in P]),
                'secs_mean': round(sum(x['secs'] for x in P) / max(1, len(P)), 2)},
}
Path(dst).parent.mkdir(parents=True, exist_ok=True)
Path(dst).write_text(json.dumps({'summary': summary, 'results': results}, ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=1))
