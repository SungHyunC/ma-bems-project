# MA-BEMS 성능 평가 (재현용)

대시보드 '검증·근거' 탭과 경진대회 발표자료의 숫자는 모두 이 폴더의 스크립트로 만든 결과입니다(평가일 2026-11-09, 2026-11-12 추가 실험·예측 재계산).

## 무엇을 재나

- **반사실 그림자 실행**: 같은 날씨·재실·EV 도착으로 멀티에이전트와 룰 기반 BMS를 동시에 돌려 차이만 비교(IPMVP Option D 방식, 시뮬레이션 기준).
- **9일 × 1분 단위**: `Sim.update()` 한 번에 정확히 1 시뮬레이션 분씩 진행합니다. 에이전트는 15분마다 계획을 내고 조율하므로 더 크게 건너뛰면 조율 라운드를 놓칩니다. 첫날(0일)은 준비 구간이고 1~8일을 채점합니다. 한 실행의 ± 값은 그 8일 일별 값의 95% 구간(t, n=8)이라 일별 변동만 뜻하고, 입력이 달라지는 경우는 시드 10회의 실행 간 구간(t, n=10)으로 따로 냅니다. `?speed=0`으로 멈춘 채 시작하므로 같은 설정은 결과가 정확히 같습니다.
- **기준선 사다리**: 기본(룰 기반 BMS), `?baseline=tuned`(ESS 피크 제어 추가), `?baseline=sensor`(에이전트와 같은 재실 센싱 + ESS 피크 제어 + 고정 DR 대응), 한전 2026 요금, BDG2 부하 형태 + 한전 요금. BDG2는 미국 대학의 여름 평일 하루 실측 비-HVAC 부하 형태를 크기 조정해 반복한 것이며 이 캠퍼스의 실측 부하가 아닙니다.
- **입력 변동**: `?seed=N`이 재실·예약·EV 도착·DR 추첨을 다시 뽑고 날마다 ±2 °C 기온 편차와 운량(0.65–1.0)을 더합니다. 옵션이 없으면 모든 KPI가 이전 커밋과 비트 단위로 같습니다(`extra_summary.json`의 `defaultsUnchanged`, 최대 차이 0).
- **그 밖의 옵션**: `dr=off`(DR 끔), `coord=v2`(코디네이터 v2), `drNotice`, `faultImpact=1`(고장 센서가 제어를 속임), `fddNoise=σ`(센서 노이즈 °C), `fdd=off`(감지 끔).
- **구성요소 제거 실험**: `?ablate=ROOM|ESS|HVAC|LIGHT|EV|COORD`, 피크 상한 스트레스 `?limit=900|850|800`.
- **예측**: 1시간 앞 수전 15분 단위 CV(RMSE)·NMBE, 어제 같은 시각·지속성과 비교. 미래 날씨를 쓰지 않는 릿지 회귀(어제 같은 시각, 직전 시각 지연 특성). ASHRAE Guideline 14의 30%는 보정 기준이라 비교 대상으로만 씁니다.
- **센서 고장 감지**: 정상 운영 오경보 수, 3시간마다 고장을 주입하는 훈련(감지율·지연·정밀도; 경보의 진위를 아는 운영자를 가정), `faultImpact`로 고장이 에너지·불쾌에 미치는 영향.
- **AI 비서**: 작업별 지연·토큰·비용(로컬 Qwen3-8B vs Claude Opus 5.5), `llm.mjs`. Claude는 공개 데모가 아니라 관리자 키에서만 쓰입니다.

## 돌리는 법

1. 대시보드 서버 실행: 프로젝트 폴더에서 `.venv\Scripts\python server\mabems_server.py` (포트 5178)
2. 헤드리스 Chrome을 원격 디버깅 포트 9333으로 실행:
   `chrome --headless=new --remote-debugging-port=9333 --user-data-dir=%TEMP%\mabems-cdp-9333 about:blank`
   - **macOS**: `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --remote-debugging-port=9333 --user-data-dir=/tmp/mabems-cdp-9333 about:blank`
   - Node 20에서는 `node`에 `--experimental-websocket`을 붙여야 합니다(아래 명령은 `node --experimental-websocket exp.mjs …`). Node 22 이상은 필요 없습니다.
   - 서버는 `python3 server/mabems_server.py`(가상환경 없이도 표준 라이브러리만으로 동작).
