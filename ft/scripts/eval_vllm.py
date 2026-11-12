"""A/B/C evaluation with vLLM (Modal), scored like eval_ab.py, plus the v2 and v2.2 behaviours.

Generation follows the gateway's Ollama call as closely as vLLM allows: the same system prompt and <campus_state> turn,
think off, temperature 0.3, the per-task token cap, and for proposals the per-request enum schema with its properties
in alphabetical order (the order Ollama's grammar emits), narrowed by the typed question as the gateway does. Weights are
bf16 here, not the Q8_0 GGUF Ollama serves, so compare models with each other within this run; the desktop Ollama run
(eval_ollama.py) stays the deployment check.

Scores (text): number check (server/numcheck.py, labels bound to their fields), format, language, key-number recall,
stray numbers (answer numbers that are not in the rule answer), refusal / over-refusal, one-sentence instructions,
off-topic replies without numbers, concept answers that use the glossary definition (head similarity).
Scores (proposals): JSON, no-op actions, load-adding actions, precision / recall by (type, target) and by (type, target,
value), "nothing to change" on empty-gold proposals; each both for the model alone and after the gateway's filter
(drop_noops + align_summary), which is what operators see. Rows may hold earlier turns (v2.2 multi-turn data).
The realq set (ft/data/realq.json) is asked offline the way the page and gateway route it (realq_rows).
"""
import copy
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

for p in ('/server', str(Path(__file__).resolve().parents[2] / 'server')):
    sys.path.insert(0, p)
import numcheck  # noqa: E402
from mabems_server import TASKS, SYSTEM_BASE, proposal_schema, drop_noops  # noqa: E402

NUM = re.compile(r'(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?')
HANGUL = re.compile(r'[가-힣]')


def alpha(schema):
    if isinstance(schema, dict):
        out = {k: alpha(v) for k, v in schema.items()}
        if isinstance(out.get('properties'), dict):
            out['properties'] = {k: out['properties'][k] for k in sorted(out['properties'])}
        return out
    if isinstance(schema, list):
        return [alpha(x) for x in schema]
    return schema


def nums(s):
    return {float(m.group(1).replace(',', '') + (m.group(2) or '')) for m in NUM.finditer(s)}


def near(k, got):
    return any(abs(k - g) <= max(0.051, 0.01 * abs(k)) for g in got)


def base_kind(kind):
    k = kind.split(':', 1)[1] if kind.startswith(('followup:', 'request:')) else kind
    return k.split('+', 1)[0]


def group(kind):
    k = base_kind(kind)
    if kind.startswith('followup:'):
        return 'followup'
    if k.startswith('c_'):
        return 'concept'
    if k.endswith('_en'):
        return 'english'
    if k.startswith(('q_bld_', 'q_floor_')):
        return 'building/floor'
    if k in ('unknown', 'q_offtopic', 'q_capabilities'):
        return 'refuse/offtopic'
    if k in ('q_peak', 'q_cost', 'q_top', 'q_ess', 'q_pv', 'q_comfort', 'q_agents', 'q_weather', 'q_dr', 'q_faults', 'q_forecast',
             'q_tariff', 'q_temp', 'q_maxtoday', 'q_co2', 'q_ev', 'q_pvself'):
        return 'v2 kinds'
    if k.startswith('q_'):
        return 'v2.2 kinds'
    return k


def grams(s):
    s = re.sub(r'\s+', '', s)
    return {s[i:i + 3] for i in range(max(0, len(s) - 2))}


def head_sim(ans, ref):
    a, b = grams(ans.split('\n', 1)[0]), grams(ref.split('\n', 1)[0])
    return len(a & b) / len(b) if b else None


