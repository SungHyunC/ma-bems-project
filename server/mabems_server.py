#!/usr/bin/env python3
"""MA-BEMS local server: static files + LLM gateway.

    .venv\\Scripts\\python server\\mabems_server.py [--port 5178] [--public-port 5179] [--selftest]
    .venv\\Scripts\\python server\\mabems_server.py --new-key NAME [--admin] | --revoke NAME | --list-keys [--show]

Serves index.html (no-store) and:
  GET  /api/llm/status   tiers, models, availability, call counters
  POST /api/llm/chat     Server-Sent Events: meta -> delta* -> done | error
                         body {task: chat|brief|explain|propose, messages: [{role, content}], context: str, tier: auto|local|api}
Tiers follow the user's BEMS policy: local Ollama first (free, private), Claude when the local
model is down, too slow to start, or returns invalid JSON. Prompts and JSON schemas live here,
not in the page, and ANTHROPIC_API_KEY is read from MA-BEMS/.env (or the environment): the key
never reaches the browser.

Public API (MABEMS_PUBLIC_PORT, bound to 127.0.0.1; deploy/start-public.ps1 puts a Cloudflare tunnel in front of it):
no files, an access key on every call (Authorization: Bearer <key>), CORS limited to the public site, per-key rate
limits. Same /api/llm/status and /api/llm/chat as above, plus GET /healthz and an OpenAI-style
POST /v1/chat/completions (non-streaming) so any OpenAI-compatible client can use this PC's local model with a key.
"""
import argparse
import hmac
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numcheck  # noqa: E402  (number guardrail ported from multi-agent-bems)
import assist  # noqa: E402  (glossary, follow-up rewriting and output guards for typed questions)

ROOT = Path(__file__).resolve().parent.parent


def load_env(path):
    out = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


ENV_PATH = ROOT / '.env'
ENV = {**load_env(ENV_PATH), **{k: v for k, v in os.environ.items() if k.startswith(('LLM_', 'ANTHROPIC_', 'MABEMS_'))}}
CFG = {
    'local_base': ENV.get('LLM_LOCAL_BASE_URL', 'http://127.0.0.1:11434').rstrip('/'),
    'local_model': ENV.get('LLM_LOCAL_MODEL', 'qwen3-8b-local'),
    'local_keep_alive': ENV.get('LLM_LOCAL_KEEP_ALIVE', '30m'),
    'local_first_token_s': float(ENV.get('LLM_LOCAL_FIRST_TOKEN_SECONDS', '25')),
    'api_model': ENV.get('LLM_API_MODEL', 'claude-opus-5-5'),
    'api_effort': ENV.get('LLM_API_EFFORT', 'low'),
    'api_max_calls_per_hour': int(ENV.get('LLM_API_MAX_CALLS_PER_HOUR', '60')),
    'policy': ENV.get('LLM_POLICY', 'local_first'),          # local_first | api_first | local_only | api_only
}
API_KEY = ENV.get('ANTHROPIC_API_KEY', '')

# ---------- prompts (stable text first so the Claude prompt cache can reuse it) ----------
SYSTEM_BASE = """당신은 'Helio Campus' 스마트 캠퍼스의 에너지 운영 비서이며 MA-BEMS 대시보드에 내장되어 있습니다.
캠퍼스: B1 오피스 타워(8층), B2 연구동(4층), B3 기숙사(5층), B4 데이터센터(2층), 옥상·주차장 태양광, ESS(배터리), EV 충전기 6기.
6개 에이전트(코디네이터, HVAC, 조명, 태양광, ESS, EV 충전)가 15분마다 관찰→계획→협상→실행→검증을 반복합니다.
같은 날씨로 룰 기반 BMS(기준선)도 함께 시뮬레이션하며, '절감률'은 이 기준선 대비입니다.

규칙:
- 사용자가 쓴 언어로 답합니다(한국어 질문에는 한국어).
- <campus_state> 안의 값만 근거로 씁니다. 없는 값은 지어내지 말고 '데이터에 없음'이라고 말합니다.
- 숫자에는 단위(kW, kWh, °C, %, 원 또는 $)를 붙이고, 시각은 시뮬레이션 시계 기준입니다.
- 짧게 씁니다: 결론 한 문장, 그다음 근거 2~4개를 '- '로 시작하는 줄로. 제목(#)과 표는 쓰지 않습니다.
- 운영 우선순위: 1) 피크 한도(peakLimit) 초과 방지 2) 재실 구역 쾌적 범위(설정온도 ±1.5 °C) 3) 비용·탄소.
  데이터센터(B4)와 서버실·전기실 냉방은 줄이지 않습니다.
- 당신은 설비를 직접 제어하지 않습니다. 제안은 운영자가 승인해야 적용됩니다."""

