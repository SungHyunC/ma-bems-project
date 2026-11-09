"""Local proposals: current schema vs a per-request schema whose target/value enums come from the context."""
import json, sys, time, urllib.request
sys.path.insert(0, r'C:\Users\sunghyun\Desktop\MA-BEMS\server')
import mabems_server as m

ctx = open(sys.argv[1], encoding='utf-8').read().strip()
c = json.loads(ctx)
zones = [z['id'] for z in c['candidateZones']]
rooms = [r['id'] for r in c['candidateRooms'] if r.get('setpointC', 20) > 10]     # leave out 4 °C cold rooms
temps = ['%g' % (22 + 0.5 * i) for i in range(13)]

def act(kind, targets, values):
    return {'type': 'object', 'properties': {'type': {'type': 'string', 'enum': [kind]}, 'target': {'type': 'string', 'enum': targets},
            'value': {'type': 'string', 'enum': values}, 'expected_effect': {'type': 'string'}, 'reason': {'type': 'string'}},
            'required': ['type', 'target', 'value', 'expected_effect', 'reason'], 'additionalProperties': False}

DYN = {'type': 'object', 'properties': {'summary': {'type': 'string'}, 'actions': {'type': 'array', 'maxItems': 4, 'items': {'anyOf': [
       act('setpoint', zones, temps), act('roomSetpoint', rooms, temps + ['null']), act('roomLights', rooms, ['auto', 'on', 'off'])]}}},
       'required': ['summary', 'actions'], 'additionalProperties': False}

def valid(a):
    t, tg, v = a.get('type'), a.get('target'), str(a.get('value'))
    if t == 'setpoint': return tg in zones and v in temps
    if t == 'roomSetpoint': return tg in rooms and v in temps + ['null']
    if t == 'roomLights': return tg in rooms and v in ('auto', 'on', 'off')
    return False

system = m.SYSTEM_BASE + m.TASKS['propose']['note']
msgs = [{'role': 'system', 'content': system}, {'role': 'user', 'content': '<campus_state>\n' + ctx + '\n</campus_state>\n\n앞으로 1시간 동안의 제어 조치를 제안해 줘.'}]
for label, schema in (('current', m.PROPOSAL_SCHEMA), ('enum', DYN)):
    ok = tot = 0; secs = []
    for run in range(4):
        payload = {'model': m.CFG['local_model'], 'stream': False, 'think': False, 'keep_alive': '30m', 'messages': msgs, 'format': schema,
                   'options': {'temperature': 0.3, 'num_predict': 900}}
        t0 = time.time()
        req = urllib.request.Request(m.CFG['local_base'] + '/api/chat', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        out = json.loads(urllib.request.urlopen(req, timeout=120).read())
        secs.append(time.time() - t0)
        acts = json.loads(out['message']['content'])['actions']
        ok += sum(valid(a) for a in acts); tot += len(acts)
        if label == 'enum' and run < 2:
            for a in acts: print('   ', a['type'], a['target'], a['value'], '|', a['reason'][:60].encode('unicode_escape').decode()[:0] or '')
    print('%-8s valid actions %2d / %2d   avg %.1fs' % (label, ok, tot, sum(secs) / len(secs)))