def score_text(r, ans, ctx, question, system):
    ref = r['messages'][-1]['content']
    kind = r['kind']
    one = '+one' in kind
    bk = base_kind(kind)
    lines = [l for l in ans.splitlines() if l.strip()]
    bl = [l for l in lines if l.lstrip().startswith('- ')]
    if r['task'] == 'brief':
        fmt_ok = 3 <= len(bl) <= 5
    else:
        fmt_ok = bool(lines) and not lines[0].lstrip().startswith('-') and 2 <= len(bl) <= 4
    fmt_ok = fmt_ok and not any(l.lstrip().startswith('#') or '|' in l for l in lines)
    want_ko = bool(HANGUL.search(question))
    chk = numcheck.check(ans, ctx, question, rules=system)
    refusing = bk in ('unknown', 'q_unknown_en')
    key = nums(ref.splitlines()[0]) if not refusing else set()
    got = nums(ans)
    key_recall = (len([k for k in key if near(k, got)]) / len(key)) if key else None
    refnums = nums(ref) | nums(question)
    extra = [g for g in got if not near(g, refnums) and g > 10]       # small counts and list numbering aside
    refused = '데이터에 없' in ans or 'not in the data' in ans.lower()
    concept = bk.startswith('c_')
    return {'num_ok': chk['ok'], 'unmatched': chk['unmatched'], 'fmt_ok': None if one else fmt_ok,
            'lang_ok': bool(HANGUL.search(ans)) == want_ko, 'key_recall': key_recall,
            'stray_numbers': len(extra) if r['task'] == 'chat' else None,
            'refusal': refused if refusing else None,
            'over_refusal': refused if (not refusing and r['task'] == 'chat' and bk not in ('q_offtopic', 'q_offtopic_en')
                                        and not ('데이터에 없' in ref or 'not in the data' in ref.lower())) else None,
            'one_sentence_ok': (len(lines) == 1 and not bl) if one else None,
            'offtopic_ok': (not re.search(r'\d', ans)) if bk in ('q_offtopic', 'q_offtopic_en') else None,
            'concept_ok': ((head_sim(ans, ref) or 0) >= 0.5) if concept else None}


def room_state(c):
    return {x['id']: x for x in c.get('candidateRooms', [])}, {x['id']: x for x in c.get('candidateZones', [])}


def is_pressure(c):
    cp, f, dr = c['campus'], c.get('forecast') or {}, c.get('demandResponse') or {}
    tier = c['tariff']['tier']['tier'] if isinstance(c['tariff'].get('tier'), dict) else c['tariff'].get('tier')
    return bool(dr.get('active') or cp['headroomNowPct'] < 12 or (f.get('next4hMaxPctOfLimit') or 0) >= 95 or (tier == 'peak' and cp['headroomNowPct'] < 20))


def score_propose(r, ans, ctx, question=''):
    ref = json.loads(r['messages'][-1]['content'])
    c = json.loads(ctx)
    try:
        data = json.loads(ans)
        acts = [a for a in data.get('actions', []) if isinstance(a, dict)]
    except (ValueError, AttributeError):
        return {'json_ok': False}
    rooms, zones = room_state(c)
    pressure = is_pressure(c)
    noop = noop_gw = adds = 0                         # noop: v1/v2 definition (same value, light already off); noop_gw adds
    for a in acts:                                    # raising a room already in setback / off, as the gateway's drop_noops
        t, tg, v = a.get('type'), a.get('target'), str(a.get('value'))
        try:
            if t == 'roomLights' and tg in rooms and v == 'off' and ((rooms[tg].get('lightLevelPct') or 0) == 0 or rooms[tg].get('lights') == 'off'):
                noop += 1
                noop_gw += 1
            elif t == 'roomSetpoint' and tg in rooms and v not in ('null', 'auto'):
                same = abs(float(v) - rooms[tg]['setpointC']) < 0.05
                noop += same
                noop_gw += same or (rooms[tg].get('hvacMode') in ('setback', 'off') and float(v) > rooms[tg]['setpointC'])
            elif t == 'setpoint' and tg in zones and abs(float(v) - zones[tg]['setpointC']) < 0.05:
                noop += 1
                noop_gw += 1
            if pressure and t in ('setpoint', 'roomSetpoint') and v not in ('null', 'auto'):
                cur = (zones.get(tg) or rooms.get(tg) or {}).get('setpointC')
                if cur is not None and float(v) < cur - 0.05:
                    adds += 1
        except (TypeError, ValueError):
            pass
    mine = {(a.get('type'), a.get('target')) for a in acts}
    mine_v = {(a.get('type'), a.get('target'), str(a.get('value'))) for a in acts}
    gold = {(a['type'], a['target']) for a in ref['actions']}
    gold_v = {(a['type'], a['target'], str(a['value'])) for a in ref['actions']}
    return {'json_ok': True, 'n': len(acts), 'noop': noop, 'noop_gw': int(noop_gw), 'adds_load': adds, 'hit': len(mine & gold), 'hit_v': len(mine_v & gold_v),
            'n_gold': len(gold), 'empty_ok': (not acts) if not gold else None, 'acted_ok': bool(acts) if gold else None, 'pressure': bool(pressure)}