3. 이 폴더에서 실행(설정 하나에 몇 초). `analyze.mjs`는 `eval/`에서 실행해도 됩니다:
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

요약 JSON(`summary.json`, `extra_summary.json`, `scn_summary.json`)은 이 폴더의 `results/`에, 실행별 원본(`full.json`, `seed_*.json` 등)은 `build/results/`에 있습니다. 표의 숫자는 모두 이 파일들에서 나왔습니다.

| 항목 | 값 |
|---|---|
| 전력량요금 절감 (기본 BMS 대비, 입력 고정 1회) | 16.7 ± 0.2% (± = 8일 일별 변동) |
| 같은 비교, 시드 10회 (날씨·재실·EV·DR 변동) | 16.5 ± 0.2% (실행 간 95% 구간) |
| 튜닝 BMS 대비 | 16.6 ± 0.4%. 튜닝 BMS의 비용이 기본 BMS와 거의 같고(3,545 vs 3,548 $/일) 평균 최대 수전은 조금 높음(1,176 vs 1,170 kW) |
| 센서 BMS 대비 | 9.7 ± 0.3% (시드 10회 10.2 ± 0.2%), 그 BMS 쾌적 97.0% |
| 최대 수요 | 일별 최대의 평균 959 vs 1,170 kW. 기간 최대 960 vs 1,210 kW. 상한 1,000 kW 초과 0분 vs 1,996분 (8일 합계) |
| 쾌적 | 99.9% vs 100% |
| 구성요소 기여(%p) | 실 단위 12.3 · ESS 3.2 · 공조 2.2 · 조명 0.7 · EV 0.0 · 코디네이터 v1 −0.15 |
| 코디네이터 v1의 효과 (초과 전력, 8일 합계) | 900 kW 482 → 417 kWh(−13%) · 850 kW 2,129 → 1,675 kWh(−21%) · 800 kW 5,083 → 4,610 kWh(−9%) |
| 예측 (1시간 앞, 미래 날씨 미사용, n=766) | CV(RMSE) 8.0%, NMBE 0.1%. 어제 같은 시각 9.0%, 1시간 전 값 유지 14.1% |
| 고장 감지 | 정상 운영 오경보 0건/1,206 실·일, 훈련 63/64 감지(오경보 1건, 정밀도 98%, 경보 진위를 아는 운영자 가정) |
| 기본요금 포함 (한전 8,320원/kW·월, 기간 최대) | 한전 14.9 → 15.5%, BDG2 14.6 → 15.6% |
| AI 비서 | 로컬 3–8초·0원, Claude 9–13초·질문당 약 $0.037 (Claude는 관리자 키에서만) |

한계: 시뮬레이션 기준(계량 데이터 보정 전), 냉방 시즌만, 기본요금은 기본 비용 계산 밖(별도 계산 위 표), EV·PV 지표는 이 시나리오에서 변별력 없음, 센서 고장의 에너지 영향은 `faultImpact` 모드에서만 시험(아래 한계 참고).

## 새 실험 (2026-11-12, results/extra_summary.json)

모든 실험은 같은 방식(9일 × 1분, 1~8일 채점, 같은 날씨·재실에서 BMS와 짝지어 비교)입니다. 옵션 없이 돌린 기존 결과는 이전 커밋과 비트 단위로 같습니다(`defaultsUnchanged`: 11쌍, 최대 차이 0).

### 기준선과 입력 변동

