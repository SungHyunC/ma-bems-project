import csv
import json
from pathlib import Path
from statistics import mean

root = Path(__file__).resolve().parent

def scored(run):
    return [d for d in run['days'] if d['day'] >= 2]

tables = {}
rows = []
for file in sorted((root / 'out').glob('*.json')):
    run = json.loads(file.read_text())
    conditions = file.stem.split('_', 1)[0]
    tables.setdefault(conditions, {})
    days = scored(run)
    assert len(days) == 8
    agent = [d['agent'] for d in days]
    baseline = [d['baseline'] for d in days]
    if conditions not in tables or 'baseline' not in tables[conditions]:
        tables[conditions]['baseline'] = baseline
    else:
        assert tables[conditions]['baseline'] == baseline, 'Inputs must be paired'
    row = {
        'case': file.stem, 'query': run['query'], 'days_scored': len(days),
        'switched_functions': ','.join(run['ablation']),
        'peak_limit_kw': run['peakLimit'],
        'mean_daily_cost_saving_pct': round(mean(100*(1-a['cost']/b['cost']) for a,b in zip(agent,baseline)), 4),
        'mean_daily_peak_kw': round(mean(a['peakKW'] for a in agent), 2),
        'hours_over_limit': round(sum(a['minutesOverLimit'] for a in agent)/60, 3),
        'minutes_over_limit': sum(a['minutesOverLimit'] for a in agent),
        'kwh_over_limit': round(sum(a['overLimitKWh'] for a in agent), 2),
        'comfort_pct': round(mean(a['comfortPct'] for a in agent), 3),
        'ev_met_pct': round(mean(a['evMetPct'] for a in agent), 3),
    }
    rows.append(row)
assert rows, 'Run the ablation experiments first'
with (root / 'out' / 'summary.csv').open('w', newline='') as out:
    writer = csv.DictWriter(out, list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
for row in rows:
    print(row)