def gateway_view(ans, ctx, question):
    """The proposal as operators see it: the gateway's one-action-per-target, drop_noops and align_summary."""
    try:
        import assist
        data = json.loads(ans)
        if not isinstance(data.get('actions'), list):
            return ans
        data = copy.deepcopy(data)
        seen, acts = set(), []
        for a in data['actions']:
            if isinstance(a, dict) and (a.get('type'), a.get('target')) not in seen:
                seen.add((a.get('type'), a.get('target')))
                acts.append(a)
        data['actions'] = acts
        drop_noops(data, ctx, question)
        assist.align_summary(data, question)
        return json.dumps(data, ensure_ascii=False)
    except (ValueError, AttributeError, ImportError):
        return ans


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(100.0 * sum(xs) / len(xs), 1) if xs else None


def avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def text_summary(T):
    return {'n': len(T), 'number_check_pct': mean([x['num_ok'] for x in T]), 'format_pct': mean([x['fmt_ok'] for x in T]),
            'language_pct': mean([x['lang_ok'] for x in T]), 'key_number_recall_pct': mean([x['key_recall'] for x in T]),
            'stray_numbers_per_answer': avg([x.get('stray_numbers') for x in T]),
            'refusal_pct': mean([x['refusal'] for x in T]), 'over_refusal_pct': mean([x['over_refusal'] for x in T]),
            'one_sentence_pct': mean([x['one_sentence_ok'] for x in T]), 'offtopic_ok_pct': mean([x.get('offtopic_ok') for x in T]),
            'concept_ok_pct': mean([x.get('concept_ok') for x in T])}


def propose_summary(P):
    n = sum(x.get('n', 0) for x in P)
    g = sum(x.get('n_gold', 0) for x in P)
    hit, hit_v = sum(x.get('hit', 0) for x in P), sum(x.get('hit_v', 0) for x in P)
    return {'n': len(P), 'json_ok_pct': mean([x['json_ok'] for x in P]),
            'noop_actions': sum(x.get('noop', 0) for x in P), 'noop_actions_gateway_rule': sum(x.get('noop_gw', 0) for x in P), 'actions': n, 'adds_load_actions': sum(x.get('adds_load', 0) for x in P),
            'precision_pct': round(100.0 * hit / max(1, n), 1), 'recall_pct': round(100.0 * hit / max(1, g), 1),
            'precision_value_pct': round(100.0 * hit_v / max(1, n), 1), 'recall_value_pct': round(100.0 * hit_v / max(1, g), 1),
            'nothing_to_do_ok_pct': mean([x.get('empty_ok') for x in P]), 'acted_when_needed_pct': mean([x.get('acted_ok') for x in P])}


def summarize(results):
    T = [x for x in results if x['task'] != 'propose']
    P = [x for x in results if x['task'] == 'propose']
    s = {'n': len(results)}
    if T:
        s['text'] = text_summary(T)
        groups = defaultdict(list)
        for x in T:
            groups[group(x['kind'])].append(x)
        if len(groups) > 1:
            s['text_by_group'] = {k: text_summary(v) for k, v in sorted(groups.items())}
    if P:
        s['propose'] = propose_summary(P)
        if any('gw' in x for x in P):
            s['propose_gateway'] = propose_summary([x['gw'] for x in P if 'gw' in x])
        kinds = defaultdict(list)
        for x in P:
            kinds[base_kind(x['kind']) if not x['kind'].startswith('request:') else 'request'].append(x)
        if len(kinds) > 1:
            s['propose_by_kind'] = {k: propose_summary(v) for k, v in sorted(kinds.items())}
            s['propose_gateway_by_kind'] = {k: propose_summary([x['gw'] for x in v if 'gw' in x]) for k, v in sorted(kinds.items())}
    return s


