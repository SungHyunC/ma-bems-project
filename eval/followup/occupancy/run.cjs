const assert = require('node:assert/strict');
const { mkdirSync, readFileSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');
const { simulate, repo } = require('../sim.cjs');

const output = join(__dirname, 'out');
const runDays = 9;
const minutesPerDay = 1440;
const mean = (values) => values.reduce((sum, value) => sum + value, 0) / values.length;

function smooth(start, end, value) {
  const t = Math.min(1, Math.max(0, (value - start) / (end - start)));
  return t * t * (3 - 2 * t);
}

function officeProfiles(stock) {
  const late = stock.map((_, i) => stock[(i - 4 * 60 + minutesPerDay) % minutesPerDay]);
  const lecture = stock.map((_, i) => {
    const hour = i / 60;
    const active = (start, finish) => smooth(start, start + 0.20, hour) * (1 - smooth(finish - 0.20, finish, hour));
    return 0.03 + 0.16 * active(8, 19.75) + 0.77 * (
      active(8.25, 10.20) + active(10.35, 12.30) + active(13.05, 15.05) + active(15.20, 17.20) + active(17.35, 19.50)
    );
  });
  const referenceMean = mean(stock);
  const scale = (referenceMean - 0.03) / (mean(lecture) - 0.03);
  const normalized = lecture.map((value) => 0.03 + (value - 0.03) * scale);
  assert(normalized.every((value) => value >= 0 && value <= 1), 'Lecture profile outside [0,1]');
  for (const profile of [late, normalized]) {
    assert(Math.abs(mean(profile) - referenceMean) < 1e-12, 'Mean daily occupancy input differs');
  }
  return { stock, lecture: normalized, late };
}

function summary(schedule, result, profile) {
  const days = result.days.filter((row) => row.day >= 2);
  const average = (mode, field) => mean(days.map((row) => row[mode][field]));
  const total = (mode, field) => days.reduce((sum, row) => sum + row[mode][field], 0);
  return {
    schedule,
    meanOccupancyInput: mean(profile),
    dailySavingMeanPct: mean(days.map(({ agent, baseline }) => 100 * (1 - agent.cost / baseline.cost))),
    meanDailyPeakAgentKW: average('agent', 'peakKW'),
    meanDailyPeakBaselineKW: average('baseline', 'peakKW'),
    overAgentMin: total('agent', 'minutesOverLimit'),
    overBaselineMin: total('baseline', 'minutesOverLimit'),
    comfortAgentPct: average('agent', 'comfortPct'),
    comfortBaselinePct: average('baseline', 'comfortPct'),
    officeMeanHeadcount: mean(result.officeHeadcounts.filter(({ minute }) => minute >= minutesPerDay && minute < runDays * minutesPerDay).map(({ people }) => people)),
  };
}

async function main() {
  const [baseline = 'basic', seed] = process.argv.slice(2);
  assert(['basic', 'expert'].includes(baseline), 'Choose basic or expert baseline');
  assert(seed === undefined || /^\d+$/.test(seed), 'Seed must be an unsigned integer');
  const params = new URLSearchParams();
  if (baseline === 'expert') params.set('baseline', baseline);
  if (seed !== undefined) params.set('seed', seed);
  const query = params.toString();
  const suffix = baseline + (seed === undefined ? '' : `_seed${seed}`);
  mkdirSync(output, { recursive: true });
  const control = await simulate(query, null, runDays, { captureOccupancy: true });
  const stock = control.officeProfile;
  const reference = summary('control', control, stock);
  const rows = [reference];
  for (const [schedule, profile] of Object.entries(officeProfiles(stock))) {
    const dataset = { name: schedule, source: 'MA-BEMS synthetic office schedules', stepMin: 1, startMin: 0, columns: { occ_office: profile } };
    const result = await simulate(query, dataset, runDays, { captureOccupancy: true });
    assert.equal(result.ds?.dataset, schedule);
    rows.push(summary(schedule, result, profile));
    writeFileSync(join(output, `${schedule}_${suffix}.json`), JSON.stringify({ dataset, days: result.days }));
  }
  assert(Math.abs(reference.dailySavingMeanPct - rows[1].dailySavingMeanPct) < 0.1, 'Loading the default office schedule shifted the reference by more than 0.1 percentage point');
  if (seed === undefined) {
    const path = baseline === 'expert' ? 'build/results/fb/expert.json' : 'build/results/full.json';
    const recorded = JSON.parse(readFileSync(join(repo, path), 'utf8'));
    const recordedMean = mean(recorded.days.filter((row) => row.day >= 2).map(({ agent, baseline }) => 100 * (1 - agent.cost / baseline.cost)));
    assert(Math.abs(reference.dailySavingMeanPct - recordedMean) < 0.001, 'Reference run differs from repository result');
  }
  writeFileSync(join(output, `summary_${suffix}.json`), JSON.stringify(rows, null, 2) + '\n');
  console.table(rows);
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