| 비교 | 비용 절감 | 최대 수전 평균 (kW) | 쾌적 (%) | 한도 초과 (분 / kWh) |
|---|---|---|---|---|
| 기본 BMS, 입력 고정 8일 | 16.7 ± 0.2% | 959 vs 1,170 | 99.9 vs 100 | 0 vs 1,996 / 0 vs 2,167 |
| 기본 BMS, 시드 10회 | 16.5 ± 0.2% | 981 vs 1,193 | 99.7 vs 99.9 | 평균 27.7 vs 3,049 / 17 vs 4,052 |
| 센서 BMS, 입력 고정 8일 | 9.7 ± 0.3% | 959 vs 1,068 | 99.9 vs 97.0 | 0 vs 605 / 0 vs 430 |
| 센서 BMS, 시드 10회 | 10.2 ± 0.2% | 981 vs 1,137 | 99.7 vs 97.4 | 27.7 vs 911.8 / 17 vs 1,504 |
| 기본 BMS, `dr=off` | 14.4 ± 0.2% | 959 vs 1,170 | 99.98 vs 100 | 0 vs 1,996 |

- 시드 행의 ±는 10개 실행(각 실행의 8일 평균)에 대한 95% t 구간입니다. 시드별 값은 `seed_N.json`, `sensor_seed_N.json`.
- 센서 BMS는 쾌적을 낮추는 대신 비용을 줄이는 BMS입니다(불쾌 °C·h는 에이전트 67 vs 센서 BMS 47). 에이전트는 DR을 요청의 142%로 이행하고 센서 BMS는 고정 대응으로 175%(DR 요청 대비 감축률)입니다.
- `dr=off`: DR 신호를 양쪽 모두 끄면 절감 16.7 → 14.4%라, 기본 BMS 대비 격차 중 약 2.3%p는 DR 미대응 효과입니다.
- 시드 10회의 ±0.2는 "다른 날씨·재실에서도 비슷한가"에 답하는 구간이고, 기준선 비교(센서 BMS)에서는 피크 격차의 변동이 더 큽니다(시드별 센서 BMS 평균 최대 수전 1,137 ± 40 kW).

### 코디네이터 v2 대 v1 (`?coord=v2`, 기본값은 v1)

v2: DR 예고(60분)와 배터리 예비·단계적 복귀, 예측 기반 ESS 물 채우기 배분, 비용 기반 배분(최대 3라운드). 비용 절감은 BMS 대비, 한도 초과는 8일 합계, 최대 수전은 일별 최대의 평균입니다.

| 시나리오 (한도) | 비용 절감 v1 → v2 | 평균 최대 수전 kW | 한도 초과 kWh | 한도 초과 분 |
|---|---|---|---|---|
| 평상시 (1,000) | 16.7 → 17.4% | 959 → 960 | 0 → 0 | 0 → 0 |
| 폭염 | 13.7 → 15.4% | 1,346 → 1,125 (BMS 1,392) | 4,385 → 2,407 | 2,050 → 3,303 (+61%) |
| 흐린 날 | 13.7 → 14.3% | 1,207 → 1,059 | 973 → 268 | 728 → 498 |
| DR 강화 | 19.0 → 19.1% | 968 → 962 | 0 → 0 | 0 → 0 |
| 한도 850 | 17.9 → 17.3% (−0.6%p) | 1,055 → 878 | 1,675 → 392 | 1,314 → 1,191 |
| 최악의 날 (900) | 9.8 → 15.9% | 1,512 → 1,299 (BMS 1,454) | 15,888 → 13,544 | 3,557 → 5,349 (+50%) |
| 한도 800 | 15.9 → 17.5% | 1,107 → 911 (기간 최대 1,157 → 950) | 4,610 → 2,493 | 2,059 → 3,867 (+88%) |
| 시드 10회 (v2 − v1) | +0.4 ± 0.1%p | 평균 최대 −12 ± 6, 기간 최대 −66 ± 26 | −11 ± 9 | −6 ± 20 |

- v2는 총량(비용·피크·초과 kWh)은 대부분 좋아지지만 한도를 넘는 시간(분)은 폭염·최악의 날·한도 800에서 늘고, 한도 850에서는 절감이 0.6%p 줄었습니다.
- 시드 10회에서 v2 대 기본 BMS 절감은 16.9 ± 0.25%(`v2_seed_N.json`)입니다.
- 기본값은 v1로 유지합니다. v2를 기본으로 바꿀지는 결정 사항입니다. 파일: `v1_*.json`, `v2_*.json`, `v2_seed_N.json`.