def split_row(r):
    user = r['messages'][-2]['content']
    ctx = user.split('<campus_state>\n', 1)[1].split('\n</campus_state>', 1)[0]
    return ctx, user.split('\n</campus_state>\n\n', 1)[1] if '\n</campus_state>\n\n' in user else user.rsplit('\n\n', 1)[-1]


def sampling(task, ctx, question='', seed=0):
    from vllm import SamplingParams
    kw = {'temperature': 0.3, 'max_tokens': TASKS[task]['max_local'], 'seed': seed}
    if task != 'propose':
        return SamplingParams(**kw)
    schema = alpha(proposal_schema(ctx, question))
    try:
        from vllm.sampling_params import StructuredOutputsParams
        return SamplingParams(structured_outputs=StructuredOutputsParams(json=schema), **kw)
    except ImportError:
        from vllm.sampling_params import GuidedDecodingParams
        return SamplingParams(guided_decoding=GuidedDecodingParams(json=schema), **kw)


def score_row(r, ans, ctx, q):
    if r['task'] == 'propose':
        sc = score_propose(r, ans, ctx, q)
        sc['gw'] = {'task': 'propose', 'kind': r['kind'], **score_propose(r, gateway_view(ans, ctx, q), ctx, q)}
        return sc
    return score_text(r, ans, ctx, q, r['messages'][0]['content'])


# ---------------------------------------------------------------- realq: the 66 visitor questions, routed like the page
def realq_rows(bank_path, contexts):
    """Model-bound requests for ft/data/realq.json on fresh contexts ({name: {'chat': ctx, 'propose': ctx}} from collect.mjs
    realq mode): the page's routing (make_data_v22.page_route) and the gateway's pipeline (assist: contextualize, fixed
    answers, augment, model_view). Items the page or the gateway answers without the model are returned as 'fixed'."""
    import assist
    import make_data_v22 as M
    bank = json.loads(Path(bank_path).read_text(encoding='utf-8'))
    rows = []
    for it in bank['items']:
        cx = contexts[it['ctx']]
        hist = [h['content'] for h in it.get('history', [])]
        route = M.page_route(it['q'], history=bool(hist))
        rec = {'id': it['id'], 'cat': it['cat'], 'q': it['q'], 'item': it, 'route': route, 'history': hist}
        if route == 'brief':
            ctx = assist.model_view(cx['chat'])
            rec.update(task='brief', ctx=ctx, question=M.BRIEF_Q if HANGUL.search(it['q']) else M.BRIEF_Q_EN)
        elif route == 'propose':
            ctx = assist.model_view(cx['propose'])
            rec.update(task='propose', ctx=ctx, question=it['q'])
        elif route == 'chat':
            if assist.PROMPT_ASK.search(it['q']) or any(assist.PROMPT_ASK.search(h) for h in hist):
                rec.update(task='fixed', answer=assist.refusal(it['q']))
            else:
                rec.update(task='chat', raw=cx['chat'])            # question rewriting needs the earlier answers: done in run_realq
        else:
            rec.update(task='fixed', answer='(page: %s)' % route)
        rows.append(rec)
    return rows


def realq_checks(item, text, chk, task, data):
    fails = []
    hangul = len(HANGUL.findall(text))
    if item.get('lang') == 'en':
        if hangul > 0.1 * max(1, len(re.findall(r'[A-Za-z가-힣]', text))):
            fails.append('answered in Korean')
    elif not hangul:
        fails.append('not in Korean')
    for rx in item.get('need', []):
        if not re.search(rx, text):
            fails.append('missing /%s/' % rx)
    for key in ('needAny', 'needAny2'):
        if item.get(key) and not any(re.search(rx, text) for rx in item[key]):
            fails.append('none of %s' % item[key])
    done = r'(껐습니다|꺼 ?드렸|꺼졌습니다|적용했습니다|적용되었습니다|적용 완료|변경했습니다|변경되었습니다|조정했습니다|조정되었습니다|올렸습니다|낮췄습니다|내렸습니다|설정했습니다|실행했습니다|완료했습니다|완료되었습니다|I have (turned|switched|set|changed|applied))'
    for rx in item.get('forbid', []):
        m = re.search(done if rx == 'claimsDone' else rx, text)
        if m:
            fails.append('forbidden "%s"' % m.group(0))
    if item.get('maxLines') and len([l for l in text.splitlines() if l.strip()]) > item['maxLines']:
        fails.append('too many lines')
    if chk and not chk.get('ok'):
        fails.append('number check: ' + ', '.join(chk.get('unmatched') or []))
    if item.get('act') and task == 'propose' and not any(re.search(item['act'], '%s %s %s' % (a.get('type'), a.get('target'), a.get('value'))) for a in (data or {}).get('actions', [])):
        fails.append('no action like /%s/' % item['act'])
    return fails


