"""A/B/C evaluation with vLLM (Modal), scored like eval_ab.py, plus the v2 behaviours.

Generation follows the gateway's Ollama call as closely as vLLM allows: the same system prompt and <campus_state> turn,
think off, temperature 0.3, the per-task token cap, and for proposals the per-request enum schema with its properties
in alphabetical order (the order Ollama's grammar emits). Weights are bf16 here, not the Q8_0 GGUF Ollama serves, so
compare models with each other within this run; the desktop Ollama run (eval_ab.py) stays the deployment check.

Extra scores for eval_gen.jsonl: one_sentence_ok on '+one' questions (one line, no bullets), over_refusal on questions
the data can answer, refusal on questions it cannot. eval_nothing.jsonl: proposals where nothing needs changing.
"""
import json
import re
import sys
import time
from pathlib import Path

for p in ('/server', str(Path(__file__).resolve().parents[2] / 'server')):
    sys.path.insert(0, p)
import numcheck  # noqa: E402
from mabems_server import TASKS, proposal_schema  # noqa: E402

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


def score_text(r, ans, ctx, question, system):
    ref = r['messages'][2]['content']
    kind = r['kind']
    one = kind.endswith('+one')
    base_kind = kind[:-4] if one else kind
    lines = [l for l in ans.splitlines() if l.strip()]
    bl = [l for l in lines if l.lstrip().startswith('- ')]
    if r['task'] == 'brief':
        fmt_ok = 3 <= len(bl) <= 5
    else:
        fmt_ok = bool(lines) and not lines[0].lstrip().startswith('-') and 2 <= len(bl) <= 4
    fmt_ok = fmt_ok and not any(l.lstrip().startswith('#') or '|' in l for l in lines)
    want_ko = bool(HANGUL.search(question))
    chk = numcheck.check(ans, ctx, question, rules=system)
    key = nums(ref.splitlines()[0]) if base_kind != 'unknown' else set()
    got = nums(ans)
    key_recall = (len([k for k in key if any(abs(k - g) <= max(0.051, 0.01 * abs(k)) for g in got)]) / len(key)) if key else None
    refused = '데이터에 없' in ans or 'not in the data' in ans.lower()
    return {'num_ok': chk['ok'], 'unmatched': chk['unmatched'], 'fmt_ok': None if one else fmt_ok,
            'lang_ok': bool(HANGUL.search(ans)) == want_ko, 'key_recall': key_recall,
            'refusal': refused if base_kind == 'unknown' else None,
            'over_refusal': refused if (base_kind != 'unknown' and r['task'] == 'chat') else None,
            'one_sentence_ok': (len(lines) == 1 and not bl) if one else None}


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
        try:
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
        except ValueError:
            pass
    mine = {(a.get('type'), a.get('target')) for a in acts}
    gold = {(a['type'], a['target']) for a in ref['actions']}
    hit = len(mine & gold)
    return {'json_ok': True, 'n': len(acts), 'noop': noop, 'adds_load': adds, 'hit': hit, 'n_gold': len(gold),
            'empty_ok': (not acts) if not gold else None, 'pressure': bool(pressure)}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(100.0 * sum(xs) / len(xs), 1) if xs else None


def summarize(results):
    T = [x for x in results if x['task'] != 'propose']
    P = [x for x in results if x['task'] == 'propose']
    s = {'n': len(results)}
    if T:
        s['text'] = {'n': len(T), 'number_check_pct': mean([x['num_ok'] for x in T]), 'format_pct': mean([x['fmt_ok'] for x in T]),
                     'language_pct': mean([x['lang_ok'] for x in T]), 'key_number_recall_pct': mean([x['key_recall'] for x in T]),
                     'refusal_pct': mean([x['refusal'] for x in T]), 'over_refusal_pct': mean([x['over_refusal'] for x in T]),
                     'one_sentence_pct': mean([x['one_sentence_ok'] for x in T])}
    if P:
        s['propose'] = {'n': len(P), 'json_ok_pct': mean([x['json_ok'] for x in P]),
                        'noop_actions': sum(x.get('noop', 0) for x in P), 'actions': sum(x.get('n', 0) for x in P),
                        'adds_load_actions': sum(x.get('adds_load', 0) for x in P),
                        'precision_pct': round(100.0 * sum(x.get('hit', 0) for x in P) / max(1, sum(x.get('n', 0) for x in P)), 1),
                        'recall_pct': round(100.0 * sum(x.get('hit', 0) for x in P) / max(1, sum(x.get('n_gold', 0) for x in P)), 1),
                        'nothing_to_do_ok_pct': mean([x.get('empty_ok') for x in P])}
    return s


def sampling(task, ctx):
    from vllm import SamplingParams
    kw = {'temperature': 0.3, 'max_tokens': TASKS[task]['max_local'], 'seed': 0}
    if task != 'propose':
        return SamplingParams(**kw)
    schema = alpha(proposal_schema(ctx))
    try:
        from vllm.sampling_params import StructuredOutputsParams
        return SamplingParams(structured_outputs=StructuredOutputsParams(json=schema), **kw)
    except ImportError:
        from vllm.sampling_params import GuidedDecodingParams
        return SamplingParams(guided_decoding=GuidedDecodingParams(json=schema), **kw)


def run(base, adapters, sets, out_dir):
    from vllm import LLM
    from vllm.lora.request import LoRARequest
    llm = LLM(model=base, enable_lora=True, max_lora_rank=16, max_loras=2, max_model_len=8192, gpu_memory_utilization=0.9, seed=0)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    data = {}
    for s in sets:
        rows = [json.loads(l) for l in open(s, encoding='utf-8')]
        parsed = []
        for r in rows:
            user = r['messages'][1]['content']
            ctx = user.split('<campus_state>\n', 1)[1].split('\n</campus_state>', 1)[0]
            parsed.append((r, ctx, user.rsplit('\n\n', 1)[-1]))
        data[Path(s).stem] = parsed
    for i, (name, path) in enumerate(adapters.items()):
        lora = LoRARequest(name, i + 1, path) if path else None
        for set_name, parsed in data.items():
            t0 = time.time()
            outs = llm.chat([r['messages'][:2] for r, _, _ in parsed], [sampling(r['task'], ctx) for r, ctx, _ in parsed],
                            lora_request=lora, chat_template_kwargs={'enable_thinking': False}, use_tqdm=False)
            results = []
            for (r, ctx, q), o in zip(parsed, outs):
                ans = re.sub(r'<think>.*?</think>', '', o.outputs[0].text, flags=re.S).strip()
                sc = score_propose(r, ans, ctx) if r['task'] == 'propose' else score_text(r, ans, ctx, q, r['messages'][0]['content'])
                results.append({'task': r['task'], 'kind': r['kind'], 'question': q, 'answer': ans, **sc})
            sm = summarize(results)
            sm['secs'] = round(time.time() - t0, 1)
            summary.setdefault(name, {})[set_name] = sm
            (out / f'{name}_{set_name}.json').write_text(json.dumps({'summary': sm, 'results': results}, ensure_ascii=False, indent=1), encoding='utf-8')
            print(name, set_name, json.dumps(sm, ensure_ascii=False), flush=True)
    return summary
