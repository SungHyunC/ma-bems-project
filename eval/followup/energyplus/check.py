"""Compare the MA-BEMS room-envelope decay with a synthetic EnergyPlus zone."""
import argparse
import csv
import json
import math
from pathlib import Path
import re
import subprocess


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2] / 'index.html'
VOLUME = 15.24 * 15.24 * 4.572
TAU_MIN = 280
OUTDOOR_C = 25
NOON_ROW = 719


def column(row, name):
    return float(next(value for key, value in row.items() if name in key))


def check(energyplus, output):
    source = SOURCE.read_text(encoding='utf-8')
    recurrence = re.search(r'const leak = \(env\.tout - S\.Ta\) / (\d+) \* MODEL_X\.leak;', source)
    if (not recurrence or int(recurrence.group(1)) != TAU_MIN
            or 'S.Ta += leak + gInt + gSol - q;' not in source):
        raise ValueError('The room temperature update changed. Review the EnergyPlus fixture before comparing.')

    output.mkdir(parents=True, exist_ok=True)
    run = subprocess.run([energyplus, '-D', '-d', str(output), str(HERE / 'zone.idf')],
                         capture_output=True, text=True)
    (output / 'run.log').write_text(run.stdout + run.stderr, encoding='utf-8')
    if run.returncode:
        raise RuntimeError(f'EnergyPlus exited with code {run.returncode}. See {output / "run.log"} and eplusout.err.')
    with (output / 'eplusout.csv').open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1440 or column(rows[NOON_ROW], 'Convective Heating Rate') != 750:
        raise ValueError('Expected one 1-minute design day and the end of a 750 W pulse at noon.')

    initial = column(rows[NOON_ROW], 'Zone Mean Air Temperature')
    room = initial
    values = []
    for minute, row in enumerate(rows[NOON_ROW + 1:], 1):
        if column(row, 'Convective Heating Rate') != 0 or column(row, 'Site Outdoor Air Drybulb Temperature') != OUTDOOR_C:
            raise ValueError(f'Unexpected heating or outdoor temperature at minute {minute} after noon.')
        room += (OUTDOOR_C - room) / TAU_MIN
        simulated = column(row, 'Zone Mean Air Temperature')
        values.append([minute, simulated, room, abs(simulated - room)])

    with (output / 'cooldown.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['minute_after_pulse', 'energyplus_C', 'ma_bems_leak_recurrence_C', 'absolute_error_C'])
        writer.writerows(values)
    return {
        'engine': subprocess.check_output([energyplus, '--version'], text=True).strip(),
        'comparison_minutes': len(values),
        'tau_min': TAU_MIN,
        'zone_m3': VOLUME,
        'airflow_m3_s': VOLUME / (60 * TAU_MIN),
        'initial_zone_C': initial,
        'outdoor_C': OUTDOOR_C,
        'rmse_C': math.sqrt(sum(row[3] ** 2 for row in values) / len(values)),
        'max_abs_error_C': max(row[3] for row in values),
        'snapshots': {row[0]: row[1:3] for row in values if row[0] in (60, 180, 280, 720)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--energyplus', default='energyplus', help='EnergyPlus 26.2.0 executable or path')
    parser.add_argument('--output', type=Path, default=HERE / 'runs', help='Directory for simulation output')
    args = parser.parse_args()
    result = check(args.energyplus, args.output.resolve())
    serialized = json.dumps(result, indent=2) + '\n'
    (args.output / 'summary.json').write_text(serialized, encoding='utf-8')
    print(serialized, end='')


if __name__ == '__main__':
    main()
