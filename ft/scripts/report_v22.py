"""Key metrics per held-out set from the v2.2 evaluation summary (modal_ft.py::evaluate --out).

    python ft/scripts/report_v22.py ft/out/eval_v22_summary.json [--md]
"""
import json
import sys

ROWS = [  # (set, label, path into the summary, lower is better)
    ('eval22_chat', 'number check %', ('text', 'number_check_pct'), False),
    ('eval22_chat', 'format %', ('text', 'format_pct'), False),
    ('eval22_chat', 'key-number recall %', ('text', 'key_number_recall_pct'), False),
    ('eval22_chat', 'stray numbers / answer', ('text', 'stray_numbers_per_answer'), True),
    ('eval22_chat', 'refusal on unanswerable %', ('text', 'refusal_pct'), False),
    ('eval22_chat', 'over-refusal %', ('text', 'over_refusal_pct'), True),
    ('eval22_chat', 'one-sentence %', ('text', 'one_sentence_pct'), False),
    ('eval22_chat', 'off-topic without numbers %', ('text', 'offtopic_ok_pct'), False),
    ('eval22_chat', 'concept uses glossary %', ('text', 'concept_ok_pct'), False),
    ('eval22_tasks', 'brief/explain number check %', ('text', 'number_check_pct'), False),
    ('eval22_tasks', 'brief/explain format %', ('text', 'format_pct'), False),
    ('eval22_tasks', 'proposal P/R value-aware %', ('propose', ('precision_value_pct', 'recall_value_pct')), False),
    ('eval22_tasks', 'after filter P/R value-aware %', ('propose_gateway', ('precision_value_pct', 'recall_value_pct')), False),
    ('eval22_tasks', 'no-op actions (gateway rule)', ('propose', ('noop_actions_gateway_rule', 'actions')), True),
    ('eval22_nothing', 'nothing to change, model only %', ('propose_by_kind', 'propose-quiet', 'nothing_to_do_ok_pct'), False),
    ('eval22_nothing', 'no-op actions, model only', ('propose_by_kind', 'propose-quiet', ('noop_actions_gateway_rule', 'actions')), True),
    ('eval22_nothing', 'one-room cases P/R value-aware %', ('propose_by_kind', 'propose-single', ('precision_value_pct', 'recall_value_pct')), False),
    ('eval22_request', 'typed requests P/R value-aware %', ('propose', ('precision_value_pct', 'recall_value_pct')), False),
    ('eval22_request', 'after filter P/R value-aware %', ('propose_gateway', ('precision_value_pct', 'recall_value_pct')), False),
    ('eval', 'v1 set: number check %', ('text', 'number_check_pct'), False),
    ('eval', 'v1 set: format %', ('text', 'format_pct'), False),
    ('eval', 'v1 set: key-number recall %', ('text', 'key_number_recall_pct'), False),
    ('eval', 'v1 set: proposal P/R value-aware %', ('propose', ('precision_value_pct', 'recall_value_pct')), False),
    ('eval', 'v1 set: after filter P/R %', ('propose_gateway', ('precision_value_pct', 'recall_value_pct')), False),
    ('eval_nothing', 'v2 nothing set, model only %', ('propose', 'nothing_to_do_ok_pct'), False),
    ('realq', 'real questions: checks pass %', ('pass_pct',), False),
    ('realq', 'real questions: number check %', ('number_check_pct',), False),
]


def get(d, path):
    for k in path[:-1]:
        d = (d or {}).get(k)
    last = path[-1]
    if isinstance(last, tuple):
        vals = [(d or {}).get(x) for x in last]
        return None if any(v is None for v in vals) else '/'.join(('%g' % v) for v in vals)
    v = (d or {}).get(last)
    return None if v is None else ('%g' % v)


def main():
    res = json.load(open(sys.argv[1], encoding='utf-8'))
    models = list(res)
    md = '--md' in sys.argv
    if md:
        print('| set | metric | ' + ' | '.join(models) + ' |')
        print('|---|---|' + '---|' * len(models))
    for s, label, path, _ in ROWS:
        vals = [get(res[m].get(s), path) for m in models]
        if all(v is None for v in vals):
            continue
        if md:
            print('| %s | %s | %s |' % (s, label, ' | '.join(v or '–' for v in vals)))
        else:
            print('%-15s %-36s %s' % (s, label, '  '.join('%12s' % (v or '-') for v in vals)))


if __name__ == '__main__':
    main()
