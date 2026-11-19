const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { repo, simulate } = require('../sim.cjs');

const DAY_COUNT = 31;
const SLOTS_PER_DAY = 96;
const source = JSON.parse(readFileSync(join(repo, 'eval/data/kepco_2025_07.json'), 'utf8'));
assert.equal(source.calendar.days.length, DAY_COUNT);
const offPeak = Math.min(...source.columns.price);
const sides = ['agent', 'baseline'];
const physicalMetrics = ['energyKWh', 'peakKW', 'comfortPct', 'minutesOverLimit'];
const sum = (values) => values.reduce((total, value) => total + value, 0);
const mean = (values) => sum(values) / values.length;

function tariffAtScale(scale) {
  const price = source.columns.price.map((rate) => Number((offPeak + scale * (rate - offPeak)).toFixed(4)));
  return { ...source, columns: { ...source.columns, price } };
}

function summarize(run) {
  assert.equal(run.T, DAY_COUNT * 1440 + 1);
  const days = run.days.filter((day) => day.day >= 2);
  assert.equal(days.length, DAY_COUNT - 1);
  const bySide = (fn) => Object.fromEntries(sides.map((side) => [side, fn(side)]));
  const charge = bySide((side) => sum(days.map((day) => day[side].cost)));
  const summary = {
    charge_krw: charge,
    savings_percent: 100 * (1 - charge.agent / charge.baseline),
    daily_savings_mean_percent: mean(days.map((day) => 100 * (1 - day.agent.cost / day.baseline.cost))),
    grid_kwh: bySide((side) => sum(days.map((day) => day[side].energyKWh))),
    peak_15min_kw: bySide((side) => {
      const slots = run.s15[side === 'agent' ? 'a' : 'b'].slice(SLOTS_PER_DAY, DAY_COUNT * SLOTS_PER_DAY);
      assert.equal(slots.length, (DAY_COUNT - 1) * SLOTS_PER_DAY);
      return Math.max(...slots);
    }),
    comfort_percent: bySide((side) => mean(days.map((day) => day[side].comfortPct))),
  };
  return summary;
}

function distanceToReference(run, reference) {
  assert.equal(run.days.length, reference.days.length);
  for (const side of ['a', 'b']) assert.equal(run.s15[side].length, reference.s15[side].length);
  return {
    daily_cost_max_absolute_krw: Math.max(...run.days.flatMap((day, i) => (
      sides.map((side) => Math.abs(day[side].cost - reference.days[i][side].cost))
    ))),
    peak_15min_max_absolute_kw: Math.max(...['a', 'b'].flatMap((side) => (
      run.s15[side].map((value, i) => Math.abs(value - reference.s15[side][i]))
    ))),
  };
}

function comparePhysicalResults(run, originalTariff) {
  const fields = (result) => result.days.map((day) => (
    sides.map((side) => physicalMetrics.map((metric) => day[side][metric]))
  ));
  assert.deepEqual(run.s15, originalTariff.s15);
  assert.deepEqual(fields(run), fields(originalTariff));
}

async function main() {
  const data = {};
  for (const baseline of ['basic', 'expert']) {
    const query = `heat=1${baseline === 'expert' ? '&baseline=expert' : ''}`;
    const originalTariff = await simulate(query, tariffAtScale(1), DAY_COUNT);
    const reference = JSON.parse(readFileSync(join(repo, `build/results/fb/kc_07_${baseline}.json`), 'utf8'));
    const distance = distanceToReference(originalTariff, reference);
    assert(distance.daily_cost_max_absolute_krw < 1, 'Daily charge differs from the stored result by at least 1 won');
    assert(distance.peak_15min_max_absolute_kw < 0.2, '15-minute demand differs from the stored result by at least 0.2 kW');
    for (const scale of [0.8, 1, 1.2]) {
      const run = scale === 1 ? originalTariff : await simulate(query, tariffAtScale(scale), DAY_COUNT);
      assert.equal(run.ds.dataset, source.name);
      const summary = summarize(run);
      if (scale === 1) {
        summary.reference_distance = distance;
      } else {
        comparePhysicalResults(run, originalTariff);
      }
      data[`07_${baseline}_${scale}`] = summary;
    }
  }
  console.log(JSON.stringify(data, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
