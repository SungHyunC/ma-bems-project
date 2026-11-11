# MA-BEMS 인수인계 문서

작성: 2026-11-09 19:55 (모든 작업을 멈춘 시점). 비밀값(API 키·접근 키)은 이 문서에 없습니다.

## 0. 한눈에

- **무엇**: 멀티에이전트 건물 에너지 관리(BEMS) 대시보드 MA-BEMS. 6개 에이전트(코디네이터·HVAC·조명·태양광·ESS·EV)가
  가상 캠퍼스를 운영하고, 같은 조건의 룰 기반 BMS와 나란히 돌려 비교합니다.
- **어디에 쓰나**: 고려대 세종 2026-2 기업연계형 캡스톤디자인 경진대회. **신청 마감 2026-11-20 15:00**(이메일),
  **발표 2026-11-30 18:00**(10분 이내, ZOOM 녹화 후 공개).
- **공개 사이트**: https://sunghyunc.github.io/ma-bems/ (GitHub 저장소 `SungHyunC/ma-bems`, 공개)
- **프로젝트 전체 원본**: https://github.com/SungHyunC/ma-bems-project (공개, 2026-11-10).
  이 `MA-BEMS` 폴더 자체이며, `.gitignore`로 `.env`·가상환경·모델 가중치·실행 파일·로그·`deploy/site`를 뺐습니다.
  학습 어댑터는 Releases [`ft-lora-v1`](https://github.com/SungHyunC/ma-bems-project/releases/tag/ft-lora-v1),
  [`ft-lora-v21`](https://github.com/SungHyunC/ma-bems-project/releases/tag/ft-lora-v21)(2026-11-10, 권장).
  고친 뒤 올리기: `git add -A && git commit -m "…" && git push`
- **발표자료**: https://claude.ai/artifact/EQNrp4akfqZMiuh1BTowEA (15장, 아직 비공개 — 공유 버튼으로 열어야 함)
- **지금 상태 (2026-11-10 갱신)**: 공개 모드 켜짐(게이트웨이 + 터널).
  - **게이트웨이 AI는 파인튜닝 v2.1(`qwen3-8b-bems-v21`, Q8_0)**: PR #1을 병합한 뒤 데스크톱에서 등록·평가하고 바꿨습니다.
  - 효과 없는 제안을 지우는 필터(`drop_noops`)도 들어가 있습니다.
  - 되돌리려면 `.env`를 `LLM_LOCAL_MODEL=qwen3-8b-local`로 바꾸고 `deploy\start-public.cmd -RestartGateway`를 실행합니다.
- **v2.1 데스크톱 결과** (`ft\README.md` "데스크톱 확인"):
  - 수치 검증 98.9%, "한 문장으로" 지시 100%, 답할 수 있는 질문 거절 0.4%
  - 제안은 필터 후 효과 없는 조치 0개, "바꿀 필요 없음" 37/37
  - 한계: 질문 뜻을 잘못 이해하는 경우가 있음("가장 비싼 시간대" → 최대 수전으로 답함). 현재 지표로는 측정되지 않음
- **AI 비서 실제 질문 대비 (2026-11-11, 3.8)**: 예상 질문 66개로 점검하고 고쳤습니다.
  - 사람 채점 41.5 → 62점(66점 만점), 오답 17 → 0. 모델은 그대로입니다.
  - 요금 시간표·용어 정의·명령·인사는 모델 없이 데이터나 규칙으로 답합니다.
  - 질문 분류는 페이지(`build\ai_module.js`), 용어집·조회·출력 점검은 게이트웨이(`server\assist.py`)가 맡습니다.
- **Ollama 모델**:
  - `qwen3-8b-bems-v21`: 운영 중
  - `qwen3-8b-bems`: v1
  - `qwen3-8b-q8`: 원본 Q8, 비교용
  - `qwen3-8b-local`: 원래 Q4_K_M

### 바로 다음에 할 일

1. 발표자료 빈칸 채우기: `[팀명]`, `[팀원 이름]`, `[교수명]`, `[기업명]`/`[연계 기업]`, `[멘토 이름]` (14·1쪽 등)
2. 제출 전 발표자료·대시보드 공유 설정 확인, 신청 메일(참가신청서·발표자료·동의서) 11/20 15:00까지
3. (선택) 파인튜닝 v2.2: `ft\data\realq.json`의 질문 유형(정의, 층별, 명령, 후속 질문)을 학습 데이터에 넣기.
   같은 66개를 회귀 평가로 씀(`ft\README.md` "실제 질문 대비")
4. (권장) 공개 터널 감시: 2026-11-10 22:30에 네트워크 끊김으로 cloudflared가 스스로 종료돼 다음 날 오후까지 AI가 꺼져 있었음.
   발표 당일엔 시작 직전에 `deploy\start-public.cmd`를 다시 실행하고 AI 탭 "운영자 PC: 켜짐"을 확인
5. (선택) 에이전트 약점 보완: "최악의 날"의 DR 직후 반등 피크 (3.6 참고)
6. 발표 당일: `deploy\start-public.cmd`, 절전 끄기, 화면에 키가 나오지 않게

## 1. 정지 시점 상태

| 구성 | 상태 | 다시 켜는 법 |
|---|---|---|
| 게이트웨이(`server\mabems_server.py`, 5178·5179) | 켜짐(백그라운드 프로세스) | 끄기 `deploy\stop-public.cmd` |
| Cloudflare 터널 | 켜짐(주소는 실행마다 바뀜, 사이트 설정에 자동 반영) | 위와 같음 |
| 공개 사이트 | 정상, AI는 접근 키로 사용 가능 | — |
| 사이트 저장소 `deploy\site` | 커밋·푸시 완료 | — |
| 파인튜닝 | v1·v2.1 완료. v2.1(`qwen3-8b-bems-v21`)이 게이트웨이에서 운영 중 | 되돌리기: 0장 |
| 헤드리스 Chrome(평가용, 9333) | 꺼짐 | 5.4 |
| Ollama | 켜짐. 게이트웨이는 `qwen3-8b-bems-v21`(Q8_0, 그래픽 메모리 약 10 GB) 사용 | 자동 로드 |

## 2. 폴더 지도

```
MA-BEMS\
  index.html            대시보드 (단일 파일, Three.js). build\inject.py가 모듈을 끼워 넣어 생성
  data\                 BDG2 실측 샘플 CSV (CC BY 4.0)
  server\
    mabems_server.py    로컬 서버 + LLM 게이트웨이 (5178: 페이지·API, 5179: 공개 API)
    numcheck.py         LLM 답변 숫자 검증기
    assist.py           질문 처리: 요금 조회·용어 정의·용어집·answerFacts·후속 질문·반복/지침 유출 차단 (3.8)
  .env                  설정 + 비밀값(ANTHROPIC_API_KEY, 접근 키). 저장소에 올리지 않음
  .env.example          설정 항목 설명 (값 없음)
  build\                대시보드 빌드 원본 (이번에 세션 임시 폴더에서 옮겨 옴)
    inject.py           index.html에 아래 모듈을 끼우고 원본 코드에 패치를 적용 (python -I inject.py)
    ai_module.js · ai_ui.html     AI 비서 탭 (로컬/공개 게이트웨이, 접근 키, 제안 검증)
    tariff_module.js · fdd_module.js   한전 요금 프리셋, 센서 고장 감지(FDD)
    proof_template.js → make_proof.mjs → proof_module.js   '검증·근거' 탭 (평가 결과를 박아 넣음)
    scn_module.js · make_scn.mjs  '시나리오' 탭과 측정값 생성
    exp.mjs · analyze.mjs · llm.mjs · shot.mjs · closechrome.mjs   평가 하네스
    pub_test.py         공개 API 점검 (키는 .env에서 읽고 출력하지 않음)
    enum_probe.py · ctx_propose.json   로컬 제안 출력 제한 실험
    results\            평가 원본 결과(JSON) 전부
  eval\                 평가 재현용 (README에 방법·결과표)
  deck\project\         발표자료 원본 사본 (실제 원본은 위 claude.ai 아티팩트)
  deploy\
    README.md           공개 배포 운영 가이드 (발표 당일 순서, 키, 보안, 문제 해결)
    start-public.ps1/.cmd · stop-public.cmd · publish-site.ps1/.cmd · keys.cmd
    bin\cloudflared.exe Cloudflare 공식 2026.10.7 (SHA-256·서명 확인)
    site\               GitHub Pages 저장소 (public\ = 실제 배포되는 파일, .github\ = CI)
    logs\               게이트웨이·터널 로그, state.json
  ft\                   로컬 LLM 파인튜닝 (README에 방법)
    .venv\              학습 전용 파이썬 (torch 2.14.1+cu130, transformers 5.22, peft 0.21, trl 1.17, bitsandbytes 0.50)
    models\Qwen3-8B\    공식 가중치 16.4 GB (SHA-256 확인)
    llama.cpp\          LoRA → GGUF 변환 스크립트만
    scripts\            collect.mjs · make_data.py · train.py · eval_ab.py
    data\               samples_*.jsonl (문맥), train/eval.jsonl, train_sub.jsonl(946건)
    out\                Modelfile, eval_base.json(기준 점수), train*.log, smoke\(3단계 시험 어댑터, 쓰지 않음)
  HANDOFF.md            이 문서
```

## 3. 무엇을 했나

### 3.1 대시보드 기능

- 6개 에이전트가 15분마다 관찰→계획→협상→실행→검증. 같은 날씨·재실·EV·DR로 룰 기반 BMS를 함께 돌리는 반사실 그림자 실행.
- 수요 예측(날씨·재실 회귀), 센서 고장 감지(가상 센서 + 이웃 방 비교, 고착·드리프트·끊김), 한전 요금 프리셋, BDG2 실측 데이터 불러오기.
- **AI 비서 탭**: 로컬 Qwen3-8B(Ollama) 우선, 필요할 때 Claude Opus 5.5. 답변 숫자를 실제 데이터와 대조하고,
  제어는 운영자가 "적용"을 눌러야만 실행. 모든 답변에 "AI 생성" 표시(인공지능기본법 제31조).
- **검증·근거 탭**: 평가 방법, 결과, 한계, 출처.
- **시나리오 탭(이번 세션)**: 프리셋 9개 + 직접 만들기. 3.6 참고.

### 3.2 성능 평가 (`eval\`, 9일 × 1분 단위, 1~8일 채점, 95% 신뢰구간)

| 항목 | 결과 (에이전트 vs 룰 기반 BMS) |
|---|---|
| 전력량요금 절감 | 16.7 ± 0.2% |
| 튜닝 BMS 대비 / BDG2 실측 + 한전 요금 | 16.6 ± 0.4% / 14.6 ± 0.7% |
| 최대 수요 | 959 vs 1,170 kW (한도 1,000 kW 초과 0분 vs 1,996분) |
| 쾌적 | 99.9% vs 100% |
| 구성요소 기여(%p) | 실 단위 12.3 · ESS 3.2 · 공조 2.2 · 조명 0.7 · EV 0.0 · 협상 −0.2 |
| 협상 효과 (한도 850 kW) | 한도 초과 전력 2,129 → 1,675 kWh (−21%) |
| 예측 | CV(RMSE) 11.0%, NMBE 0.0% (ASHRAE Guideline 14 기준 이내), 지속성 대비 21% 개선 |
| 고장 감지 | 정상 운영 오경보 0건(1,206 실·일), 훈련 63/64 감지, 정밀도 98% |
| AI 비서 | 로컬 3–8초·0원, Claude 9–13초·질문당 약 $0.037 |

한계: 시뮬레이션 기준(계량 데이터 보정 전), 냉방 시즌만, 기본요금은 비용 밖, EV·PV 지표는 변별력 없음, 고장의 에너지 영향 미반영.

### 3.3 발표자료 (claude.ai Slides 아티팩트)

- 15장, "왜"를 앞세운 구성, 한국어 발표 대본 포함. 숫자는 모두 `eval\` 결과.
- 15쪽 마지막 장에 대시보드 링크 `sunghyunc.github.io/ma-bems` (claude.ai 링크에서 교체함).
- 아직: 빈칸 5종(0장 참고). 시나리오·파인튜닝 내용은 발표자료에 아직 없음.
- 편집 규칙: Slides 아티팩트는 파일 단위로 `project/slides/*.html`을 고쳐 다시 게시. 로컬 사본은 `deck\project\`.

### 3.4 공개 배포 (`deploy\`, 자세한 운영은 `deploy\README.md`)

```
방문자 → GitHub Pages(정적 대시보드) ─ AI 탭 ─HTTPS + 접근 키→ Cloudflare Quick Tunnel → 이 PC 127.0.0.1:5179 → Ollama / Claude
```

- **프런트엔드**: GitHub Pages. `main`에 푸시하면 GitHub Actions가 검사(페이지 스크립트 문법, config 형식, 비밀값 스캔) 후 배포.
- **게이트웨이 공개 API(5179)**: 127.0.0.1에서만 열림, 파일 제공 없음(`.env` 404), 모든 호출에 `Authorization: Bearer <접근 키>`,
  CORS는 `https://sunghyunc.github.io`와 이 PC만, 키당 분당 10회·하루 300회(관리자 분당 30회), 동시 2건, 요청 256 KB.
  OpenAI 호환 `/v1/chat/completions`·`/v1/models`도 제공(스트리밍 없음).
- **접근 키** (`.env`, 수정하면 재시작 없이 반영): `MABEMS_USER_KEYS`에 `judges`(로컬 모델만), `MABEMS_ADMIN_KEYS`에 `owner`(로컬 + Claude).
  보기·공유 링크: `deploy\keys.cmd`. 발급 `--new-key 이름 [--admin]`, 회수 `--revoke 이름`.
- **터널**: 계정 없는 Quick Tunnel. 켤 때마다 주소가 바뀌고 `start-public`이 `config.json`을 고쳐 푸시(반영 약 1분).
  응답은 스트리밍 없이 한 번에 도착(Quick Tunnel이 버퍼링 — 실측 확인).
- **확인한 것**: 실제 터널을 거친 키·출처·파일 차단·질의응답·속도 제한, 공개 사이트에서 "운영자 PC: 켜짐"과 키 입력란, 틀린 키 거부, 끄기→켜기 한 바퀴.
- **확인 못 한 것**: 공개 사이트에서 진짜 키를 넣는 마지막 단계(안전 규칙상 직접 못 함). 같은 경로를 명령줄·모의 응답으로 검증함.
  → 발표 전에 `keys.cmd`의 `owner` 링크로 한 번 직접 확인할 것.
- claude.ai 대시보드 사본(https://claude.ai/artifact/WXM4dhZyCLcRpaYU4L4PxJ)은 예전 버전이고 공개 사이트로 안내만 함(시나리오 탭 없음).

### 3.5 AI 비서 개선 (이번 세션)

| 문제 | 원인 | 조치 | 확인 |
|---|---|---|---|
| judges 키로 "제어 제안" 시 전부 "적용 불가" | 로컬 8B가 대상 칸에 `ess`·`roomLights` 등을 넣음(16건 중 0건 유효). 평소엔 제안을 Claude가 먼저 맡아 안 보였음 | 로컬 모델에만 요청마다 실제 존·방 ID와 허용값을 enum으로 묶은 스키마 전달(`proposal_schema`), 같은 대상 중복 제거 | 실험 16/16, 게이트웨이 경유 14/14 유효, 약 4.5초 |
| "데이터에 없는 수치: 1.5" | 운영 규칙(설정온도 ±1.5 °C)의 숫자를 검사기가 모름 | `numcheck.check(..., rules=시스템 프롬프트)` | 지어낸 숫자(한도 940 kW 등)는 여전히 잡음 |
| 저온실(4 °C)이 제안 대상 | 후보 목록·검증에 저온실 예외 없음 | 후보에서 제외, 검증에서 거부("저온실은 4 °C 유지") | — |
| 큰 문맥의 "선택 대상 설명" 실패 | Ollama 기본 문맥 4,096 토큰, 게이트웨이 추정(2.4자/토큰)이 한국어+JSON에서 과소 | 로컬 호출은 항상 `num_ctx` 8,192 | 실패하던 4,205토큰 요청 성공 |

### 3.6 시나리오 기능 (대시보드 '시나리오' 탭, 상단 버튼)

`?scn=heatwave|cloudy|dr|tight|evrush|holiday|fault|worst` 또는 `?scn=custom&dT=…&sun=…&occ=…&limit=…&drAt=HH:MM&drShed=…&drMin=…&ev=…&fault=…`.
페이지를 그 조건으로 오전 10시부터 다시 시작하고, 카드마다 바뀌는 조건·에이전트 실제 규칙·볼 곳·8일 측정값을 보여 줌.
평상시 결과는 기존 평가와 일별로 완전히 같음(회귀 없음 확인).

| 시나리오 | 비용 절감 | 최대 수전 (kW) | 한도 초과 (분/일) | 그 밖에 |
|---|---|---|---|---|
| 평상시 | 16.7 ± 0.2% | 959 vs 1,170 | 0 vs 249.5 | DR 142 vs 7% (100% 초과 = 요청보다 더 감축) |
| 폭염 +5 °C | 13.7 ± 1.0% | 1,346 vs 1,392 | 256.3 vs 734 | |
| 흐린 날 (일사 25%) | 13.7 ± 0.6% | 1,207 vs 1,258 | 91 vs 626.4 | |
| DR 강화 (16시 300 kW·60분) | 19.0 ± 0.2% | 968 vs 1,170 | 0 vs 249.5 | DR 91 vs 2% |
| 한도 850 kW | 17.9 ± 0.3% | 1,055 vs 1,170 | 164.3 vs 755.5 | |
| 퇴근길 EV +6대 | 17.3 ± 0.2% | 960 vs 1,267 | 0 vs 281.6 | EV 충족 97 vs 97% |
| 휴일·방학 (재실 25%) | 24.8 ± 0.3% | 946 vs 1,045 | 0 vs 45.1 | 빈 방 낭비 1,391 vs 2,867 kWh |
| 센서 고착 | 에너지 영향 미반영 | | | 70분 만에 감지, 경보 방치 시 옆 방 오경보 1건 |
| 최악의 날 (복합) | 9.8 ± 0.3% | **1,512 vs 1,454** | 444.6 vs 815.6 | DR 61 vs 2% |

발견한 것:
- **DR 시각 함정**: 룰 BMS는 15~18시에 배터리를 고정 방전합니다. 15시 DR이면 그 방전이 'DR 감축'으로 집계돼 BMS 달성률이 41~53%로 부풀었음 → 프리셋 DR을 16시로 옮김.
- **에이전트 약점**: 최악의 날에 에이전트 최대 수전이 BMS보다 58 kW 높음. 배터리를 피크 깎기에 먼저 써서 14시쯤 SOC 8%로 바닥나고,
  DR이 끝난 직후 냉방이 한꺼번에 복귀하며 반등 피크 발생. 개선 후보: DR 예고 시 배터리 예비량 확보, DR 뒤 단계적 복귀.
  (에이전트 로직을 바꾸면 기본 평가 숫자도 바뀌므로 `eval\` 전체 재실행과 발표자료 숫자 갱신이 필요)

### 3.7 로컬 LLM 파인튜닝 (`ft\`, 미완료)

목표: judges 키(로컬 모델만)로도 형식에 맞고 숫자가 맞으며 쓸모 있는 제안을 내게 하기. 유효성은 3.5의 출력 제한이 이미 보장하고, 파인튜닝은 "내용"을 겨냥.

- **데이터 (API 비용 0원)**: 시뮬레이터를 시나리오 9종 + 무작위 조건 31종으로 돌려 AI 패널이 보내는 실제 문맥 782건 수집(평가용은 다른 조건 6종, 117건).
  정답은 문맥에서 규칙으로 생성(질의응답 13종 + "데이터에 없음", 브리핑, 설명, 제어 제안 정책). 학습 1,592건 / 평가 234건.
  정답 전부 수치 검증 통과(1,214/1,214, 177/177). Claude 답변을 정답으로 쓰지 않은 이유: Anthropic 약관의 경쟁 모델 학습 제한 가능성.
- **형식 일치**: 학습 프롬프트(Qwen3 템플릿, think 끔) = Ollama 렌더링, 토큰 수 2,414 = 2,414 확인.
- **기준 점수 (현재 qwen3-8b-local, 평가 234건)** — `ft\out\eval_base.json`:

  | 지표 | 값 |
  |---|---|
  | 수치 검증 통과 | 91.0% |
  | 형식 준수 (결론 + 근거 2~4줄) | 21.5% |
  | 핵심 숫자 포함 | 67.0% |
  | "데이터에 없음" 거절 | 76.9% |
  | 제안 중 효과 없는 조치 | 118 / 228 (52%) |
  | 정답 정책과 일치 (정밀도/재현율) | 7.9% / 9.5% |
  | "바꿀 필요 없음" 판단 | 0% |

  주의: 이 측정은 `num_ctx` 수정 전이라 설명 3건이 문맥 초과로 실패해 있음 → 비교 전에 기준을 다시 재야 함.
- **학습 시도 기록**:
  - 시험(24건, 3단계): 단계당 43.5초, GPU 최대 10.4 GB, 손실 1.634 → 정상
  - 1차(948건, 최대 3,584토큰): VRAM이 차서 시스템 메모리로 5.2 GB 넘침 → 첫 단계 1,389초, 중지
  - 2차(946건, 최대 3,328토큰): 단계당 약 40초로 정상, 6/119단계(손실 1.629)에서 요청에 따라 중지. 체크포인트는 50단계마다라 남은 것 없음
  - 3차(같은 설정, 20:18): PC 사용 중이라 데스크톱(DWM) 3.3 GB + Firefox가 VRAM을 써서 다시 넘침(단계당 161초, 전력 71 W) → 중지
  - 수정: `train.py`의 `AnswerOnlySFTTrainer` — 손실이 걸리는 답변 위치에서만 어휘(152k) 확률을 계산.
    기본 방식은 프롬프트 전체 ~3,300위치에 대해 계산해 약 3 GB를 더 씀. 결과: 단계당 25초(약 40% 빠름), 최대 8.4 GB, 손실 정규화 동일
  - 4차(20:31 시작): 48분 만에 완료, 손실 1.63 → 0.018, 최대 8.4 GB (`ft\out\train4.log`)
- **Ollama 등록 우회**: Ollama 0.40은 LoRA 어댑터를 따로 받지 않고(`LoRA adapters are no longer supported`),
  자체 양자화는 int4·int8·nvfp4 등만 지원합니다. 또 llama.cpp 양자화 실행 파일 다운로드는 자동 모드 안전 검사에서 막혔습니다.
  그래서 어댑터를 원본에 합친 뒤(`scripts\merge.py`, 1.6분) 파이썬 변환기로 **Q8_0** GGUF를 만들었습니다.
  공정한 비교를 위해 원본도 같은 Q8_0으로 만들어 `qwen3-8b-q8`로 등록했습니다.
- **결과 (평가 234건, 자세한 표는 `ft\README.md`)**:

  | 지표 | 운영 중 Q4 | 원본 Q8 | 학습 Q8 |
  |---|---|---|---|
  | 수치 검증 통과 | 85.9% | 87.0% | **96.0%** |
  | 형식 준수 | 22.6% | 24.3% | **98.9%** |
  | 핵심 숫자 포함 | 66.6% | 70.4% | **98.4%** |
  | 데이터에 없는 질문 거절 | 76.9% | 53.8% | **100%** |
  | 효과 없는 제안 조치 | 116/228 | 118/228 | **15/222** |
  | 정답 정책 일치 (정밀도/재현율) | 12.7/15.3% | 11.8/14.2% | 18.5/22.0% |
  | 제안 JSON 정상 / 제안 시간 | 100% / 6.0초 | 100% / 8.1초 | 98.2% / 8.7초 |

- **한계(자유 질문 6개 점검)**:
  - 답할 수 있는 질문을 거절함("가장 비싼 시간대" → "데이터에 없음")
  - "한 문장으로" 같은 형식 지시를 무시함
  - 다른 작업의 문구를 섞음
  - 원인: 정답을 규칙 템플릿으로만 만들어 다양성이 부족했음
  - 형식·핵심 숫자 지표는 템플릿 형식 기준이라 학습 모델에 유리함
- **교체 방법**: `.env`의 `LLM_LOCAL_MODEL=qwen3-8b-bems` → `deploy\start-public.cmd -RestartGateway`.
  그래픽 메모리 5 GB → 8.7 GB. 되돌리려면 `qwen3-8b-local`로 바꾸고 같은 명령을 실행합니다.
- **v2 아이디어**:
  - 질문 바꿔 쓰기
  - 형식 지시를 따르는 예시
  - 답할 수 있는 질문을 거절하지 않는 반례
  - 제안 JSON 키를 알파벳 순서로 학습(Ollama가 그 순서를 강제함)
  - "바꿀 필요 없음" 예시 늘리기

### 3.8 AI 비서 실제 질문 대비 (2026-11-11)

자세한 표와 이유는 `ft\README.md` "실제 질문 대비", 항목별 채점은 `ft\out\eval_realq_grades.json`.

- **점검**: 방문자가 칠 만한 질문 66개(`ft\data\realq.json`, 15개 범주)를 방문자와 같은 경로(로컬 모델만)로 물음.
  v2.1은 학습한 18가지 유형 밖의 질문을 가장 가까운 학습 틀로 답했음.
  - 예: "DR이 뭐야?" → DR 상태, "제일 싼 시간" → 지금이 제일 싸다, "B1 3층" → B3 3층 값, "빈 방 불 꺼줘" → 반복 출력
- **질문이 가는 길** (페이지 `aiRoute` → 게이트웨이 `chat`):
  1. 인사·감사·도움말, 데이터센터 냉방 끄기 요청 → 자동 안내(질문 언어로)
  2. 대상과 값이 분명한 명령 → 페이지가 직접 적용 카드("요청 해석 · 모델 없이")
  3. 모호한 제어 요청 → 제안 작업. 냉방 요청엔 설정온도 조치만, 조명 요청엔 조명 조치만 허용
  4. 전반 상태 질문 → 운영 브리핑
  5. 나머지 질문 → 게이트웨이에서 순서대로:
     - 요금 시간표 질문 → 데이터 조회
     - "X가 뭐야?" → 용어 정의 + 현재 값
     - "한도를 넘으면?" → FAQ
     - 그 밖 → 모델. 이때 질문이 가리키는 기록(`answerFacts`)과 용어집을 맥락에 붙이고, 요금 시간표는 모델에게 숨김
- **페이지 맥락 추가**: 층별 온도 `floors`, `rooms`(빈 방 조명), `ev`, `scenario`, `assets`,
  `today.highestGridImportAt`, `tariff.schedule`·`nextChange`(게이트웨이 전용)
- **출력 점검**: 반복 감지·중단, 지침·키 요청 거절, 질문 되풀이 줄·내부 메모 줄 삭제, 요약-조치 불일치 수정, 수치 검사 오탐 2종 수정
- **결과**: 사람 채점 41.5 → 62 / 66점, 오답 17 → 0, 모델이 답한 질문의 응답 시간 중앙값 2.0초.
  남은 문제는 모델 답의 보조 줄에 엉뚱한 조합이 섞이는 것(부분 정답 8개)
- **제안 지침**: 한 줄 추가를 시험했다가 재현율이 낮게 나와 되돌림. 지침은 학습 때와 같음
- **재시작 스크립트 수정**: `-RestartGateway`
  - 남은 게이트웨이 복사본을 모두 끄고, 두 포트가 비기를 기다림
  - 포트 확인을 실제 접속으로 바꿈: Windows가 듣는 소켓을 FinWait1로 보고해 "시작되지 않음"으로 오판했음
  - 하위 프로세스 번호는 부모 번호로 찾음
- **평가 도구**:
  - `ft\scripts\eval_realq_page.mjs`: 페이지 경유, 헤드리스 Chrome 9333
  - `ft\scripts\eval_realq.py`: 게이트웨이만
  - 페이지 훅 `MA_BEMS.ai.ask(질문, {tier})`·`reset()`·`route()`

## 4. 결정 기록 (왜 이렇게 했나)

| 결정 | 이유 |
|---|---|
| 공개 저장소에는 `public\` 사이트 파일만 | GitHub Pages 무료는 공개 저장소 필요. 서버 코드·키는 올리지 않음 |
| AI는 접근 키를 받은 사람만, judges 키는 로컬 모델만 | 방문자 때문에 API 비용이 나가지 않게 (사용자 선택) |
| Quick Tunnel (계정 없음) | 무료·즉시. 상시 운영은 자체 도메인 + 이름 있는 터널로 바꾸면 되고 `config.json` 한 줄만 달라짐 |
| 제안 유효성은 출력 제한(enum)으로 | 파인튜닝으로는 100% 보장 불가, 문법 제약은 결정적 |
| 시나리오는 URL 파라미터 + 새로 시작 | 재현 가능, 두 제어기가 처음부터 같은 조건, 평가 하네스와 같은 방식 |
| DR 프리셋 16시 | BMS 고정 방전(15시 시작)과 겹치는 측정 착시 제거 |
| 파인튜닝 정답은 규칙 생성 | 숫자 정확, 비용 0, 약관 위험 없음. 대신 모델은 규칙 수준을 넘지 못함 |
| 학습 중 공개 모드 끔 | GPU를 학습이 다 써야 함 (사용자 승인) |

## 5. 명령 모음

### 5.1 로컬에서 대시보드 보기
```
cd C:\Users\sunghyun\Desktop\MA-BEMS
.venv\Scripts\python server\mabems_server.py          → http://127.0.0.1:5178
```

### 5.2 공개 모드
```
deploy\start-public.cmd                  켜기 (Ollama 먼저 켜기, 절전 끄기)
deploy\stop-public.cmd                   끄기
deploy\start-public.cmd -RestartGateway  server\*.py 수정 후 게이트웨이만 재시작 (터널 주소 유지)
deploy\keys.cmd                          접근 키와 공유 링크
```

### 5.3 대시보드 수정 → 배포
```
build\ 의 모듈 수정 → python -I build\inject.py   (SYNTAX_OK가 나와야 함, 백업은 build\backup\)
deploy\publish-site.cmd                  index.html·data 복사 → 검사 → 푸시 → 1~2분 뒤 반영
```
주의: `inject.py`의 REPLACE 항목은 "새 문자열이 이미 있으면 건너뜀" 방식입니다. 이미 적용된 패치의 새 문자열을 바꿀 때는
`index.html`의 해당 부분도 같이 고쳐야 중복 삽입이 안 됩니다.

### 5.4 평가 재현 (`eval\README.md`)
```
chrome --headless=new --remote-debugging-port=9333 --user-data-dir=%TEMP%\mabems-cdp-9333 about:blank
cd eval   (또는 build)
node exp.mjs full "" 9      … node analyze.mjs
node exp.mjs scn_heatwave "scn=heatwave" 9   … node make_scn.mjs
```

### 5.5 파인튜닝 이어서 하기
```
:: 0) GPU 비우기 — 게임 등 GPU 프로그램 종료, 공개 모드 끄기, 모델 내리기
deploy\stop-public.cmd
ollama stop qwen3-8b-local

cd C:\Users\sunghyun\Desktop\MA-BEMS\ft
:: 1) 학습 (약 50분, 단계당 25초 안팎이어야 정상. 100초를 넘으면 VRAM이 넘친 것 → GPU 쓰는 프로그램을 닫거나 --max-len을 낮춤)
.venv\Scripts\python scripts\train.py --model models\Qwen3-8B --data data\train_sub.jsonl --out out\qwen3-bems-lora --epochs 1 --max-len 3328
:: 2) 합치기·변환·등록 (Ollama 0.40은 별도 어댑터 불가 → 합쳐서 Q8_0)
.venv\Scripts\python scripts\merge.py models\Qwen3-8B out\qwen3-bems-lora out\merged
.venv\Scripts\python llama.cpp\convert_hf_to_gguf.py out\merged --outtype q8_0 --outfile out\qwen3-bems-Q8_0.gguf
ollama create qwen3-8b-bems -f out\Modelfile
:: 3) 비교 (원본도 같은 Q8_0: convert_hf_to_gguf.py models\Qwen3-8B --outtype q8_0 → Modelfile.base-q8 → qwen3-8b-q8)
..\.venv\Scripts\python scripts\eval_ab.py data\eval.jsonl out\eval_q8.json qwen3-8b-q8
..\.venv\Scripts\python scripts\eval_ab.py data\eval.jsonl out\eval_bems.json qwen3-8b-bems
:: 4) 더 좋으면: .env의 LLM_LOCAL_MODEL=qwen3-8b-bems → deploy\start-public.cmd -RestartGateway
```
판단 기준 예: 형식 준수·핵심 숫자·효과 없는 조치·정답 정책 일치가 좋아지고, 수치 검증 통과율이 떨어지지 않을 것.
결과는 `ft\README.md` 아래에 기록하고, 발표에 쓰려면 한계(정답이 규칙에서 나옴)를 함께 적을 것.

## 6. 알려진 한계·주의

- 절감 수치는 시뮬레이션 기준. 실측 보정 전.
- AI는 운영자 PC가 켜져 있어야 동작. 절전·재부팅 시 `start-public` 다시 실행.
- Quick Tunnel은 Cloudflare가 테스트용으로 안내하는 방식. 스트리밍 없음, 동시 200건.
- 발표 영상이 공개되므로 키·공유 링크·`.env` 화면 노출 금지. 새면 `--revoke` 후 재발급.
- GPU 공유: 게임 등 다른 프로그램이 VRAM을 쓰면 학습이 시스템 메모리로 넘쳐 30배 이상 느려짐(Windows 공유 GPU 메모리).
- 로컬 모델 제안은 유효하지만 내용이 단순(빈 방 소등 위주). 좋은 제안은 관리자 키(Claude)에서.
- `ft\.venv`, `ft\models`(16 GB)는 용량이 큼. 파인튜닝을 접으면 지워도 됨.

## 7. 환경·계정 (비밀값 제외)

- PC: Windows 11 Pro, RTX 4070 Ti SUPER 16 GB, RAM 31 GB, C: 여유 약 150 GB
- 파이썬: `MA-BEMS\.venv`(3.12, 게이트웨이·평가), `ft\.venv`(3.12, 학습), anaconda 3.12(torch 2.5.1)
- Ollama 0.40.15: `qwen3-8b-local`(Qwen3-8B Q4_K_M, 기본), `qwen2.5:14b-instruct`
- GitHub CLI: `SungHyunC` 로그인(repo·workflow 권한). 커밋 메일은 noreply(`41741563+SungHyunC@users.noreply.github.com`)
- Anthropic API 키: `MA-BEMS\.env`의 `ANTHROPIC_API_KEY`(원본은 `Documents\BEMS-keys\`, 드라이브에 올리지 않음)
- 옛 BEMS 프로젝트들은 2026-11-09 구글 드라이브로 옮기고 로컬에서 정리함(복구는 휴지통 또는 `Desktop\_archived`)