TASKS = {
    'chat': {'max_local': 700, 'max_api': 3000, 'note': ''},
    'brief': {'max_local': 600, 'max_api': 3000, 'note': """
지금 할 일: 현재 상황을 운영 브리핑으로 요약합니다. '- '로 시작하는 줄 3~5개:
현재 부하와 피크 여유, 요금 구간, 에이전트들이 지금 하는 조치와 이유(최근 로그 근거), 앞으로 1시간 주의점."""},
    'explain': {'max_local': 600, 'max_api': 3000, 'note': """
지금 할 일: <campus_state>의 selected(운영자가 선택한 대상)를 설명합니다.
현재 상태, 정상/주의 여부와 이유, 관련 에이전트 조치, 운영자가 할 수 있는 일을 짧게."""},
    'propose': {'max_local': 900, 'max_api': 4000, 'note': """
지금 할 일: 피크·비용·쾌적을 개선할 제어 조치를 최대 4개 JSON으로 제안합니다.
허용 type과 value:
- setpoint: target = zone id(예: B1-F3), value = 22~28 사이 숫자(°C)
- roomSetpoint: target = room id(예: B1-F3-R2), value = 22~28 사이 숫자 또는 "null"(구역 설정 따르기)
- roomLights: target = room id, value = "auto" | "on" | "off"
<campus_state>에 있는 id만 씁니다. B4와 서버실·전기실 냉방 완화는 금지입니다. 조치가 필요 없으면 actions를 빈 배열로 둡니다.
같은 대상에는 조치를 하나만, 이미 그 상태인 조치(예: 이미 꺼진 빈 방의 조명 off)는 제안하지 않습니다.
summary, expected_effect, reason은 사용자의 언어(기본 한국어)로 씁니다."""},
}
PROPOSAL_SCHEMA = {
    'type': 'object',
    'properties': {
        'summary': {'type': 'string'},
        'actions': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'type': {'type': 'string', 'enum': ['setpoint', 'roomSetpoint', 'roomLights']},
                'target': {'type': 'string'},
                'value': {'type': 'string'},
                'expected_effect': {'type': 'string'},
                'reason': {'type': 'string'},
            },
            'required': ['type', 'target', 'value', 'expected_effect', 'reason'],
            'additionalProperties': False,
        }},
    },
    'required': ['summary', 'actions'],
    'additionalProperties': False,
}
SCHEMAS = {'propose': PROPOSAL_SCHEMA}
_TEMPS = ['%g' % (22 + 0.5 * i) for i in range(13)]       # setpoints the page accepts: 22, 22.5, ... 28 °C


def proposal_schema(context, question=''):
    """PROPOSAL_SCHEMA narrowed to this request, for the local model: targets limited to the candidate zone and room ids
    in campus_state, values to what the page accepts. Qwen3-8B filled the free-text fields with 'ess', 'roomLights' or
    several ids in one string (0 of 16 actions valid in a test); with the ids as enums, Ollama's grammar-constrained
    decoding cannot write anything else (16 of 16 valid, 3.9 s). Claude keeps the general schema and picks real ids.
    A typed request about cooling allows setpoint actions only and one about lights only light actions: asked
    "에어컨 좀 약하게 해줘", v2.1 sometimes proposed switching off empty rooms' lights, its most common proposal."""
    try:
        c = json.loads(context)
    except ValueError:
        return PROPOSAL_SCHEMA
    ids = lambda key, ok=lambda x: True: [x['id'] for x in (c.get(key) or []) if isinstance(x, dict) and x.get('id') and ok(x)]   # noqa: E731
    zones = ids('candidateZones')
    rooms = ids('candidateRooms', lambda r: not (isinstance(r.get('setpointC'), (int, float)) and r['setpointC'] < 15))   # never cold rooms

    def act(kind, targets, values):
        return {'type': 'object', 'properties': {
            'type': {'type': 'string', 'enum': [kind]}, 'target': {'type': 'string', 'enum': targets},
            'value': {'type': 'string', 'enum': values}, 'expected_effect': {'type': 'string'}, 'reason': {'type': 'string'}},
            'required': ['type', 'target', 'value', 'expected_effect', 'reason'], 'additionalProperties': False}
    temp = re.search(r'에어컨|냉방|난방|온도|설정|공조|cool|heat|temperature|setpoint|\bAC\b', question or '', re.I)
    light = re.search(r'불|조명|전등|light', question or '', re.I)
    kinds = {'setpoint', 'roomSetpoint'} if temp and not light else {'roomLights'} if light and not temp else {'setpoint', 'roomSetpoint', 'roomLights'}
    variants = ([act('setpoint', zones, _TEMPS)] if zones and 'setpoint' in kinds else []) + \
               ([act('roomSetpoint', rooms, _TEMPS + ['null'])] if rooms and 'roomSetpoint' in kinds else []) + \
               ([act('roomLights', rooms, ['auto', 'on', 'off'])] if rooms and 'roomLights' in kinds else [])
    if not variants:
        return PROPOSAL_SCHEMA
    return {'type': 'object', 'properties': {'summary': {'type': 'string'},
                                             'actions': {'type': 'array', 'maxItems': 4, 'items': {'anyOf': variants}}},
            'required': ['summary', 'actions'], 'additionalProperties': False}

# ---------- counters ----------
LOCK = threading.Lock()
STATS = {t: {'calls': 0, 'failures': 0, 'escalations': 0, 'latency_ms': 0.0, 'input_tokens': 0, 'output_tokens': 0, 'cache_read_tokens': 0, 'cache_write_tokens': 0} for t in ('local', 'api')}
API_CALLS = []                                          # timestamps of Claude calls in the last hour


def stat(tier, **kw):
    with LOCK:
        for k, v in kw.items():
            STATS[tier][k] += v


# ---------- local tier: Ollama ----------
_TAGS = {'t': 0, 'alive': False, 'models': []}


def local_tags(force=False):
    if not force and time.time() - _TAGS['t'] < 15:
        return _TAGS
    try:
        with urllib.request.urlopen(CFG['local_base'] + '/api/tags', timeout=2.5) as r:
            data = json.loads(r.read().decode('utf-8'))
        _TAGS.update(t=time.time(), alive=True, models=[m.get('name') for m in data.get('models', [])])
    except Exception:
        _TAGS.update(t=time.time(), alive=False, models=[])
    return _TAGS


