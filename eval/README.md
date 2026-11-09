# MA-BEMS 성능 평가 (재현용)

대시보드 '검증·근거' 탭과 경진대회 발표자료의 숫자는 모두 이 폴더의 스크립트로 만든 결과입니다(평가일 2026-11-09).

## 무엇을 재나

- **반사실 그림자 실행**: 같은 날씨·재실·EV 도착으로 멀티에이전트와 룰 기반 BMS를 동시에 돌려 차이만 비교(IPMVP Option D 방식, 시뮬레이션 기준).
- **9일 × 1분 단위**: `Sim.update()` 한 번에 정확히 1 시뮬레이션 분씩 진행합니다. 에이전트는 15분마다 협상하므로 더 크게 건너뛰면 협상 라운드를 놓칩니다. 첫날(0일)은 준비 구간이고 1~8일을 채점해 95% 신뢰구간을 냅니다. `?speed=0`으로 멈춘 채 시작하므로 같은 설정은 결과가 정확히 같습니다.
- **기준선 사다리**: 기본(룰 기반 BMS), `?baseline=tuned`(ESS 피크 제어 추가), 한전 2026 요금, BDG2 실측 부하 + 한전 요금.
- **구성요소 제거 실험**: `?ablate=ROOM|ESS|HVAC|LIGHT|EV|COORD`, 피크 상한 스트레스 `?limit=900|850|800`.
- **예측**: 1시간 앞 15분 단위 CV(RMSE)·NMBE(ASHRAE Guideline 14), 지속성 예측과 비교.
- **센서 고장 감지**: 정상 운영 오경보 수, 3시간마다 고장을 주입하는 훈련(감지율·지연·정밀도).
- **AI 비서**: 작업별 지연·토큰·비용(로컬 Qwen3-8B vs Claude Opus 5.5), `llm.mjs`.

## 돌리는 법

1. 대시보드 서버 실행: 프로젝트 폴더에서 `.venv\Scripts\python server\mabems_server.py` (포트 5178)
2. 헤드리스 Chrome을 원격 디버깅 포트 9333으로 실행:
   `chrome --headless=new --remote-debugging-port=9333 --user-data-dir=%TEMP%\mabems-cdp-9333 about:blank`
3. 이 폴더에서 실행(설정 하나에 몇 초):
   ```
   node exp.mjs full "" 9
   node exp.mjs full_repeat "" 9
   node exp.mjs tuned "baseline=tuned" 9
   node exp.mjs ablate_ROOM "ablate=ROOM" 9        (ESS, HVAC, LIGHT, EV, COORD도 같은 방식)
   node exp.mjs kepco "" 9 kepco
   node exp.mjs bdg2 "" 9 bdg2
   node exp.mjs drill "" 9 "" 180
   node exp.mjs lim850_full "limit=850" 9
   node exp.mjs lim850_coord "limit=850&ablate=COORD" 9
   node analyze.mjs                                  → results/summary.json
   node llm.mjs                                      → results/llm.json (Claude 호출 약 6회, 약 $0.25)
   ```
4. 시나리오(대시보드 '시나리오' 탭의 측정값): 설정마다 9일, 몇 초씩
   ```
   node exp.mjs scn_normal "" 9
   node exp.mjs scn_heatwave "scn=heatwave" 9      (cloudy, dr, tight, evrush, holiday, fault, worst도 같은 방식)
   node make_scn.mjs                                 → results/scn_summary.json
   ```
   직접 만든 조건은 `scn=custom&dT=3&sun=0.5&occ=0.8&limit=900&drAt=16:00&drShed=300&drMin=60&ev=4&fault=stuck`처럼 넘깁니다.

## 결과 요약 (results/summary.json)

