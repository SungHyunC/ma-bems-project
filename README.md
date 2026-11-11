# MA-BEMS: Multi-Agent Building Energy Management

**Six cooperating agents run a simulated campus every 15 minutes, next to a rule-based BMS fed the same weather, occupancy and EV arrivals, so the difference in cost, peak demand and comfort can be measured directly. A fine-tuned local LLM explains the agents' decisions and proposes control actions.**

English · [한국어](README.ko.md) · [Live dashboard](https://sunghyunc.github.io/ma-bems/) · [Evaluation](eval/README.md) · [Fine-tuning](ft/README.md)

Capstone design project at Korea University Sejong Campus, fall 2026, entered in the Industry-Linked Capstone Design Competition (results pending). It follows [Multi-Agent BEMS](https://github.com/SungHyunC/multi-agent-bems), the spring 2026 capstone that won the Excellence Award; the answer number check in `server/numcheck.py` was ported from that project.

![The MA-BEMS dashboard: a 3D campus with KPI cards, campus details, the agent decision log and the six agents' status](docs/dashboard.webp)

**Demo video** (2:54, Korean narration and subtitles): [1080p](https://github.com/SungHyunC/ma-bems-project/releases/download/demo-2026-11-11/ma-bems-demo-ko.mp4) · [720p](https://github.com/SungHyunC/ma-bems-project/releases/download/demo-2026-11-11/ma-bems-demo-ko-720p.mp4). It was recorded by driving the live dashboard, and the AI answers in it were generated on the spot by the local model. A 10-page project overview (Korean) is in [docs/ma-bems-overview-ko.pdf](docs/ma-bems-overview-ko.pdf).

All results come from simulation. The savings have not been calibrated against metered data.

## Results

Counterfactual shadow run (IPMVP Option D style): the agents and a rule-based BMS run at the same time on identical inputs. Each setting runs 9 simulated days at 1-minute steps. Day 0 is warm-up, and days 1–8 are scored with 95% confidence intervals. Scripts and raw results are in [`eval/`](eval/README.md).

| Metric | Agents vs. rule-based BMS |
|---|---|
| Energy cost savings | **16.7 ± 0.2%** (16.6 ± 0.4% vs. a tuned BMS; 14.6 ± 0.7% on measured BDG2 load with KEPCO tariffs) |
| Peak demand | 959 vs. 1,170 kW; 0 vs. 1,996 minutes above the 1,000 kW limit |
| Comfort compliance | 99.9% vs. 100% |
| 1-hour load forecast | CV(RMSE) 11.0%, NMBE 0.0% (within ASHRAE Guideline 14), 21% better than persistence |
| Sensor fault detection | 0 false alarms over 1,206 room-days of normal operation; 63 of 64 injected faults caught, 98% precision |

- **Ablations** show where the savings come from (percentage points): room-level control 12.3, ESS 3.2, HVAC 2.2, lighting 0.7, EV 0.0. Negotiation adds nothing in the default case (−0.2), but with an 850 kW cap it cuts over-limit energy by 21% (2,129 → 1,675 kWh).
- **Nine scenarios** (heat wave, cloudy day, demand response, tighter limit, EV rush, holiday, stuck sensor, worst day) are reported separately. On the combined worst day, the agents' peak is *higher* than the BMS's (1,512 vs. 1,454 kW): the battery is spent on peak shaving and runs out around 14:00, and cooling rebounds after the DR event. That failure and the proposed fixes are documented in [eval/README.md](eval/README.md).

## How it works

```
Browser (GitHub Pages)                       Operator PC
index.html  ── AI tab ── HTTPS + access key ──> Cloudflare Quick Tunnel ──> LLM gateway (server/)
  simulation, 6 agents, forecast,                                           ├─ Qwen3-8B, fine-tuned (Ollama)
  fault detection, shadow BMS                                               └─ Claude (admin keys only)
```

- **Agents.** A coordinator plus HVAC, lighting, PV, ESS and EV-charging agents repeat observe → plan → negotiate → act → verify every 15 minutes over 4 buildings and 19 zones. The whole simulation runs in the browser in a single-file Three.js dashboard (`index.html`, assembled from `build/` by `build/inject.py`).
- **LLM gateway** (`server/`, Python standard library). It checks every number in an answer against the data it was given, routes typed questions (tariff lookups, glossary terms, direct commands) away from the model when data can answer them, drops proposed actions that would change nothing, and guards against repetition and prompt-extraction requests. The public API needs an access key and has CORS checks, per-key rate limits and request-size limits.
- **Deployment.** The static site deploys from a separate Pages repository ([SungHyunC/ma-bems](https://github.com/SungHyunC/ma-bems)) after a CI check for script syntax, config format and secrets. The gateway stays on the operator PC behind a Cloudflare tunnel. See [deploy/README.md](deploy/README.md) (Korean).

## Local LLM fine-tuning

The public demo's AI assistant uses only a local model, so Qwen3-8B was fine-tuned with QLoRA (4-bit NF4 base, LoRA r=16, loss on answer tokens only). Training data comes from the simulator: 40 scenario and random conditions were logged as the exact contexts the dashboard sends, and rule-based reference answers were written from those contexts. Paraphrased questions came from open models. No Claude output was used for training. Training ran on a 16 GB desktop GPU (v1) and a Modal H100 (v2.1); evaluation used vLLM and was re-checked through Ollama Q8_0 on the desktop.

| Held-out conditions (234 prompts) | Base Qwen3-8B | Fine-tuned v2.1 |
|---|---|---|
| Answers passing the number check | 86.4% | **98.3%** |
| Answers in the required format | 26.0% | **98.9%** |
| Reference key numbers included | 67.4% | **99.6%** |
| Proposed actions that would change nothing | 121 / 228 | **3 / 209** |
| Agreement with the reference policy (precision / recall) | 12.7 / 15.3% | **67.0 / 73.7%** |

With the gateway's no-op filter, the model correctly says "nothing needs to change" in 37 of 37 such cases. The model still learns the rules' style rather than becoming smarter than the rules, and these metrics do not measure whether it understood the question. Details, including the v1 → v2 → v2.1 history: [ft/README.md](ft/README.md) (Korean). Trained adapters are in [Releases](https://github.com/SungHyunC/ma-bems-project/releases).

A follow-up test used 66 questions that judges and visitors are likely to type, across 15 categories. Without changing the model, routing, context and output guards raised the human-graded score from 41.5 to 62 out of 66 and cut wrong answers from 17 to 0.

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
| `eval/` | How to reproduce every reported number, with result files |
| `ft/` | QLoRA fine-tuning: data generation, training, evaluation, results |
| `deploy/` | Public deployment scripts (GitHub Pages + Cloudflare tunnel, access keys) |
| `deck/` | Competition slide sources |
| `docs/` | Project overview (PDF and HTML, Korean) and the dashboard screenshot; the demo video is in Releases |
| `demo/` | Demo video toolchain: script, Korean TTS, automated recording, assembly |
| `data/` | Measured BDG2 sample (CC BY 4.0) |
| [`HANDOFF.md`](HANDOFF.md) | Project status, decisions and command reference (Korean) |

Not in the repository: `.env` (API and access keys), Python environments, `cloudflared.exe`, the base Qwen3-8B weights, and merged models and GGUF files (tens of GB).

## Limitations

- Simulation only: no metered-data calibration, cooling season only, and demand charges are left out of the cost.
- The energy impact of sensor faults is not modeled. EV and PV metrics do not separate the controllers in these scenarios.
- The dashboard UI supports Korean and English. Most documentation outside this README is in Korean.
