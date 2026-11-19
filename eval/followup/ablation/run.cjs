const assert = require('node:assert/strict');
const { mkdirSync, readFileSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');
const { repo, simulate } = require('../sim.cjs');

const cases = [
  ['normal_full', '', 'full'],
  ['normal_light_ev', 'ablate=LIGHT,EV'],
  ['normal_coord_light_ev', 'ablate=COORD,LIGHT,EV'],
  ['normal_ess_light_ev', 'ablate=ESS,LIGHT,EV'],
  ['tight_full', 'limit=850', 'lim850_full'],
  ['tight_coord', 'limit=850&ablate=COORD', 'lim850_coord'],
  ['tight_light_ev', 'limit=850&ablate=LIGHT,EV'],
  ['tight_coord_light_ev', 'limit=850&ablate=COORD,LIGHT,EV'],
  ['tight_ess_light_ev', 'limit=850&ablate=ESS,LIGHT,EV'],
  ['evrush_full', 'scn=evrush', 'scn_evrush'],
  ['evrush_light_ev', 'scn=evrush&ablate=LIGHT,EV'],
];
const out = join(__dirname, 'out');

function assertEquivalent(actual, expected, key = '') {
  if (typeof actual === 'number') {
    assert(Math.abs(actual - expected) <= 1e-7, `${key}: ${actual} differs from ${expected}`);
  } else if (actual && typeof actual === 'object') {
    assert.deepEqual(Object.keys(actual), Object.keys(expected));
    for (const field of Object.keys(actual)) assertEquivalent(actual[field], expected[field], `${key}.${field}`);
  } else {
    assert.equal(actual, expected);
  }
}

async function main() {
  const filter = process.argv[2] || '';
  const selected = cases.filter(([name]) => name.startsWith(filter));
  assert(selected.length > 0, `Unknown case prefix: ${filter}`);
  mkdirSync(out, { recursive: true });
  for (const [name, query, reference] of selected) {
    const run = await simulate(query);
    assert.deepEqual(run.ablation, new URLSearchParams(query).get('ablate')?.split(',') ?? []);
    if (reference) {
      const recorded = JSON.parse(readFileSync(join(repo, 'build/results', `${reference}.json`), 'utf8'));
      assertEquivalent(run.days, recorded.days);
    }
    const { days, ablation, peakLimit } = run;
    writeFileSync(join(out, `${name}.json`), JSON.stringify({ name, query, days, ablation, peakLimit }));
    console.log(name, reference ? `matches ${reference}` : 'finished');
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