class TierFailed(Exception):
    def __init__(self, reason, sent=False):
        super().__init__(reason)
        self.reason, self.sent = reason, sent


def run_local(system, messages, task, emit, schema=None):
    safe_stream = assist.SafeStream(system, emit)
    emit = safe_stream.feed
    schema = schema or SCHEMAS.get(task)
    payload = {
        'model': CFG['local_model'], 'stream': True, 'think': False, 'keep_alive': CFG['local_keep_alive'],
        'messages': [{'role': 'system', 'content': system}] + messages,
        'options': {'temperature': 0.3, 'num_predict': TASKS[task]['max_local']},
    }
    # always 8192 tokens: Ollama's default is 4096, and Korean + JSON runs ~1.5 characters per token, so a 4.4k-character
    # explain context already overflowed it (3 of 234 held-out requests); one fixed size also avoids a reload per change
    payload['options']['num_ctx'] = 8192
    if schema:
        payload['format'] = schema
    req = urllib.request.Request(CFG['local_base'] + '/api/chat', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
    out, sent, in_think, usage, size, checked, looped = [], False, False, {}, 0, 0, False
    try:
        with urllib.request.urlopen(req, timeout=CFG['local_first_token_s']) as r:
            for raw in r:
                if not schema and size - checked >= 120:   # a decoding loop ("셋백·소등·공조를 셋백·소등·…") runs to the token cap
                    checked = size
                    cut = assist.find_loop(''.join(out))
                    if cut >= 0:                          # keep what came before it; leaving the stream stops generation
                        kept = ''.join(out)[:cut].rstrip(' ·,')
                        out, looped = [kept + ' …' if len(kept) >= 12 else ''], True
                        break
                if not raw.strip():
                    continue
                line = json.loads(raw.decode('utf-8'))
                if line.get('error'):
                    raise TierFailed('ollama: ' + str(line['error'])[:160], sent)
                piece = (line.get('message') or {}).get('content') or ''
                # qwen3 may still wrap a (empty) reasoning block; never show it
                while piece:
                    if in_think:
                        end = piece.find('</think>')
                        if end < 0:
                            piece = ''
                        else:
                            piece, in_think = piece[end + 8:], False
                    else:
                        start = piece.find('<think>')
                        if start < 0:
                            break
                        head, piece, in_think = piece[:start], piece[start + 7:], True
                        if head:
                            out.append(head)
                            if not schema:
                                emit(head); sent = True
                if piece and not in_think:
                    out.append(piece)
                    size += len(piece)
                    if not schema:
                        emit(piece); sent = True
                if line.get('done'):
                    usage = {'input_tokens': line.get('prompt_eval_count', 0), 'output_tokens': line.get('eval_count', 0)}
                    break
    except TierFailed:
        raise
    except (socket.timeout, TimeoutError):
        raise TierFailed('local model did not answer within %ds' % CFG['local_first_token_s'], sent)
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:200]
        raise TierFailed('ollama HTTP %d: %s' % (e.code, detail), sent)
    except urllib.error.URLError as e:
        raise TierFailed('ollama unreachable: %s' % getattr(e, 'reason', e), sent)
    except Exception as e:                                # malformed stream etc.
        raise TierFailed('local error: %s' % e, sent)
    if not schema:
        safe_stream.finish()
    text = ''.join(out).strip()
    if not text and not looped:                           # a loop with nothing before it: chat() says so instead
        raise TierFailed('local model returned nothing', sent)
    return text, CFG['local_model'], usage


# ---------- API tier: Claude (official SDK) ----------
_CLIENT = None


def api_client():
    global _CLIENT
    if _CLIENT is None:
        import anthropic
        _CLIENT = anthropic.Anthropic(api_key=API_KEY, timeout=anthropic.Timeout(90.0, connect=8.0), max_retries=1)
    return _CLIENT


def api_ready():
    if not API_KEY:
        return False, 'ANTHROPIC_API_KEY not set in MA-BEMS/.env'
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, 'anthropic SDK not installed (pip install anthropic)'
    with LOCK:
        now = time.time()
        while API_CALLS and now - API_CALLS[0] > 3600:
            API_CALLS.pop(0)
        if len(API_CALLS) >= CFG['api_max_calls_per_hour']:
            return False, 'hourly cap of %d Claude calls reached' % CFG['api_max_calls_per_hour']
    return True, None


def run_api(system, messages, task, emit):
    import anthropic
    ok, why = api_ready()
    if not ok:
        raise TierFailed(why)
    with LOCK:
        API_CALLS.append(time.time())
    schema = SCHEMAS.get(task)
    output_config = {'effort': CFG['api_effort']}
    if schema:
        output_config['format'] = {'type': 'json_schema', 'schema': schema}
    sent = False
    try:
        with api_client().beta.messages.stream(
            model=CFG['api_model'],
            max_tokens=TASKS[task]['max_api'],
            system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
            messages=messages,
            output_config=output_config,
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',                          # a policy decline is retried server-side on Anthropic's recommended model
        ) as stream:
            for text in stream.text_stream:
                if not schema:
                    emit(text); sent = True
            final = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise TierFailed('Claude rejected the API key', sent)
    except anthropic.RateLimitError:
        raise TierFailed('Claude rate limit (429)', sent)
    except anthropic.APIStatusError as e:
        raise TierFailed('Claude API error %s: %s' % (e.status_code, str(e.message)[:160]), sent)
    except anthropic.APIConnectionError:
        raise TierFailed('Claude API unreachable (network)', sent)
    if final.stop_reason == 'refusal':
        raise TierFailed('Claude declined this request', sent)
    text = ''.join(b.text for b in final.content if b.type == 'text').strip()
    u = final.usage
    usage = {'input_tokens': u.input_tokens or 0, 'output_tokens': u.output_tokens or 0,   # input_tokens excludes cached tokens
             'cache_read_tokens': getattr(u, 'cache_read_input_tokens', 0) or 0,           # billed at 0.05x input on Opus 5.5
             'cache_write_tokens': getattr(u, 'cache_creation_input_tokens', 0) or 0}      # billed at 1.25x input (5-min TTL)
    return text, final.model, usage