| 항목 | 값 |
|---|---|
| 전력량요금 절감 (룰 기반 BMS 대비) | 16.7 ± 0.2% |
| 튜닝 BMS 대비 / 실측 부하(BDG2)+한전 | 16.6 ± 0.4% / 14.6 ± 0.7% |
| 최대 수요 | 959 kW vs 1,170 kW (상한 1,000 kW 초과 0분 vs 1,996분) |
| 쾌적 | 99.9% vs 100% |
| 구성요소 기여(%p) | 실 단위 12.3 · ESS 3.2 · 공조 2.2 · 조명 0.7 · EV 0.0 · 협상 −0.2 |
| 협상의 효과 (상한 850 kW) | 상한 초과 전력 2,129 → 1,675 kWh (−21%) |
| 예측 | CV(RMSE) 11.0%, NMBE 0.0%, 지속성 대비 21% 개선 |
| 고장 감지 | 정상 운영 오경보 0건(1,206 실·일), 훈련 63/64 감지, 정밀도 98% |
| AI 비서 | 로컬 3–8초·0원, Claude 9–13초·질문당 약 $0.037 |

한계: 시뮬레이션 기준(계량 데이터 보정 전), 냉방 시즌만, 기본요금은 비용 계산 밖, EV·PV 지표는 이 시나리오에서 변별력 없음, 센서 고장의 에너지 영향은 미반영.

## 시나리오별 결과 (results/scn_summary.json, 8일 평균, 에이전트 vs 룰 기반 BMS)

| 시나리오 | 비용 절감 | 최대 수전 (kW) | 한도 초과 (분/일) | 쾌적 (%) | 그 밖에 |
|---|---|---|---|---|---|
| 평상시 | 16.7 ± 0.2% | 959 vs 1,170 | 0 vs 249.5 | 99.9 vs 100 | DR 142 vs 7% (100% 넘음 = 요청보다 더 감축) |
| 폭염 (+5 °C) | 13.7 ± 1.0% | 1,346 vs 1,392 | 256.3 vs 734 | 99.7 vs 99.3 | |
| 흐린 날 (일사 25%) | 13.7 ± 0.6% | 1,207 vs 1,258 | 91 vs 626.4 | 99.9 vs 100 | |
| 수요반응 강화 (16시 300 kW·60분) | 19.0 ± 0.2% | 968 vs 1,170 | 0 vs 249.5 | 99.4 vs 100 | DR 91 vs 2% |
| 피크 한도 850 kW | 17.9 ± 0.3% | 1,055 vs 1,170 | 164.3 vs 755.5 | 99.9 vs 100 | |
| 퇴근길 EV +6대 | 17.3 ± 0.2% | 960 vs 1,267 | 0 vs 281.6 | 99.9 vs 100 | EV 충족 97 vs 97% |
| 휴일·방학 (재실 25%) | 24.8 ± 0.3% | 946 vs 1,045 | 0 vs 45.1 | 99.1 vs 100 | 빈 방 낭비 1,391 vs 2,867 kWh |
| 센서 고착 | 에너지 영향 미반영 | | | | 감지 1/1, 70분. 경보를 처리하지 않고 두면 옆 방 오경보 1건 |
| 최악의 날 (복합) | 9.8 ± 0.3% | **1,512 vs 1,454** | 444.6 vs 815.6 | 99.3 vs 100 | DR 61 vs 2% |

- DR 시나리오는 16시에 발령합니다. 룰 BMS는 15~18시에 배터리를 고정 방전하는데, 15시 DR이면 그 방전이 'DR 감축'으로 집계돼 BMS 달성률이 41~53%로 부풀었습니다.
- 최악의 날에는 에이전트의 최대 수전이 BMS보다 58 kW 높습니다. 배터리를 피크 깎기에 먼저 써서 14시쯤 SOC 8%로 바닥나고, DR이 끝난 직후 냉방이 한꺼번에 돌아오며 반등 피크가 생깁니다. 개선 후보: DR 예고 시 배터리 예비량 확보, DR 뒤 단계적 복귀.
