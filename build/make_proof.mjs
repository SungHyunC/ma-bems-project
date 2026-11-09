// node make_proof.mjs → proof_module.js (the Insights "검증·근거" tab) with PROOF filled from results/*.json
import { readFileSync, writeFileSync } from 'node:fs';
const J = (n) => JSON.parse(readFileSync(`results/${n}.json`, 'utf8'));
const S = J('summary'), llm = J('llm');
const r1 = (x) => Math.round(x * 10) / 10, r2 = (x) => Math.round(x * 100) / 100, r3 = (x) => Math.round(x * 1000) / 1000;
const ci = (c) => ({ mean: +c.mean.toFixed(4), ci: +c.ci.toFixed(4) });   // full precision: the page rounds once
const kp = (k) => ({ costSave: ci(k.costSave), energySave: ci(k.energySave), peakCut: ci(k.peakCut), peakA: r2(k.peakA), peakB: r2(k.peakB), limit: k.limit,
  overMinA: k.overMinA, overMinB: k.overMinB, comfortA: r2(k.comfortA), comfortB: r2(k.comfortB), co2Save: ci(k.co2Save), drA: k.drA && r1(k.drA), drB: k.drB && r1(k.drB) });
const over = (n) => J(n).days.filter((d) => d.day >= 2).reduce((s, d) => s + d.agent.overLimitKWh, 0);
const limits = [900, 850, 800].map((L) => ({ limit: L, full: Math.round(over(`lim${L}_full`)), coord: Math.round(over(`lim${L}_coord`)) }));

// AI assistant: per-task latency / tokens / cost (Opus 5.5: $4 in, $20 out, $0.20 cache read, cache write 1.25 × input)
const usd = (u) => ((u.input_tokens || 0) * 4 + (u.output_tokens || 0) * 20 + (u.cache_read_tokens || 0) * 0.2 + (u.cache_write_tokens || 0) * 5) / 1e6;
const row = (task, tier) => llm.rows.find((r) => r.task === task && r.tier === tier && !r.note);
const lab = { brief: ['Briefing', '운영 브리핑'], chat: ['Question (peak risk)', '질문 (피크 위험)'], explain: ['Explain selection', '선택 대상 설명'], propose: ['Control proposals (JSON)', '제어 제안 (JSON)'] };
const fmtL = (r) => `${r1(r.latencyMs / 1000)} s · ${r.usage.input_tokens.toLocaleString()} / ${r.usage.output_tokens.toLocaleString()} tok`;
const apiRows = ['brief', 'chat', 'explain', 'propose'].map((t) => row(t, 'api'));
const usdPerQ = apiRows.reduce((s, r) => s + usd(r.usage), 0) / apiRows.length;
const rows = ['brief', 'chat', 'explain', 'propose'].map((t) => { const L = row(t, 'local'), A = row(t, 'api');
  return { labelEn: lab[t][0], labelKo: lab[t][1], local: fmtL(L) + (L.actions ? ` · ${L.actions.filter((a) => a.valid).length}/${L.actions.length} ✓` : ''), api: `${fmtL(A)} · $${usd(A.usage).toFixed(3)}` }; });