# ---------- routing ----------
# per-task routes under the default policy: control proposals need Claude (an 8B local model picks
# targets that do not exist); questions, briefings and explanations try the local model first
TASK_ROUTES = {'propose': ['api', 'local']}


def tier_order(pref, task='chat'):
    if pref == 'local':
        return ['local']
    if pref == 'api':
        return ['api']
    if CFG['policy'] == 'local_first' and task in TASK_ROUTES:
        return TASK_ROUTES[task]
    return {'api_first': ['api', 'local'], 'local_only': ['local'], 'api_only': ['api']}.get(CFG['policy'], ['local', 'api'])


def clean_messages(raw):
    out = []
    for m in (raw or [])[-16:]:
        role = m.get('role')
        content = str(m.get('content') or '')[:4000]
        if role in ('user', 'assistant') and content.strip():
            out.append({'role': role, 'content': content})
    while out and out[0]['role'] != 'user':
        out.pop(0)
    return out


def valid_json(text):
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r'\{.*\}', text, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return None
    if not isinstance(data, dict) or not isinstance(data.get('actions'), list) or not isinstance(data.get('summary'), str):
        return None
    return data


def drop_noops(data, context, question=''):
    """Remove proposed actions that would change nothing in the campus state the model was given, and say so.

    Fine-tuned Qwen3-8B v2.1 still raised the setpoint of empty rooms whose air handling was already in setback or off
    (all 101 wrong actions on 33 held-out "nothing to do" states, ft/README.md). Dropping these is deterministic, so
    the operator sees "nothing to change" instead of buttons that do nothing:
      roomSetpoint  same as the current setpoint, or raised on a room whose hvacMode is setback / off
      roomLights    already in that mode, or "off" for a room that is already dark
      setpoint      same as the zone's current setpoint
    Targets missing from the context are left alone (the page validates them). Returns the number dropped."""
    try:
        c = json.loads(context)
    except ValueError:
        return 0
    rooms = {x['id']: x for x in (c.get('candidateRooms') or []) if isinstance(x, dict) and x.get('id')}
    zones = {x['id']: x for x in (c.get('candidateZones') or []) if isinstance(x, dict) and x.get('id')}

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def noop(a):
        t, tg, v = a.get('type'), a.get('target'), str(a.get('value'))
        r, z = rooms.get(tg), zones.get(tg)
        if t == 'roomSetpoint' and r and num(v) is not None and num(r.get('setpointC')) is not None:
            same = abs(num(v) - r['setpointC']) < 0.05
            return same or (r.get('hvacMode') in ('setback', 'off') and num(v) > r['setpointC'])
        if t == 'roomLights' and r:
            return v == r.get('lights') or (v == 'off' and not (r.get('lightLevelPct') or 0))
        if t == 'setpoint' and z and num(v) is not None and num(z.get('setpointC')) is not None:
            return abs(num(v) - z['setpointC']) < 0.05
        return False

    keep = [a for a in data['actions'] if not noop(a)]
    dropped = len(data['actions']) - len(keep)
    if not dropped:
        return 0
    ko = bool(re.search(r'[가-힣]', question)) or not question
    data['actions'] = keep
    data['dropped'] = dropped
    if not keep:
        data['summary'] = ('지금은 바꿀 필요가 없습니다: 제안된 조치 %d개는 이미 그 상태인 대상이라 뺐습니다.' % dropped if ko else
                           'Nothing needs changing now: the %d proposed actions targeted rooms already in that state.' % dropped)
    else:
        data['summary'] = data['summary'].rstrip() + (' (이미 그 상태인 조치 %d개는 뺐습니다.)' % dropped if ko else
                                                      ' (%d actions that would change nothing were removed.)' % dropped)
    return dropped