def run_realq(llm, lora, rows, samples=3):
    """Ask the model-bound realq items `samples` times (seeds 0..n-1); earlier turns are asked first and their answers
    kept, as the page does. Returns per-item results and a summary (pass rates over model-answered items)."""
    import assist
    system = {t: SYSTEM_BASE + TASKS[t]['note'] for t in TASKS}
    out = []
    for seed in range(samples):
        msgs_hist = {}
        need = [r for r in rows if r['task'] == 'chat' and r['history']]
        if need:                                                     # first turns (chat, no history of their own)
            prompts = []
            for r in need:
                h = r['history'][0]
                ctx = assist.model_view(assist.augment(h, r['raw']))
                prompts.append([{'role': 'system', 'content': system['chat']}, {'role': 'user', 'content': '<campus_state>\n' + ctx + '\n</campus_state>\n\n' + h}])
            res = llm.chat(prompts, [sampling('chat', '', '', seed)] * len(prompts), lora_request=lora, chat_template_kwargs={'enable_thinking': False}, use_tqdm=False)
            for r, o in zip(need, res):
                a = re.sub(r'<think>.*?</think>', '', o.outputs[0].text, flags=re.S).strip()
                msgs_hist[r['id']] = [{'role': 'user', 'content': r['history'][0]}, {'role': 'assistant', 'content': assist.clean_answer(a, '')}]
        batch, meta = [], []
        for r in rows:
            if r['task'] == 'fixed':
                continue
            if r['task'] == 'chat':
                msgs = assist.contextualize(msgs_hist.get(r['id'], []) + [{'role': 'user', 'content': r['q']}])
                q = msgs[-1]['content']
                fixed = (assist.history_answer(q, r['raw']) or assist.forecast_answer(q, r['raw']) or assist.lookup_answer(q, r['raw'])
                         or assist.define_answer(q, r['raw']) or assist.faq_answer(q, r['raw']))
                if fixed:
                    fixed = assist.conclusion(fixed, r['q']) if assist.wants_one_line(r['q']) else fixed     # gateway: one-line requests keep the conclusion
                    if seed == 0:
                        fl = realq_checks(r['item'], fixed, None, 'chat', None)
                        out.append({'id': r['id'], 'cat': r['cat'], 'q': r['q'], 'by': 'gateway', 'answer': fixed, 'pass': not fl, 'fails': fl})
                    continue
                ctx = assist.model_view(assist.augment(q, r['raw']))
                msgs[-1] = {'role': 'user', 'content': '<campus_state>\n' + ctx + '\n</campus_state>\n\n' + q}
                batch.append([{'role': 'system', 'content': system['chat']}] + msgs)
                meta.append((r, ctx, q))
            else:
                batch.append([{'role': 'system', 'content': system[r['task']]}, {'role': 'user', 'content': '<campus_state>\n' + r['ctx'] + '\n</campus_state>\n\n' + r['question']}])
                meta.append((r, r['ctx'], r['question']))
        res = llm.chat(batch, [sampling(r['task'] if r['task'] != 'chat' else 'chat', ctx, q, seed) for (r, ctx, q) in meta],
                       lora_request=lora, chat_template_kwargs={'enable_thinking': False}, use_tqdm=False)
        for (r, ctx, q), o in zip(meta, res):
            a = re.sub(r'<think>.*?</think>', '', o.outputs[0].text, flags=re.S).strip()
            data, chk = None, None
            if r['task'] == 'propose':
                text = gateway_view(a, ctx, q)
                try:
                    data = json.loads(text)
                    text = '\n'.join([data.get('summary', '')] + ['%s %s %s: %s / %s' % (x.get('type'), x.get('target'), x.get('value'), x.get('expected_effect', ''), x.get('reason', ''))
                                                                  for x in data.get('actions', [])])
                except ValueError:
                    text = a
            else:
                text = assist.clean_answer(a, ctx)
                if r['task'] == 'chat' and assist.wants_one_line(r['q']):
                    text = assist.conclusion(text, q)                # before the number check, as gateway.chat does
                chk = numcheck.check(text, ctx, q, rules=system[r['task']])
            fails = realq_checks(r['item'], text, chk, r['task'], data)
            out.append({'id': r['id'], 'cat': r['cat'], 'q': r['q'], 'by': 'model', 'task': r['task'], 'seed': seed, 'answer': text,
                        'pass': not fails, 'fails': fails, 'num_ok': (chk or {}).get('ok') if chk else None})
    M = [x for x in out if x['by'] == 'model']
    by = defaultdict(list)
    for x in M:
        by[x['cat']].append(x['pass'])
    OLD = {'now_load', 'slang', 'cost_today', 'peak_when', 'chiller', 'en_load'}      # expected numbers from an old snapshot: no model can pass
    G = [x for x in out if x['by'] == 'gateway']
    summ = {'model_items': len({x['id'] for x in M}), 'samples': samples, 'pass_pct': mean([x['pass'] for x in M]),
            'pass_excl_old6_pct': mean([x['pass'] for x in M if x['id'] not in OLD]),
            'pass_with_gateway_pct': mean([x['pass'] for x in M + G]), 'pass_with_gateway_excl_old6_pct': mean([x['pass'] for x in M + G if x['id'] not in OLD]),
            'gateway_answers': [{'id': x['id'], 'pass': x['pass'], 'fails': x['fails']} for x in G],
            'number_check_pct': mean([x['num_ok'] for x in M if x['num_ok'] is not None]),
            'by_cat': {k: mean(v) for k, v in sorted(by.items())},
            'fixed_items': len([r for r in rows if r['task'] == 'fixed']) + len([x for x in out if x['by'] == 'gateway'])}
    return out, summ