const rep = llm.rows.find((r) => r.note && r.note.startsWith('repeat'));
const month = (perDay, share) => r1(perDay * 30 * share * usdPerQ);
const P = {
  date: '2026-11-09', days: 8, K: Object.fromEntries(['full', 'tuned', 'kepco', 'bdg2'].map((n) => [n, kp(S.K[n])])),
  abl: Object.fromEntries(Object.entries(S.abl).map(([k, c]) => [k, ci(c)])), limits,
  forecast: { model: { cvrmse: +S.forecast.model.cvrmse.toFixed(4), nmbe: +S.forecast.model.nmbe.toFixed(4), n: S.forecast.model.n }, persistence: { cvrmse: +S.forecast.persistence.cvrmse.toFixed(4) }, skill: r3(S.forecast.skill), dailyCV: ci(S.forecast.dailyCV) },
  fdd: S.fdd,
  llm: { rows, usdPerQ: r3(usdPerQ), cacheRepeatUsd: r3(usd(rep.usage)),
    localNote: `${r1(Math.min(...['brief', 'chat', 'explain', 'propose'].map((t) => row(t, 'local').latencyMs)) / 1000)}–${r1(Math.max(...['brief', 'chat', 'explain', 'propose'].map((t) => row(t, 'local').latencyMs)) / 1000)} s per answer and the data never leaves the PC`,
    localNoteKo: `답변당 ${r1(Math.min(...['brief', 'chat', 'explain', 'propose'].map((t) => row(t, 'local').latencyMs)) / 1000)}~${r1(Math.max(...['brief', 'chat', 'explain', 'propose'].map((t) => row(t, 'local').latencyMs)) / 1000)}초, 데이터가 PC 밖으로 나가지 않음`,
    monthlyEn: `50 questions a day all on Claude ≈ $${month(50, 1)} a month; with the default local-first routing (only ~5 proposals a day on Claude) ≈ $${month(5, 1)}`,
    monthlyKo: `하루 50건을 모두 Claude로 보내면 월 약 $${month(50, 1)}, 기본 설정(로컬 우선, 제안 하루 5건만 Claude)이면 월 약 $${month(5, 1)}` },
  refs: [
    { t: 'FEMP M&V Guidelines 4.0 — ASHRAE Guideline 14 calibration criteria (CV(RMSE), NMBE) and IPMVP options', url: 'https://www.energy.gov/sites/prod/files/2016/01/f28/mv_guide_4_0.pdf' },
    { t: 'EVO — International Performance Measurement and Verification Protocol (IPMVP) core concepts', url: 'https://evo-world.org/images/denisdocuments/Core-TOC.pdf' },
    { t: 'BOPTEST — core KPIs for building control benchmarking (Blum et al., J. Building Performance Simulation, 2021)', url: 'https://ibpsa.github.io/project1-boptest/docs-design/core_kpi.html' },
    { t: 'CityLearn — KPI reference for grid-interactive building control', url: 'https://www.citylearn.net/guides/kpis_reference.html' },
    { t: 'US DOE — Smart Energy Analytics Campaign: continued energy and cost savings (LBNL)', url: 'https://www.energy.gov/cmei/buildings/articles/smart-energy-analytics-campaign-reveals-continued-energy-and-cost-savings' },
    { t: 'PNNL — advanced building controls could cut commercial energy use by 29 %', url: 'https://www.eurekalert.org/news-releases/738293' },
    { t: 'From theory to practice: a critical review of model predictive control field implementations', url: 'https://pure.etsmtl.ca/en/publications/from-theory-to-practice-a-critical-review-of-model-predictive-con' },
    { t: 'OWASP Top 10 for LLM Applications 2025 — LLM06 Excessive Agency', url: 'https://genai.owasp.org/llmrisk/llm062025-excessive-agency/' },
    { t: 'OWASP Top 10 for LLM Applications 2025 — LLM09 Misinformation', url: 'https://genai.owasp.org/llmrisk/llm092025-misinformation/' },
    { t: 'CISA et al. — Principles for the secure integration of AI in operational technology', url: 'https://www.cisa.gov/resources-tools/resources/principles-secure-integration-artificial-intelligence-operational-technology' },
    { t: "South Korea's AI Basic Act (in force 2026-01-22): overview incl. Art. 31 transparency", url: 'https://www.cooley.com/news/insight/2026/2026-01-27-south-koreas-ai-basic-act-overview-and-key-takeaways' },
    { t: 'Building Data Genome 2 — measured meter data used for the BDG2 + KEPCO run', url: 'https://github.com/buds-lab/building-data-genome-project-2' },
    { t: 'KEPCO 2026 time-of-use reform (peak moves to 15–21 h)', url: 'https://mobile.newsis.com/view/NISX20260313_0003547625' },
  ],
};
const tpl = readFileSync('proof_template.js', 'utf8');
writeFileSync('proof_module.js', tpl.replace('__PROOF_DATA__', JSON.stringify(P)));
writeFileSync('results/proof_data.json', JSON.stringify(P, null, 1));
console.log('proof_module.js written', { usdPerQ: P.llm.usdPerQ, repeat: P.llm.cacheRepeatUsd, limits, monthly: P.llm.monthlyKo });