def chat(body, send):
    task = body.get('task') if body.get('task') in TASKS else 'chat'
    messages = clean_messages(body.get('messages'))
    if not messages:
        send('error', {'message': 'empty question'}); return
    context = str(body.get('context') or '')[:14000]
    question = messages[-1]['content']
    system = SYSTEM_BASE + TASKS[task]['note']
    if any(assist.PROMPT_ASK.search(m['content']) for m in messages if m['role'] == 'user'):      # hidden instructions or keys: a fixed answer, no model
        send('meta', {'tier': 'rule', 'model': 'rule', 'task': task})
        send('done', {'tier': 'rule', 'model': 'rule', 'latency_ms': 0, 'usage': {}, 'text': assist.refusal(question), 'json': {'summary': assist.refusal(question), 'actions': []} if task == 'propose' else None, 'check': None})
        return
    if task == 'chat':
        messages = assist.contextualize(messages)                  # "왜 그런 거야?" carries the question it follows
        question = messages[-1]['content']
        looked = assist.forecast_answer(question, context) or assist.lookup_answer(question, context)
        fixed = looked or assist.define_answer(question, context) or assist.faq_answer(question, context)
        if fixed:                                                  # timetable lookups, definitions, one FAQ: no model
            kind = 'lookup' if looked else 'faq'
            send('meta', {'tier': 'rule', 'model': kind, 'task': task})
            send('done', {'tier': 'rule', 'model': kind, 'latency_ms': 0, 'usage': {}, 'text': fixed, 'json': None,
                          'check': numcheck.check(fixed, context, question, rules=system) if context else None})
            return
        context = assist.augment(question, context)                # the record asked about + grounding for concept questions
    context = assist.model_view(context)                           # the timetable stays with the gateway (see assist.model_view)
    if context:
        messages[-1] = {'role': 'user', 'content': '<campus_state>\n' + context + '\n</campus_state>\n\n' + messages[-1]['content']}
    order = tier_order(body.get('tier', 'auto'), task)
    for i, tier in enumerate(order):
        if tier == 'local' and not local_tags()['alive']:
            reason = 'ollama is not running at ' + CFG['local_base']
            stat('local', failures=1)
            if i + 1 < len(order):
                stat('local', escalations=1); send('escalate', {'from': 'local', 'to': order[i + 1], 'reason': reason, 'reset': False}); continue
            send('error', {'message': reason}); return
        model = CFG['local_model'] if tier == 'local' else CFG['api_model']
        send('meta', {'tier': tier, 'model': model, 'task': task})
        t0 = time.time()
        try:
            emit = lambda s: send('delta', {'text': s})   # noqa: E731
            if tier == 'local':
                text, served_by, usage = run_local(system, messages, task, emit, proposal_schema(context, question) if task == 'propose' else None)
            else:
                text, served_by, usage = run_api(system, messages, task, emit)
            data, chk = None, None
            if task in SCHEMAS:
                data = valid_json(text)
                if data is None:
                    raise TierFailed('the model returned invalid JSON')
                seen, acts = set(), []                    # one action per target
                for a in data['actions']:
                    if isinstance(a, dict) and (a.get('type'), a.get('target')) not in seen:
                        seen.add((a.get('type'), a.get('target')))
                        acts.append(a)
                data['actions'] = acts
                drop_noops(data, context, question)
                assist.align_summary(data, question)          # the summary must name the actions it shows
                acts = data['actions']
                if acts and not any(str(a.get('target', '')) and str(a.get('target')) in context for a in acts) and i + 1 < len(order):
                    raise TierFailed('none of the proposed targets exist in the campus data')
            else:
                if assist.leaks_prompt(text, system):
                    text = assist.refusal(question)
                text = assist.clean_answer(text, context)
                if len(text.strip(' .…')) < 2:                # the model looped from its first words
                    text = ('답을 만들다 같은 말이 반복되어 멈췄습니다. 질문을 조금 바꿔 다시 물어봐 주세요.' if re.search(r'[가-힣]', question) else
                            'The answer started repeating itself, so it was stopped. Please rephrase the question.')
            if task not in SCHEMAS and context:
                chk = numcheck.check(text, context, question, rules=system)   # the operating rules' numbers (±1.5 °C) are facts too
                if not chk['ok'] and tier == 'local' and i + 1 < len(order) and api_ready()[0]:
                    raise TierFailed('number/meaning check failed: ' + ', '.join(chk['unmatched']), True)
            ms = (time.time() - t0) * 1000
            stat(tier, calls=1, latency_ms=ms, input_tokens=usage.get('input_tokens', 0), output_tokens=usage.get('output_tokens', 0),
                 cache_read_tokens=usage.get('cache_read_tokens', 0), cache_write_tokens=usage.get('cache_write_tokens', 0))
            send('done', {'tier': tier, 'model': served_by, 'latency_ms': round(ms), 'usage': usage, 'text': text, 'json': data, 'check': chk})
            return
        except TierFailed as e:
            stat(tier, calls=1, failures=1)
            if i + 1 < len(order):
                stat(tier, escalations=1)
                send('escalate', {'from': tier, 'to': order[i + 1], 'reason': e.reason, 'reset': e.sent}); continue
            send('error', {'message': e.reason, 'tier': tier}); return


def status():
    tags = local_tags()
    ok, why = api_ready()
    with LOCK:
        stats = json.loads(json.dumps(STATS))
        recent = len(API_CALLS)
    return {
        'policy': CFG['policy'],
        'local': {'provider': 'ollama', 'base_url': CFG['local_base'], 'model': CFG['local_model'], 'alive': tags['alive'],
                  'installed': CFG['local_model'] in tags['models'] or any(m.split(':')[0] == CFG['local_model'] for m in tags['models']), 'models': tags['models']},
        'api': {'provider': 'anthropic', 'model': CFG['api_model'], 'effort': CFG['api_effort'], 'available': ok, 'reason': why,
                'calls_last_hour': recent, 'cap_per_hour': CFG['api_max_calls_per_hour']},
        'stats': stats,
    }


