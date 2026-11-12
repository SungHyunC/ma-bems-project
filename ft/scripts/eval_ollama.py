"""Desktop deployment check: the eval_vllm.py scoring on answers from Ollama (the Q8_0 GGUF the gateway serves).

    ..\\.venv\\Scripts\\python scripts\\eval_ollama.py <ollama model> <out dir> <set.jsonl> [<set.jsonl> ...]

Calls Ollama exactly like the gateway (system prompt and <campus_state> turn, think off, temperature 0.3, the per-task
token cap, num_ctx 8192, and for proposals the per-request enum schema, whose keys Ollama emits in alphabetical order).
Scores with eval_vllm.score_text / score_propose / summarize, so the numbers compare with the vLLM tables in ft/README.
Proposals are also scored after the gateway's drop_noops filter ("propose_gateway"), which is what operators see.
--current-prompt (anywhere in the arguments) swaps each item's system message for the gateway's current one
(SYSTEM_BASE + task note), to check that a prompt edit does not undo what the fine-tune learned.
"""
import copy
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_vllm as ev  # noqa: E402  (scoring only; vLLM is imported lazily there)
from mabems_server import SYSTEM_BASE, TASKS, drop_noops, proposal_schema  # noqa: E402

CURRENT = '--current-prompt' in sys.argv
model, out_dir, sets = sys.argv[1], Path(sys.argv[2]), [a for a in sys.argv[3:] if a != '--current-prompt']
out_dir.mkdir(parents=True, exist_ok=True)


def ollama(messages, task, ctx, question=''):
    p = {'model': model, 'stream': False, 'think': False, 'keep_alive': '30m', 'messages': messages,
         'options': {'temperature': 0.3, 'num_predict': TASKS[task]['max_local'], 'num_ctx': 10240}}
    if task == 'propose':
        p['format'] = proposal_schema(ctx, question)      # narrowed by a typed request, as the gateway does
    req = urllib.request.Request('http://127.0.0.1:11434/api/chat', data=json.dumps(p).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=300).read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print('HTTP %d on %s: %s' % (e.code, task, e.read().decode('utf-8', 'replace')[:160]), flush=True)
        return ''
    return re.sub(r'<think>.*?</think>', '', (d.get('message') or {}).get('content') or '', flags=re.S).strip()


for s in sets:
    rows = [json.loads(line) for line in open(s, encoding='utf-8')]
    results, gated, t0 = [], [], time.time()
    for r in rows:
        ctx, q = ev.split_row(r)                       # the last user turn (v2.2 rows may hold earlier turns)
        msgs = r['messages'][:-1]
        if CURRENT:
            msgs = [{'role': 'system', 'content': SYSTEM_BASE + TASKS[r['task']]['note']}] + msgs[1:]
        ans = ollama(msgs, r['task'], ctx, q)
        if r['task'] == 'propose':
            sc = ev.score_propose(r, ans, ctx)
            g = ans
            try:
                data = json.loads(ans)
                if isinstance(data.get('actions'), list):
                    data = copy.deepcopy(data)
                    drop_noops(data, ctx, q)
                    g = json.dumps(data, ensure_ascii=False)
            except ValueError:
                pass
            gated.append({'task': 'propose', 'kind': r['kind'], **ev.score_propose(r, g, ctx)})
        else:
            sc = ev.score_text(r, ans, ctx, q, r['messages'][0]['content'])
        results.append({'task': r['task'], 'kind': r['kind'], 'question': q, 'answer': ans, **sc})
    sm = ev.summarize(results)
    if gated:
        sm['propose_gateway'] = ev.summarize(gated)['propose']
    sm['minutes'] = round((time.time() - t0) / 60, 1)
    name = Path(s).stem + ('_current' if CURRENT else '')
    (out_dir / f'{model}_{name}.json').write_text(json.dumps({'summary': sm, 'results': results}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(model, name, json.dumps(sm, ensure_ascii=False), flush=True)
