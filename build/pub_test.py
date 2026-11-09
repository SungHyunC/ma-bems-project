"""Exercise the public API on 127.0.0.1:5179 (keys read from .env, never printed)."""
import json, sys, time, urllib.error, urllib.request
sys.path.insert(0, r'C:\Users\sunghyun\Desktop\MA-BEMS\server')
from mabems_server import load_env, ENV_PATH
env = load_env(ENV_PATH)
UK = env['MABEMS_USER_KEYS'].split(',')[0].split('=', 1)[1]
AK = env['MABEMS_ADMIN_KEYS'].split(',')[0].split('=', 1)[1]
BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5179'
SITE = 'https://sunghyunc.github.io'

def call(method, path, key=None, origin=None, body=None, timeout=60):
    h = {'User-Agent': 'mabems-test'}
    if key: h['Authorization'] = 'Bearer ' + key
    if origin: h['Origin'] = origin
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h['Content-Type'] = 'application/json'
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode('utf-8', 'replace'), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode('utf-8', 'replace'), time.time() - t0

def show(label, res, keys=()):
    code, hdr, body, dt = res
    extra = ' '.join('%s=%s' % (k, hdr.get(k)) for k in keys if hdr.get(k))
    print('%-46s %s  %.1fs  %s  %s' % (label, code, dt, extra, body[:110].replace('\n', ' | ')))

show('healthz (no key, no origin)', call('GET', '/healthz'))
show('healthz from evil origin', call('GET', '/healthz', origin='https://evil.example'))
show('status without key', call('GET', '/api/llm/status'))
show('status bad key', call('GET', '/api/llm/status', key='mbk_' + 'x' * 32))
code, hdr, body, dt = call('GET', '/api/llm/status', key=UK, origin=SITE)
st = json.loads(body)
print('%-46s %s  access=%s api.available=%s local.alive=%s base_url_hidden=%s ACAO=%s' % ('status user key + site origin', code, st.get('access'), st['api']['available'], st['local']['alive'], 'base_url' not in st['local'], hdr.get('Access-Control-Allow-Origin')))
code, hdr, body, dt = call('GET', '/api/llm/status', key=AK)
st = json.loads(body); print('%-46s %s  access=%s api.available=%s' % ('status admin key', code, st.get('access'), st['api']['available']))
show('status user key + evil origin', call('GET', '/api/llm/status', key=UK, origin='https://evil.example'))
show('preflight from site', call('OPTIONS', '/api/llm/chat', origin=SITE), ('Access-Control-Allow-Origin', 'Access-Control-Allow-Headers', 'Access-Control-Allow-Methods'))
show('preflight from evil', call('OPTIONS', '/api/llm/chat', origin='https://evil.example'))
show('preflight from localhost:8090', call('OPTIONS', '/api/llm/chat', origin='http://127.0.0.1:8090'), ('Access-Control-Allow-Origin',))
for p in ('/index.html', '/.env', '/server/mabems_server.py', '/data/README.md', '/'):
    show('file %s' % p, call('GET', p))
show('v1/models user key', call('GET', '/v1/models', key=UK))
if '--chat' in sys.argv:
    ctx = json.dumps({'clock': '14:05', 'tou': 'peak', 'campus': {'gridImportNowKW': 760, 'peakLimitKW': 1000, 'headroomNowKW': 240}}, ensure_ascii=False)
    code, hdr, body, dt = call('POST', '/api/llm/chat', key=UK, origin=SITE, body={'task': 'chat', 'tier': 'api', 'context': ctx, 'messages': [{'role': 'user', 'content': '피크 여유가 얼마나 남았어? 한 문장으로.'}]}, timeout=120)
    evs = [blk.split('\n') for blk in body.strip().split('\n\n') if blk]
    names = [e[0][7:] for e in evs]
    done = [json.loads(e[1][6:]) for e in evs if e[0] == 'event: done']
    print('%-46s %s  %.1fs  type=%s events=%s' % ('chat user key asking tier=api', code, dt, hdr.get('Content-Type'), sorted(set(names))))
    if done: print('   -> tier=%s model=%s check=%s text=%s' % (done[0]['tier'], done[0]['model'], (done[0].get('check') or {}).get('ok'), done[0]['text'][:120].replace('\n', ' ')))
    code, hdr, body, dt = call('POST', '/v1/chat/completions', key=UK, body={'model': 'anything', 'messages': [{'role': 'user', 'content': 'Reply with exactly: pong'}], 'max_tokens': 20, 'temperature': 0}, timeout=120)
    j = json.loads(body)
    print('%-46s %s  %.1fs  model=%s content=%r usage=%s' % ('v1/chat/completions user key', code, dt, j.get('model'), (j.get('choices') or [{}])[0].get('message', {}).get('content'), j.get('usage')))
    show('v1/chat/completions stream=true', call('POST', '/v1/chat/completions', key=UK, body={'messages': [{'role': 'user', 'content': 'hi'}], 'stream': True}))