# ---------- public API: access keys, allowed origins, rate limits ----------
# Keys live in .env and are re-read whenever the file changes, so issuing or revoking one needs no restart:
#   MABEMS_USER_KEYS=judges=mbk_...,team=mbk_...   local model only
#   MABEMS_ADMIN_KEYS=owner=mba_...                local model + Claude (Claude still under LLM_API_MAX_CALLS_PER_HOUR)
PUB = {
    'port': int(ENV.get('MABEMS_PUBLIC_PORT') or 0),
    'origins': {o.strip().rstrip('/') for o in ENV.get('MABEMS_ALLOWED_ORIGINS', 'https://sunghyunc.github.io').split(',') if o.strip()},
    'per_min': int(ENV.get('MABEMS_KEY_RATE_PER_MIN', '10')),
    'per_day': int(ENV.get('MABEMS_KEY_DAILY_CAP', '300')),
    'site': ENV.get('MABEMS_SITE_URL', 'https://sunghyunc.github.io/ma-bems/'),
}
INFLIGHT = threading.BoundedSemaphore(max(1, int(ENV.get('MABEMS_MAX_INFLIGHT', '2'))))   # Ollama answers one at a time
KEY_VARS = (('MABEMS_USER_KEYS', 'user'), ('MABEMS_ADMIN_KEYS', 'admin'))
_LOCAL_ORIGIN = re.compile(r'^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$')
_KEYS = {'mtime': None, 'map': {}}
RATE = {}                                                # key name -> sliding one-minute window + daily count


def access_keys():
    """{key: (name, scope)} from .env (or the environment), re-read when .env changes."""
    try:
        mtime = ENV_PATH.stat().st_mtime
    except OSError:
        mtime = 0
    if mtime != _KEYS['mtime']:
        env = {**load_env(ENV_PATH), **{k: v for k, v in os.environ.items() if k in dict(KEY_VARS)}}
        found = {}
        for var, scope in KEY_VARS:
            for item in env.get(var, '').split(','):
                name, _, key = item.strip().partition('=')
                if len(key.strip()) >= 24:                # placeholders and typos are not keys
                    found[key.strip()] = (name.strip() or 'key', scope)
        _KEYS.update(mtime=mtime, map=found)
    return _KEYS['map']


def key_owner(header):
    token = header[7:].strip() if header and header[:7].lower() == 'bearer ' else ''
    match = None
    if token:
        for key, who in access_keys().items():           # constant-time compare against every key
            if hmac.compare_digest(key.encode(), token.encode()):
                match = who
    return match


def origin_ok(origin):
    """Browsers send Origin on cross-site calls: a key works in a browser only on the public site (or a page on this
    PC). Calls without Origin (curl, scripts, SDKs) are API clients and need only the key."""
    return not origin or origin.rstrip('/') in PUB['origins'] or bool(_LOCAL_ORIGIN.match(origin))


def rate_check(name, scope):
    now, today = time.time(), time.strftime('%Y-%m-%d')
    per_min = PUB['per_min'] * (3 if scope == 'admin' else 1)
    with LOCK:
        r = RATE.setdefault(name, {'win': [], 'day': today, 'n': 0})
        r['win'] = [t for t in r['win'] if now - t < 60]
        if r['day'] != today:
            r['day'], r['n'] = today, 0
        if len(r['win']) >= per_min:
            return 'too many requests: %d per minute per key' % per_min, max(1, int(61 - (now - r['win'][0])))
        if scope != 'admin' and r['n'] >= PUB['per_day']:
            return 'daily cap of %d requests reached for this key' % PUB['per_day'], 3600
        r['win'].append(now)
        r['n'] += 1
    return None, 0


def public_status(name, scope):
    st = status()
    st['local'] = {k: v for k, v in st['local'].items() if k not in ('base_url', 'models')}   # no internals over the tunnel
    st['access'] = {'name': name, 'scope': scope}
    if scope != 'admin':
        st['api'] = {**st['api'], 'available': False, 'reason': 'Claude is reserved for the operator (admin key)'}
    return st


def openai_chat(body):
    """Minimal OpenAI-style chat completion on the local model (non-streaming: quick tunnels buffer responses anyway),
    so any OpenAI-compatible client can use this PC's LLM with an access key. The model is always the local one."""
    msgs = []
    for m in (body.get('messages') or [])[-32:]:
        if not isinstance(m, dict):
            continue
        role, content = m.get('role'), m.get('content')
        if isinstance(content, list):                    # [{type: text, text: ...}] parts
            content = ''.join(p.get('text', '') for p in content if isinstance(p, dict))
        if role in ('system', 'user', 'assistant') and isinstance(content, str) and content.strip():
            msgs.append({'role': role, 'content': content[:8000]})
    bad = lambda msg: (400, {'error': {'message': msg, 'type': 'invalid_request_error'}})   # noqa: E731
    if not msgs:
        return bad('messages is empty')
    if body.get('stream'):
        return bad('stream=true is not supported through the tunnel; send stream=false')
    try:
        max_tokens = max(1, min(int(body.get('max_tokens') or body.get('max_completion_tokens') or 512), 2048))
        temperature = max(0.0, min(float(body.get('temperature', 0.7)), 2.0))
    except (TypeError, ValueError):
        return bad('max_tokens and temperature must be numbers')
    payload = {'model': CFG['local_model'], 'stream': False, 'think': False, 'keep_alive': CFG['local_keep_alive'],
               'messages': msgs, 'options': {'temperature': temperature, 'num_predict': max_tokens, 'num_ctx': 8192}}
    req = urllib.request.Request(CFG['local_base'] + '/api/chat', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            out = json.loads(r.read().decode('utf-8'))
    except Exception as e:                                # down, timeout, HTTP error
        stat('local', calls=1, failures=1)
        return 502, {'error': {'message': 'local model unavailable: %s' % e, 'type': 'server_error'}}
    text = re.sub(r'<think>.*?</think>', '', (out.get('message') or {}).get('content') or '', flags=re.S).strip()
    pin, pout = out.get('prompt_eval_count', 0), out.get('eval_count', 0)
    stat('local', calls=1, latency_ms=(time.time() - t0) * 1000, input_tokens=pin, output_tokens=pout)
    return 200, {'id': 'chatcmpl-' + secrets.token_hex(12), 'object': 'chat.completion', 'created': int(time.time()), 'model': CFG['local_model'],
                 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text},
                              'finish_reason': 'length' if out.get('done_reason') == 'length' else 'stop'}],
                 'usage': {'prompt_tokens': pin, 'completion_tokens': pout, 'total_tokens': pin + pout}}