### 예측 (미래 날씨 미사용)

| 모델 (1시간 앞, n=766) | CV(RMSE) | NMBE |
|---|---|---|
| 릿지 회귀(날씨 예보, 재실 시간표, 어제 같은 시각·직전 시각 지연) | 8.0% | 0.1% |
| 어제 같은 시각 | 9.0% | −0.1% |
| 직전 관측값 유지(지속성) | 14.1% | 0.0% |
| 시드 10회 (모델 / 어제 / 지속성) | 8.0 / 9.9 / 12.9% | NMBE 0.1 ± 0.2% |

이전 예측(11.0%)은 목표 시각의 실제 날씨를 읽는 방식이라 폐기했고, 모든 숫자를 새 방식으로 다시 계산했습니다. 정의: 슬롯 a의 1시간 앞 예측은 슬롯 a−4 시작 시점에 a−5까지의 데이터로 만듭니다(`summary.json`의 `forecast.definitions`).

### 센서 고장 감지

| 설정 | 결과 |
|---|---|
| 기본 입력, 정상 운영 | 오경보 0건/1,206 실·일 |
| 기본 입력 무고장 25회 합계 | 6건/30,150 실·일 |
| 날씨 변동 시드 10회 (무고장) | 34건/12,060 실·일 (시드 5에서 14건) |
| 센서 노이즈 σ = 0.3 °C, 정상 운영 | 1건/1,206 실·일 |
| σ = 0.3 °C, 고장 훈련 | 63/64 감지, 오경보 0, 드리프트 중앙값 75분 |

훈련은 경보의 진위를 아는 운영자가 진짜 경보만 승인하고 거짓 경보는 기각한다고 가정합니다. 실제 운영자는 이만큼 정확하지 않을 수 있습니다.

### 고장의 에너지 영향 (`faultImpact=1`)

9일 전체를 같은 날씨에서 고장 없는 실행과 비교한 추가 에너지입니다. 승인된 센서는 30분 뒤 수리된다고 가정하고, BMS 쪽 세계는 고장을 그대로 둡니다.

| 고장 | 감지 끔 (추가 kWh) | 감지 켬, 진짜 경보 승인 | 감지 켬, 경보 방치 |
|---|---|---|---|
| 드리프트 1건 | +1,285 kWh | +27 kWh | +1,128 kWh |
| 고착 1건 | +393 kWh | 0 kWh | −404 kWh, 불쾌 +1,963 °C·h |
| 3시간마다 고장 주입 훈련 | +12,387 kWh (49건 주입) | +1,572 kWh (63건 주입) | |

- 훈련의 두 실행은 주입된 고장 수가 다릅니다(감지 끔 49건, 켬 63건). 같은 고장 수로 맞춘 비교가 아니므로 방향(감지가 에너지를 줄임)만 읽어야 합니다.
- 가상 센서에는 피드백이 없어, 경보를 방치한 고착은 에너지를 404 kWh 아끼지만 불쾌 °C·h가 1,963 늘어납니다(에너지 절감이 아니라 쾌적 손실).
- 닫힌 루프에서는 드리프트 감지가 느려집니다: 훈련 중앙값 55분(`drill.json`) → 245분(`fi_drill.json`), 오경보 55건.
- 파일: `fi_*.json`, `n03_*.json`.

### 기본요금 (`analyze.mjs`)

한전 일반용(을) 고압A 선택 II 2026-06-01 기본요금 8,320원/kW·월을 기간 최대 수전에 곱합니다.

| 설정 | 에너지요금만 | 기본요금 포함 |
|---|---|---|
| 한전 요금, 모델 부하 | 14.9% | 15.5% (월 2,084,109원 절감) |
| BDG2 부하 형태 | 14.6% | 15.6% (월 2,669,299원 절감) |

저장소에 달러 요율이 없어 `$` 설정은 에너지요금만 냅니다. 달러 요율은 `node analyze.mjs --demandUSD=<$/kW·월>`로 넣습니다.

### 재현 명령 (`extra_summary.json`의 `commands`)

