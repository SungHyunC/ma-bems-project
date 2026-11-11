"""Ask the running gateway the questions in ft/data/realq.json, the way the AI tab does, and check the answers.

  python ft/scripts/eval_realq.py <out.json> [--base http://127.0.0.1:5178] [--tier local] [--contexts ctx.json] [--only id,id]

Each item is sent to POST /api/llm/chat (task chat) with its campus context; items with a history first ask the earlier
user turn and pass the model's own answer back, as the page does. --contexts replaces the stored snapshots with fresh ones
({name: context string}, from ft/scripts/realq_contexts.mjs) so a change to the page's aiContext() can be tested.
Checks are deliberately simple (regexes, language, line count, the gateway's number check); every answer is also written
out for reading, because 'did it answer the question that was asked' still needs a person."""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAIMS_DONE = r'(껐습니다|꺼 ?드렸|꺼졌습니다|적용했습니다|적용되었습니다|적용 완료|변경했습니다|변경되었습니다|조정했습니다|조정되었습니다|' \
              r'올렸습니다|낮췄습니다|내렸습니다|설정했습니다|실행했습니다|완료했습니다|완료되었습니다|I have (turned|switched|set|changed|applied))'


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1]
    return default


def ask(base, tier, messages, context):
    body = json.dumps({'task': 'chat', 'tier': tier, 'messages': messages, 'context': context}).encode('utf-8')
    req = urllib.request.Request(base + '/api/llm/chat', data=body, headers={'Content-Type': 'application/json'})
    t0, done, err, ev = time.time(), None, None, 'message'
    with urllib.request.urlopen(req, timeout=180) as r:
        for raw in r:
            line = raw.decode('utf-8').rstrip('\r\n')
            if line.startswith('event: '):
                ev = line[7:]
            elif line.startswith('data: '):
                d = json.loads(line[6:])
                if ev == 'done':
                    done = d
                elif ev == 'error':
                    err = d.get('message')
    return done, err, time.time() - t0


def checks(item, text, chk):
    fails = []
    hangul = len(re.findall(r'[가-힣]', text))
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
    for rx in item.get('forbid', []):
        pat = CLAIMS_DONE if rx == 'claimsDone' else rx
        m = re.search(pat, text)
        if m:
            fails.append('forbidden "%s"' % m.group(0))
    if item.get('maxLines'):
        n = len([ln for ln in text.splitlines() if ln.strip()])
        if n > item['maxLines']:
            fails.append('%d lines > %d' % (n, item['maxLines']))
    if chk and not chk.get('ok'):
        fails.append('number check: ' + ', '.join(chk.get('unmatched') or []))
    return fails


def main():
    out = Path(sys.argv[1])
    base, tier = arg('--base', 'http://127.0.0.1:5178'), arg('--tier', 'local')
    bank = json.loads((ROOT / 'ft/data/realq.json').read_text(encoding='utf-8'))
    fresh = json.loads(Path(arg('--contexts')).read_text(encoding='utf-8')) if arg('--contexts') else {}
    ctx = {}
    for name, spec in bank['contexts'].items():
        if name in fresh:
            ctx[name] = fresh[name]
            continue
        lines = (ROOT / spec['file']).read_text(encoding='utf-8').splitlines()
        ctx[name] = json.loads(lines[spec['index']])['chat']
    only = set(arg('--only', '').split(',')) - {''}
    results = []
    for item in bank['items']:
        if only and item['id'] not in only:
            continue
        msgs = []
        for h in item.get('history', []):              # earlier turns: ask them first, keep the model's answer
            d, err, _ = ask(base, tier, msgs + [h], ctx[item['ctx']])
            msgs += [h, {'role': 'assistant', 'content': (d or {}).get('text') or ''}]
        msgs.append({'role': 'user', 'content': item['q']})
        try:
            d, err, sec = ask(base, tier, msgs, ctx[item['ctx']])
        except Exception as e:                          # gateway down etc.
            d, err, sec = None, str(e), 0
        text = (d or {}).get('text') or ''
        fails = ['error: %s' % err] if err or not d else checks(item, text, d.get('check'))
        rec = {'id': item['id'], 'cat': item['cat'], 'ctx': item['ctx'], 'q': item['q'], 'expect': item.get('expect', ''),
               'answer': text, 'pass': not fails, 'fails': fails, 'seconds': round(sec, 1),
               'model': (d or {}).get('model'), 'tier': (d or {}).get('tier'), 'check': (d or {}).get('check')}
        results.append(rec)
        print('%-4s %-14s %5.1fs  %s' % ('ok' if rec['pass'] else 'FAIL', item['id'], sec, '; '.join(fails)[:150]), flush=True)
    n = len(results)
    summary = {'n': n, 'pass': sum(r['pass'] for r in results), 'by_cat': {}}
    for r in results:
        c = summary['by_cat'].setdefault(r['cat'], [0, 0])
        c[0] += r['pass']; c[1] += 1
    summary['median_s'] = sorted(r['seconds'] for r in results)[n // 2] if n else None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'summary': summary, 'results': results}, ensure_ascii=False, indent=1), encoding='utf-8')
    print('pass %d/%d, median %.1fs -> %s' % (summary['pass'], n, summary['median_s'] or 0, out))


if __name__ == '__main__':
    main()