# ---------- HTTP ----------
class ApiIO:
    """Response helpers shared by the page server (this PC) and the public API (the tunnel)."""

    def cors(self):
        pass

    def send_json(self, code, obj, headers=None):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0 or n > 256 * 1024:
            self.send_json(413 if n > 0 else 400, {'error': 'request too large' if n > 0 else 'empty request'})
            return None
        try:
            body = json.loads(self.rfile.read(n).decode('utf-8'))
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self.send_json(400, {'error': 'invalid JSON'})
            return None
        return body

    def stream_chat(self, body):
        # text/event-stream: streams on this PC; a Cloudflare quick tunnel buffers it and delivers it whole, which the
        # page's reader handles the same way
        self.send_response(200)
        self.cors()
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

        def send(event, data):
            self.wfile.write(('event: %s\ndata: %s\n\n' % (event, json.dumps(data, ensure_ascii=False))).encode('utf-8'))
            self.wfile.flush()
        try:
            chat(body, send)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass                                          # the page closed the stream


class Handler(ApiIO, SimpleHTTPRequestHandler):
    server_version = 'MA-BEMS/1.0'

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):
        if '/api/llm/status' not in str(args[0] if args else ''):
            sys.stderr.write('[%s] %s\n' % (time.strftime('%H:%M:%S'), fmt % args))

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def _blocked(self):
        # allowlist on the decoded path: the page itself and data/ only (.env, .venv and server/ sit in the same folder)
        path = unquote(self.path.split('?', 1)[0].split('#', 1)[0]).replace('\\', '/')
        parts = [p for p in path.split('/') if p]
        if any(p.startswith('.') or ':' in p for p in parts):
            return True
        return not (not parts or parts == ['index.html'] or parts == ['favicon.ico'] or (parts[0] == 'data' and len(parts) > 1))

    def do_GET(self):
        if self.path.startswith('/api/llm/status'):
            return self.send_json(200, status())
        if self._blocked():
            return self.send_error(404)
        return super().do_GET()

    def do_HEAD(self):
        if self._blocked():
            return self.send_error(404)
        return super().do_HEAD()

    def do_POST(self):
        origin = self.headers.get('Origin')
        port = self.server.server_address[1]
        if origin is not None and origin not in ('http://127.0.0.1:%d' % port, 'http://localhost:%d' % port):
            return self.send_error(403)
        if self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
            return self.send_error(415)
        if not self.path.startswith('/api/llm/chat'):
            return self.send_error(404)
        body = self.read_body()
        if body is not None:
            self.stream_chat(body)


