# MA-BEMS: Multi-Agent Building Energy Management

**Six cooperating agents run a simulated campus every 15 minutes, with a coordinator that settles conflicts by priority, next to a rule-based BMS fed the same weather, occupancy and EV arrivals, so the difference in cost, peak demand and comfort can be measured directly. A fine-tuned local LLM explains the agents' decisions and proposes control actions.**

English · [한국어](README.ko.md) · [Live dashboard](https://sunghyunc.github.io/ma-bems/) · [Evaluation](eval/README.md) · [Fine-tuning](ft/README.md)

Capstone design project at Korea University Sejong Campus, fall 2026, entered in the Industry-Linked Capstone Design Competition (results pending). It follows [Multi-Agent BEMS](https://github.com/SungHyunC/multi-agent-bems), the spring 2026 capstone that won the Excellence Award; the answer number check in `server/numcheck.py` was ported from that project.

![The MA-BEMS dashboard: a 3D campus with KPI cards, campus details, the agent decision log and the six agents' status](docs/dashboard.webp)

**Demo video** (2:54, Korean narration and subtitles): [1080p](https://github.com/SungHyunC/ma-bems-project/releases/download/demo-2026-11-11/ma-bems-demo-ko.mp4) · [720p](https://github.com/SungHyunC/ma-bems-project/releases/download/demo-2026-11-11/ma-bems-demo-ko-720p.mp4). It was recorded by driving the live dashboard, and the AI answers in it were generated on the spot by the local model. A 10-page project overview (Korean) is in [docs/ma-bems-overview-ko.pdf](docs/ma-bems-overview-ko.pdf).

## Results

Counterfactual shadow run (IPMVP Option D style): the agents and a rule-based BMS run at the same time on identical inputs. Each setting runs 9 simulated days at 1-minute steps. Day 0 is warm-up, and days 1–8 are scored. Scripts and raw results are in [`eval/`](eval/README.md).

How to read the ±: in a single run the inputs are fixed, so "± 0.2" is the 95% t-interval over that run's 8 daily values, i.e. day-to-day variation only. The proper interval for "would it hold with different inputs" is the one across 10 seeded runs (`?seed=N` re-draws occupancy, EV sessions and DR timing and adds day-to-day weather), where each run counts once.

| Metric | Agents vs. rule-based BMS |
|---|---|
| Energy cost savings, default BMS | **16.7 ± 0.2%** (one run, ± = day-to-day variation of its 8 days). **16.5 ± 0.2%** over 10 seeds (95% CI across runs) |
| Tuned BMS (adds ESS peak control) | 16.6 ± 0.4%. It costs almost the same as the default BMS and its mean peak is slightly higher (1,176 vs. 1,170 kW), so it is not a stronger baseline in cost terms |
| Sensor BMS (the agents' occupancy sensing, ESS peak control and a fixed DR response) | **9.7 ± 0.3%** (10 seeds: 10.2 ± 0.2%). That BMS's comfort drops to 97.0% (10 seeds: 97.4%). With `dr=off` the saving vs. the default BMS is 14.4%, so DR non-response explains about 2.3 points of the 16.7% |
| Peak demand | Mean of the daily maxima: 959 vs. 1,170 kW (maximum over the period: about 960 vs. 1,210 kW). 10 seeds: 981 vs. 1,193 kW. Over 8 days: 0 vs. 1,996 minutes above the 1,000 kW limit |
| Comfort compliance | 99.9% vs. 100% (10 seeds: 99.7 vs. 99.9%) |
| Grid-import forecast, 1 hour ahead, no future weather | CV(RMSE) 8.0%, NMBE 0.1% (n = 766 forecasts). Same-time-yesterday: 9.0%; one-hour persistence: 14.1%. Over 10 seeds: 8.0 / 9.9 / 12.9%. ASHRAE Guideline 14's 30% is a calibration criterion for energy models, so it is a point of comparison here, not a forecasting standard the result is "within" |
| Sensor fault detection | 0 false alarms in 1,206 room-days of normal operation (default inputs). Over the 25 committed no-fault runs with default inputs: 6 in 30,150 room-days. With 0.3 °C sensor noise: 1 in 1,206, and the drill still catches 63 of 64 injected faults. The drill assumes an operator who knows which alarms are real. With weather variation (10 seeds) there were 34 false alarms in 12,060 room-days (14 of them in one seed) |
| Demand charge (KEPCO 8,320 KRW per kW-month on the period maximum) | Not in the default cost. Adding it: KEPCO tariff on the modelled load 14.9 → 15.5%; BDG2 load shape 14.6 → 15.6%. There is no USD rate in the repository, so the dollar runs take it as a parameter |

BDG2 here is one measured summer weekday of non-HVAC electricity from four buildings of a US campus, rescaled to the Helio Campus and repeated every day. It is not measured load of this campus.

- **Ablations** show where the savings come from (percentage points): room-level control 12.3, ESS 3.2, HVAC 2.2, lighting 0.7, EV 0.0. The coordinator (version 1) settles conflicting plans by priority; it adds nothing in the default case (−0.15). Its value shows under tight limits: over-limit energy is cut by 13% at 900 kW (482 → 417 kWh), 21% at 850 kW (2,129 → 1,675 kWh) and 9% at 800 kW (5,083 → 4,610 kWh).
- **Coordinator v2 (`?coord=v2`, optional; the default stays v1).** It gives DR notice with a battery reserve and staged recovery, forecast-aware ESS water-filling, and cost-based allocation over up to 3 rounds. Against v1: normal day 16.7 → 17.4% saving; combined worst day 9.8 → 15.9% saving and mean peak 1,512 → 1,299 kW (now below the BMS's 1,454); 850 kW limit over-limit energy 1,675 → 392 kWh; 800 kW limit period maximum 1,157 → 950 kW; over 10 seeds +0.4 ± 0.1 points of saving and −66 ± 26 kW of period maximum. It is worse in two ways: minutes above the limit rise (heat wave +61%, worst day +50%, 800 kW +88%), and the saving at the 850 kW limit falls by 0.6 points. Whether v2 should become the default is open.
- **Nine scenarios** (heat wave, cloudy day, demand response, tighter limit, EV rush, holiday, stuck sensor, worst day) are reported separately. On the combined worst day, v1's mean peak is *higher* than the BMS's (1,512 vs. 1,454 kW): the battery is spent on peak shaving and runs out around 14:00, and cooling rebounds after the DR event. v2 addresses this (above). Details: [eval/README.md](eval/README.md).
- **Energy impact of sensor faults** (`?faultImpact=1`, 9 simulated days, an operator who approves real alarms): a drift fault adds 1,285 kWh with fault detection off and 27 kWh with it on; the every-3-hours fault drill adds 12,387 kWh with detection off (49 faults injected) vs. 1,572 kWh with it on (63 injected), so read it as a direction, not a like-for-like ratio. Limits: the virtual sensor has no feedback, so an unattended stuck sensor saves 404 kWh but adds 1,963 °C·h of discomfort; in the closed loop, drift detection slows from 55 to 245 minutes (median) and the drill raises 55 false alarms.

All results come from simulation. The savings have not been calibrated against metered data.

## How it works

```
Browser (GitHub Pages)                       Operator PC
index.html  ── AI tab ── HTTPS + access key ──> Cloudflare Quick Tunnel ──> LLM gateway (server/)
  simulation, 6 agents, forecast,                                           ├─ Qwen3-8B, fine-tuned (Ollama)
  fault detection, shadow BMS                                               └─ Claude (admin keys only)
```

- **Agents.** A coordinator plus HVAC, lighting, PV, ESS and EV-charging agents repeat observe → plan → coordinate → act → verify every 15 minutes over 4 buildings and 19 zones. The whole simulation runs in the browser in a single-file Three.js dashboard (`index.html`, assembled from `build/` by `build/inject.py`). Without URL options the committed results are reproduced bit for bit; the options below only add evaluation modes.
- **Forecast.** Grid import for the next 4 hours comes from a ridge regression on forecast weather (yesterday's profile plus today's offset), the occupancy timetable and lag features (same slot yesterday, last observed slot). It never reads actual future weather, and it is refitted every slot.
- **Dashboard additions.** A "Stage 1: building without room sensors" preset (`ablate=ROOM`) in the scenario tab. A proposal impact preview that replays a private copy of the simulator for the next 60 minutes with and without the action, behind a fidelity gate (not available with `coord=v2`, with `faultImpact`, or after a dataset was loaded mid-run). A shadow mode that takes a meter CSV, rescales it to campus size keeping its shape, prices it at KEPCO summer weekday rates and reports what the agents would have saved.
- **Evaluation URL options.** `baseline=sensor`, `dr=off`, `seed=N`, `coord=v2`, `drNotice`, `faultImpact=1`, `fddNoise`, `fdd=off`; see [eval/README.md](eval/README.md).
- **LLM gateway** (`server/`, Python standard library). It checks every number in an answer against the data it was given (`numcheck` binds each number to its label and rejects malformed numbers), routes typed questions (tariff lookups, glossary terms, direct commands, "will we exceed the limit?" from the forecast) away from the model when data can answer them, drops proposed actions that would change nothing, and guards against repetition. The prompt-extraction check covers every task, and a leak check runs before streamed text is sent. The public API needs an access key and has per-key rate limits and request-size limits; the local port checks Origin and Content-Type; `/v1/chat/completions` accepts admin keys only. `server/test_gateway.py` has 8 tests. The numcheck change leaves the pass rates on saved v2.1 outputs unchanged on every eval set; on the 66 real questions it newly flags 3 real errors, and one item could not be judged because its saved context differs.
- **Deployment.** The static site deploys from a separate Pages repository ([SungHyunC/ma-bems](https://github.com/SungHyunC/ma-bems)) after a CI check for script syntax, config format and secrets. The gateway stays on the operator PC behind a Cloudflare tunnel. See [deploy/README.md](deploy/README.md) (Korean).

## Local LLM fine-tuning

The public demo's AI assistant uses only a local model, so Qwen3-8B was fine-tuned with QLoRA (4-bit NF4 base, LoRA r=16, loss on answer tokens only). Training data comes from the simulator: 40 scenario and random conditions were logged as the exact contexts the dashboard sends, and rule-based reference answers were written from those contexts. Paraphrased questions came from open models. No Claude output was used for training. Training ran on a 16 GB desktop GPU (v1) and a Modal H100 (v2.1); evaluation used vLLM and was re-checked through Ollama Q8_0 on the desktop.

| Held-out conditions (234 prompts)* | Base Qwen3-8B | Fine-tuned v2.1 |
|---|---|---|
| Answers passing the number check | 86.4% | **98.3%** |
| Answers in the required format | 26.0% | **98.9%** |
| Reference key numbers included | 67.4% | **99.6%** |
| Proposed actions that would change nothing | 121 / 228 | **3 / 209** |
| Agreement with the reference policy (precision / recall) | 12.7 / 15.3% | **67.0 / 73.7%** |

\* "Held-out" means the simulator conditions were not used in training, but 226 of the 234 prompts' question sentences also appear in the training data. A separate set with unseen phrasing (`eval_gen`, 234 prompts, see "eval_gen" in [ft/README.md](ft/README.md)) gives, for v2.1: number check 99.1%, key numbers included 96.4%, "answer in one sentence" followed 100%, answerable questions wrongly refused 0.4%.

With the gateway's no-op filter, the model correctly says "nothing needs to change" in 37 of 37 such cases. The model still learns the rules' style rather than becoming smarter than the rules. The number check only tests whether a number appears in the data the model was given; it is not an accuracy measure, and none of these metrics tests whether the model understood the question. Details, including the v1 → v2 → v2.1 history: [ft/README.md](ft/README.md) (Korean). Trained adapters are in [Releases](https://github.com/SungHyunC/ma-bems-project/releases).

A follow-up test used 66 questions that judges and visitors are likely to type, across 15 categories. Without changing the model, routing, context and output guards raised the human-graded score from 41.5 to 62 out of 66 and cut wrong answers from 17 to 0. This is a regression set that the fixes were tuned on, so it shows that the known failures are fixed, not how the assistant does on new questions.

## Run locally (Windows)

```
python -m venv .venv && .venv\Scripts\pip install anthropic
copy .env.example .env              (fill in ANTHROPIC_API_KEY etc.; pull a Qwen3 8B model in Ollama)
.venv\Scripts\python server\mabems_server.py      → http://127.0.0.1:5178
```

To look around without the AI assistant, serve `index.html` from any static server; the simulation runs in the browser.

## Repository layout

| Path | Contents |
|---|---|
| `index.html` | The dashboard: simulation, agents, forecast and fault detection |
| `build/` | Dashboard modules, assembled into `index.html` by `build/inject.py`; evaluation harness |
| `server/` | Local server and LLM gateway: number check, question handling, public API |
| `eval/` | How to reproduce every reported number (including macOS notes), with result files |
| `ft/` | QLoRA fine-tuning: data generation, training, evaluation, results |
| `deploy/` | Public deployment scripts (GitHub Pages + Cloudflare tunnel, access keys) |
| `deck/` | Competition slide sources |
| `docs/` | Project overview (PDF and HTML, Korean) and the dashboard screenshot; the demo video is in Releases |
| `demo/` | Demo video toolchain: script, Korean TTS, automated recording, assembly |
| `data/` | Measured BDG2 sample (CC BY-SA 4.0) |
| [`HANDOFF.md`](HANDOFF.md) | Project status, decisions and command reference (Korean) |

Not in the repository: `.env` (API and access keys), Python environments, `cloudflared.exe`, the base Qwen3-8B weights, and merged models and GGUF files (tens of GB).

## Limitations

- Simulation only: no metered-data calibration and cooling season only. Demand charges are left out of the default cost (a separate calculation adds them).
- The energy impact of sensor faults is modelled only with `faultImpact=1`, with the limits described above. EV and PV metrics do not separate the controllers in these scenarios.
- The demo video was made before these changes and may still show older wording and numbers (for example the 11.0% forecast figure); so may the dashboard screenshot and the screenshots in the slide deck.
- The dashboard UI supports Korean and English. Most documentation outside this README is in Korean.
