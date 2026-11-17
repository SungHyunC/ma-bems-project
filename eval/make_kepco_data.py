"""Monthly simulator datasets for the year-round KEPCO evaluation (eval/README.md, "연중 요금·주말").

    python -I make_kepco_data.py        (in eval/; reads data/wx_sejong_2025_MM.json, writes data/kepco_2025_MM*.json)

Each month becomes a 15-min dataset: the month's real weather (linear interpolation of the hourly ERA5 values, exactly what
the simulator does between hourly rows), the KEPCO price for that 15-min point and a calendar.
  kepco_2025_MM.json          weekends and 2025 holidays: Saturday peak hours billed as mid-peak, Sundays and public
                              (incl. substitute) holidays all off-peak, temporary holidays (01-27, 06-03) as weekdays.
                              The simulator's calendar makes Saturdays, Sundays and all holidays off-days for occupancy.
  kepco_2025_MM_weekday.json  every day a weekday (no calendar), to separate the effect of weekends.
Tariff: 한전 일반용전력(을) 고압A 선택 II. Energy charges from KEPCO's table (2023-11-09; KEPCO's 2026 notice changes the
load periods of this class, not its energy charges). Load periods: March–October weekdays use the 2026-06-01 edition
(peak 15–21, mid 08–15 and 21–22), November–February keep the winter periods (peak 09–12 and 16–19, mid 08–09, 12–16 and
19–22); off-peak 22–08 all year.
"""
import calendar
import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / 'data'
RATES = {   # ₩/kWh: off, mid, peak
    'summer': {'off': 87.3, 'mid': 140.2, 'peak': 222.3},
    'spring_fall': {'off': 87.3, 'mid': 109.8, 'peak': 140.5},
    'winter': {'off': 94.3, 'mid': 140.4, 'peak': 197.9},
}
HOURS = {   # load periods (hours, [from, to))
    'warm': {'peak': [[15, 21]], 'mid': [[8, 15], [21, 22]]},             # March–October, 2026-06-01 edition
    'winter': {'peak': [[9, 12], [16, 19]], 'mid': [[8, 9], [12, 16], [19, 22]]},
}
HOLIDAYS = {   # 2025, 관공서의 공휴일 (substitute holidays included)
    '2025-01-01', '2025-01-28', '2025-01-29', '2025-01-30', '2025-03-01', '2025-03-03', '2025-05-05', '2025-05-06',
    '2025-06-06', '2025-08-15', '2025-10-03', '2025-10-05', '2025-10-06', '2025-10-07', '2025-10-08', '2025-10-09', '2025-12-25',
}
TEMP_HOLIDAYS = {'2025-01-27', '2025-06-03'}   # 임시공휴일: off-days on campus, weekdays for KEPCO metering


def season(month):
    return 'summer' if month in (6, 7, 8) else 'winter' if month in (11, 12, 1, 2) else 'spring_fall'


def day_code(d):
    s = d.isoformat()
    if s in TEMP_HOLIDAYS:
        return 3
    if s in HOLIDAYS or d.weekday() == 6:
        return 2
    if d.weekday() == 5:
        return 1
    return 0


def tier(hours, h):
    inr = lambda rs: any(a <= h < b for a, b in rs)
    return 'peak' if inr(hours['peak']) else 'mid' if inr(hours['mid']) else 'off'


def build(month, with_calendar):
    wx = json.loads((DATA / f'wx_sejong_2025_{month:02d}.json').read_text(encoding='utf-8'))
    nd = calendar.monthrange(2025, month)[1]
    hours = HOURS['winter' if season(month) == 'winter' else 'warm']
    rate = RATES[season(month)]
    cols = {k: wx['columns'][k] for k in ('tout', 'irr', 'wind')}
    n = nd * 96
    out = {k: [] for k in ('tout', 'irr', 'wind', 'price')}
    days = []
    for day in range(nd):
        d = dt.date(2025, month, day + 1)
        code = day_code(d) if with_calendar else 0
        days.append(code)
        for q in range(96):
            j = day * 96 + q
            x = j / 4.0
            i0 = int(x)
            f = x - i0
            for k, v in cols.items():
                a = v[i0]
                b = v[i0 + 1] if i0 + 1 < len(v) else v[i0]
                out[k].append(round(a + (b - a) * f, 2))
            t = tier(hours, q / 4.0)
            if code == 2:
                t = 'off'
            elif code == 1 and t == 'peak':
                t = 'mid'
            out['price'].append(rate[t])
    assert len(out['price']) == n
    ds = {
        'name': f'세종 2025-{month:02d} 기상 + 한전 계절 요금' + ('' if with_calendar else ' (모든 날 평일)'),
        'source': 'ERA5 (Open-Meteo) + 한전 일반용(을) 고압A 선택II, 15분',
        'currency': '₩', 'stepMin': 15, 'startMin': 0, 'columns': out, 'tou': hours,
    }
    if with_calendar:
        ds['calendar'] = {'start': f'2025-{month:02d}-01', 'days': days}
    return ds, days


def main():
    summary = []
    for month in range(1, 13):
        ds, days = build(month, True)
        (DATA / f'kepco_2025_{month:02d}.json').write_text(json.dumps(ds, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        dw, _ = build(month, False)
        (DATA / f'kepco_2025_{month:02d}_weekday.json').write_text(json.dumps(dw, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        summary.append({'month': month, 'season': season(month), 'weekdays': days.count(0), 'saturdays': days.count(1),
                        'sundaysHolidays': days.count(2), 'temporaryHolidays': days.count(3)})
    meta = {'tariff': '한전 일반용전력(을) 고압A 선택 II', 'energyChargesFrom': 'KEPCO 전기요금표 2023-11-09',
            'loadPeriods': {'march_october': HOURS['warm'], 'november_february': HOURS['winter'], 'off': [[22, 8]]},
            'ratesKRWperKWh': RATES, 'demandKRWperKWmonth': 8320,
            'weekendMetering': 'Saturday peak → mid; Sundays and public holidays off-peak all day; temporary holidays as weekdays',
            'holidays2025': sorted(HOLIDAYS), 'temporaryHolidays2025': sorted(TEMP_HOLIDAYS), 'months': summary}
    (DATA / 'kepco_2025_summary.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    for s in summary:
        print(s)


if __name__ == '__main__':
    main()
