// Run the project's browser simulator and evaluation loop headlessly, using local code only.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join, resolve } = require('node:path');

const repo = resolve(__dirname, '../..');
const html = readFileSync(join(repo, 'index.html'), 'utf8');
const evaluator = readFileSync(join(repo, 'eval/exp.mjs'), 'utf8');

function extract(text, start, end) {
  const from = text.indexOf(start);
  const to = text.indexOf(end, from + start.length);
  assert(from >= 0 && to > from, `Simulator source block not found: ${start}`);
  return text.slice(from, to);
}

const core = extract(html, 'function createBus()', '/* =====================================================================\n   SECTION 2 — 3D WORLD');
const fdd = extract(html, '/* MA-FDD:BEGIN */', '/* MA-FDD:END */');
const loop = extract(evaluator, 'const page = `', '\nconst r = await send');

const browserStubs = `
const window = {};
const LANG = 'ko';
const document = {
  querySelector() { return null; },
  getElementById(id) { return id === 'side' ? { addEventListener() {} } : null; },
};
function i18nAdd() {}
function onFrame() {}
function renderChart() {}
function renderSide() {}
function renderAlerts() {}
// The browser loop yields every 120 steps. Node can use a one-shot callback.
class MessageChannel {
  port1 = {};
  port2 = { postMessage: () => setImmediate(this.port1.onmessage) };
}
`;
const initialize = `
let lastSnap;
Bus.on('tick', (s) => { lastSnap = s; });
const MA_BEMS = { Sim, Bus, get snapshot() { return lastSnap; } };
window.MA_BEMS = MA_BEMS;
Sim.command({ type: 'lang', value: LANG });
Sim.start(30);
Sim.command({ type: 'speed', value: 0 });
const officeHeadcounts = [];
if (captureOccupancy) {
  Bus.on('tick', (s) => {
    if (s.T % 60 === 0 && officeHeadcounts.at(-1)?.minute !== s.T) {
      officeHeadcounts.push({ minute: s.T, people: s.buildings.B1.people });
    }
  });
}
`;
const run = new Function('location', 'name', 'query', 'P', 'DS', 'captureOccupancy',
  '"use strict";\n' + browserStubs + core + fdd + initialize + loop + `
return eval(page).then((result) => {
  if (captureOccupancy) {
    result.officeHeadcounts = officeHeadcounts;
    result.officeProfile = Array.from({ length: 1440 }, (_, i) => occupancy('office', i / 60));
  }
  return result;
});`);

async function simulate(query = '', dataset = null, days = 9, { captureOccupancy = false } = {}) {
  const location = { search: '?lang=ko&t=0.5&speed=0' + (query ? '&' + query : '') };
  const parameters = { days, dataset: dataset?.name ?? '', drill: 0, seed: 11 };
  const result = await run(location, '', query, parameters, JSON.stringify(dataset), captureOccupancy);
  assert(!result.error, result.error);
  assert.equal(result.T, days * 1440 + 1);
  assert.equal(result.days.filter((day) => day.day >= 2).length, days - 1);
  return result;
}

module.exports = { simulate, repo };