class PublicHandler(ApiIO, BaseHTTPRequestHandler):
    """The tunnel's side: API only, never files. cloudflared connects from 127.0.0.1, so the visitor's address comes
    from Cloudflare's CF-Connecting-IP header (used in the log only)."""
    server_version = 'MA-BEMS-API/1.0'
    who = '-'

    def log_message(self, fmt, *args):
        ip = self.headers.get('CF-Connecting-IP', '-') if getattr(self, 'headers', None) else '-'
        sys.stderr.write('[%s] public %s %s %s\n' % (time.strftime('%H:%M:%S'), ip, self.who, fmt % args))

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def cors(self):
        origin = self.headers.get('Origin')
        if origin and origin_ok(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')

    def do_OPTIONS(self):                                 # CORS preflight (the Authorization header triggers one)
        origin = self.headers.get('Origin')
        if not origin or not origin_ok(origin):
            return self.send_json(403, {'error': 'origin not allowed'})
        self.send_response(204)
        self.cors()
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Max-Age', '600')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def authorized(self):
        if not origin_ok(self.headers.get('Origin')):
            self.send_json(403, {'error': 'origin not allowed'})
            return None
        who = key_owner(self.headers.get('Authorization'))
        if not who:
            self.send_json(401, {'error': 'missing or unknown access key'}, {'WWW-Authenticate': 'Bearer'})
            return None
        self.who = '%s/%s' % who
        return who

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/healthz':                            # no key: lets the site show whether the operator's PC is up
            if not origin_ok(self.headers.get('Origin')):
                return self.send_json(403, {'error': 'origin not allowed'})
            return self.send_json(200, {'ok': True, 'service': 'ma-bems', 'local_model_up': local_tags()['alive']})
        if path in ('/api/llm/status', '/v1/models'):
            who = self.authorized()
            if who:
                self.send_json(200, public_status(*who) if path == '/api/llm/status' else
                               {'object': 'list', 'data': [{'id': CFG['local_model'], 'object': 'model', 'owned_by': 'ma-bems'}]})
            return
        self.send_json(404, {'error': 'not found'})

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        if path not in ('/api/llm/chat', '/v1/chat/completions'):
            return self.send_json(404, {'error': 'not found'})
        who = self.authorized()
        if not who:
            return
        if path == '/v1/chat/completions' and who[1] != 'admin':
            return self.send_json(403, {'error': {'message': 'Administrator access required', 'type': 'permission_error', 'param': None, 'code': 'forbidden'}})
        why, wait = rate_check(*who)
        if why:
            return self.send_json(429, {'error': why, 'retry_after_s': wait}, {'Retry-After': str(wait)})
        body = self.read_body()
        if body is None:
            return
        if not INFLIGHT.acquire(blocking=False):
            return self.send_json(503, {'error': 'the local model is busy with other requests; try again in a few seconds', 'retry_after_s': 5},
                                  {'Retry-After': '5'})
        try:
            if path == '/v1/chat/completions':
                self.send_json(*openai_chat(body))
                return
            if who[1] != 'admin':
                body['tier'] = 'local'                    # Claude is the operator's: user keys get the local model only
            self.stream_chat(body)
        finally:
            INFLIGHT.release()


# ---------- access keys from the command line ----------
def _key_lines():
    return ENV_PATH.read_text(encoding='utf-8').splitlines() if ENV_PATH.exists() else []


def _set_keys(var, pairs):
    lines, value = _key_lines(), ','.join('%s=%s' % p for p in pairs)
    for i, line in enumerate(lines):
        if line.split('=', 1)[0].strip() == var:
            lines[i] = '%s=%s' % (var, value)
            break
    else:
        lines.append('%s=%s' % (var, value))
    ENV_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _pairs(var):
    env = load_env(ENV_PATH)
    return [tuple(p.strip().split('=', 1)) for p in env.get(var, '').split(',') if '=' in p]


def new_key(name, admin):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', name or ''):
        sys.exit('key name: 1-32 letters, digits, _ . -')
    var = 'MABEMS_ADMIN_KEYS' if admin else 'MABEMS_USER_KEYS'
    for v, _ in KEY_VARS:                                 # one key per name across both lists
        if any(p[0] == name for p in _pairs(v)):
            _set_keys(v, [p for p in _pairs(v) if p[0] != name])
    key =('mba_' if admin else 'mbk_') + secrets.token_urlsafe(24)
    _set_keys(var, _pairs(var) + [(name, key)])
    print('%s key "%s" saved in %s' % ('admin' if admin else 'user', name, ENV_PATH))
    print('  key:        %s' % key)
    print('  share link: %s#key=%s' % (PUB['site'], key))
    print('Anyone with this link can use the assistant on the public site (%s). Revoke: --revoke %s'
          % ('local model + Claude' if admin else 'local model only', name))


def revoke_key(name):
    hit = False
    for var, _ in KEY_VARS:
        pairs = _pairs(var)
        if any(p[0] == name for p in pairs):
            _set_keys(var, [p for p in pairs if p[0] != name])
            hit = True
    print('revoked "%s"' % name if hit else 'no key named "%s"' % name)


def list_keys(show):
    for var, scope in KEY_VARS:
        for name, key in _pairs(var):
            shown = key if show else key[:8] + '...' + key[-4:]
            print('%-6s %-16s %s%s' % (scope, name, shown, ('   ' + PUB['site'] + '#key=' + key) if show else ''))
    if not show:
        print('(--show prints the full keys and share links)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=int(ENV.get('MABEMS_PORT', '5178')))
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--public-port', type=int, default=PUB['port'], help='public API port on 127.0.0.1 (0 = off)')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--new-key', metavar='NAME')
    ap.add_argument('--admin', action='store_true', help='with --new-key: the key may also use Claude')
    ap.add_argument('--revoke', metavar='NAME')
    ap.add_argument('--list-keys', action='store_true')
    ap.add_argument('--show', action='store_true')
    a = ap.parse_args()
    if a.new_key:
        return new_key(a.new_key, a.admin)
    if a.revoke:
        return revoke_key(a.revoke)
    if a.list_keys:
        return list_keys(a.show)
    if a.selftest:
        return selftest()
    st = status()
    print('MA-BEMS  http://%s:%d   local=%s (%s)   api=%s (%s)' % (a.host, a.port, st['local']['model'], 'up' if st['local']['alive'] else 'down',
                                                                 st['api']['model'], 'ready' if st['api']['available'] else st['api']['reason']), flush=True)
    if a.public_port:
        keys = list(access_keys().values())
        pub = ThreadingHTTPServer(('127.0.0.1', a.public_port), PublicHandler)   # loopback only: the tunnel is the way in
        threading.Thread(target=pub.serve_forever, daemon=True).start()
        print('public API  http://127.0.0.1:%d   keys: %d user, %d admin   origins: %s' % (
            a.public_port, sum(s == 'user' for _, s in keys), sum(s == 'admin' for _, s in keys), ', '.join(sorted(PUB['origins']))), flush=True)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


def selftest():
    print(json.dumps(status(), ensure_ascii=False, indent=1))
    ctx = json.dumps({'clock': '14:05', 'tou': 'peak', 'gridKW': 760, 'peakLimit': 1000, 'savingsPct': 16.5}, ensure_ascii=False)
    for tier in ('local', 'api'):
        print('\n== %s' % tier)
        events = []
        chat({'task': 'chat', 'tier': tier, 'context': ctx, 'messages': [{'role': 'user', 'content': '피크 여유가 얼마나 남았어? 한 문장으로.'}]},
             lambda ev, d: events.append((ev, d)))
        for ev, d in events:
            if ev != 'delta':
                print(ev, {k: v for k, v in d.items() if k != 'json'})


if __name__ == '__main__':
    main()