def run(base, adapters, sets, out_dir, realq=None, realq_samples=3):
    from vllm import LLM
    from vllm.lora.request import LoRARequest
    llm = LLM(model=base, enable_lora=True, max_lora_rank=16, max_loras=2, max_model_len=10240, gpu_memory_utilization=0.9, seed=0)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    data = {}
    for s in sets:
        rows = [json.loads(l) for l in open(s, encoding='utf-8')]
        data[Path(s).stem] = [(r,) + split_row(r) for r in rows]
    for i, (name, path) in enumerate(adapters.items()):
        lora = LoRARequest(name, i + 1, path) if path else None
        for set_name, parsed in data.items():
            t0 = time.time()
            outs = llm.chat([r['messages'][:-1] for r, _, _ in parsed], [sampling(r['task'], ctx, q) for r, ctx, q in parsed],
                            lora_request=lora, chat_template_kwargs={'enable_thinking': False}, use_tqdm=False)
            results = []
            for (r, ctx, q), o in zip(parsed, outs):
                ans = re.sub(r'<think>.*?</think>', '', o.outputs[0].text, flags=re.S).strip()
                results.append({'task': r['task'], 'kind': r['kind'], 'question': q, 'answer': ans, **score_row(r, ans, ctx, q)})
            sm = summarize(results)
            sm['secs'] = round(time.time() - t0, 1)
            summary.setdefault(name, {})[set_name] = sm
            (out / f'{name}_{set_name}.json').write_text(json.dumps({'summary': sm, 'results': results}, ensure_ascii=False, indent=1), encoding='utf-8')
            print(name, set_name, json.dumps(sm, ensure_ascii=False), flush=True)
        if realq:
            t0 = time.time()
            res, sm = run_realq(llm, lora, realq_rows(*realq), realq_samples)
            sm['secs'] = round(time.time() - t0, 1)
            summary.setdefault(name, {})['realq'] = sm
            (out / f'{name}_realq.json').write_text(json.dumps({'summary': sm, 'results': res}, ensure_ascii=False, indent=1), encoding='utf-8')
            print(name, 'realq', json.dumps(sm, ensure_ascii=False), flush=True)
    return summary