`build/results/`에 저장됩니다. 시드 N=1…10에 대해 같은 세 줄을 반복합니다.

```
node --experimental-websocket exp.mjs sensor "baseline=sensor" 9
node --experimental-websocket exp.mjs dr_off "dr=off" 9
node --experimental-websocket exp.mjs seed_N "seed=N" 9
node --experimental-websocket exp.mjs sensor_seed_N "baseline=sensor&seed=N" 9
node --experimental-websocket exp.mjs v2_seed_N "coord=v2&seed=N" 9
node --experimental-websocket exp.mjs v2_scn_normal "coord=v2" 9
node --experimental-websocket exp.mjs v1_scn_heatwave "scn=heatwave" 9        (cloudy, dr, tight, worst도 같은 방식, v2_scn_*은 앞에 coord=v2&)
node --experimental-websocket exp.mjs v2_scn_heatwave "coord=v2&scn=heatwave" 9
node --experimental-websocket exp.mjs v1_lim850 "limit=850" 9                  (v2_lim850은 "coord=v2&limit=850", 800도 같은 방식)
node --experimental-websocket exp.mjs n03_full "fddNoise=0.3" 9
node --experimental-websocket exp.mjs n03_drill "fddNoise=0.3" 9 "" 180
node --experimental-websocket exp.mjs n03_fault "fddNoise=0.3&scn=fault" 9
node --experimental-websocket exp.mjs fi_ref "faultImpact=1" 9
node --experimental-websocket exp.mjs fi_stuck_op "faultImpact=1&scn=fault" 9 "" -1
node --experimental-websocket exp.mjs fi_stuck_off "faultImpact=1&scn=fault&fdd=off" 9
node --experimental-websocket exp.mjs fi_stuck_noop "faultImpact=1&scn=fault" 9
node --experimental-websocket exp.mjs fi_drift_op "faultImpact=1&scn=custom&fault=drift" 9 "" -1     (_off은 &fdd=off, _noop은 마지막 인자 없이)
node --experimental-websocket exp.mjs fi_dropout_op "faultImpact=1&scn=custom&fault=dropout" 9 "" -1  (_off은 &fdd=off)
node --experimental-websocket exp.mjs fi_drill "faultImpact=1" 9 "" 180
node --experimental-websocket exp.mjs fi_drill_off "faultImpact=1&fdd=off" 9 "" 180
node analyze.mjs                      (선택: --demandUSD=<$/kW·월>)
```

시드 N 실행은 `seed_1`~`seed_10`처럼 이름을 바꿔 위 세 줄(`seed_N`, `sensor_seed_N`, `v2_seed_N`)을 10번 돌립니다.

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
| 센서 고착 | 기본 모드는 에너지 영향 미반영(`faultImpact` 결과는 위) | | | | 감지 1/1, 70분. 경보를 처리하지 않고 두면 옆 방 오경보 1건 |
| 최악의 날 (복합) | 9.8 ± 0.3% | **1,512 vs 1,454** | 444.6 vs 815.6 | 99.3 vs 100 | DR 61 vs 2% |

- DR 시나리오는 16시에 발령합니다. 룰 BMS는 15~18시에 배터리를 고정 방전하는데, 15시 DR이면 그 방전이 'DR 감축'으로 집계돼 BMS 달성률이 41~53%로 부풀었습니다.
- 최악의 날에는 에이전트의 최대 수전이 BMS보다 58 kW 높습니다. 배터리를 피크 깎기에 먼저 써서 14시쯤 SOC 8%로 바닥나고, DR이 끝난 직후 냉방이 한꺼번에 돌아오며 반등 피크가 생깁니다. 코디네이터 v2(`coord=v2`)가 DR 예고 시 배터리 예비량 확보와 DR 뒤 단계적 복귀를 구현했고, 같은 시나리오에서 평균 최대 수전이 1,512 → 1,299 kW(BMS 1,454보다 낮음)로 내려갑니다(위 v2 표). 이 표의 값은 기본값 v1입니다.
- 이 표의 "최대 수전"은 일별 최대의 평균입니다.
