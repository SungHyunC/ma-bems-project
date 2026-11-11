# MA-BEMS · 멀티에이전트 건물 에너지 관리 시스템

[English](README.md) · 한국어

**라이브 대시보드: https://sunghyunc.github.io/ma-bems/**
(공개 사이트 배포 저장소는 [SungHyunC/ma-bems](https://github.com/SungHyunC/ma-bems), 이 저장소는 프로젝트 전체 원본)

6개 에이전트(코디네이터·HVAC·조명·태양광·ESS·EV 충전)가 15분마다 관찰→계획→협상→실행→검증을 반복하며
가상 캠퍼스(Helio Campus)의 피크·요금·쾌적을 함께 관리합니다. 같은 날씨·재실·EV·DR 신호로 룰 기반 BMS를 나란히 돌려
차이만 비교합니다(반사실 그림자 실행). 고려대 세종 2026-2 기업연계형 캡스톤디자인 출품작입니다.

## 데모 영상 · 설명서

- **데모 영상** (2분 54초, 한국어 내레이션·자막):
  [1080p, 83 MB](https://github.com/SungHyunC/ma-bems-project/releases/download/demo-2026-11-11/ma-bems-demo-ko.mp4) ·
  [720p, 18 MB](https://github.com/SungHyunC/ma-bems-project/releases/download/demo-2026-11-11/ma-bems-demo-ko-720p.mp4)
  ([릴리스](https://github.com/SungHyunC/ma-bems-project/releases/tag/demo-2026-11-11))
  - 장면: 개요 → 상단 지표·기준선 비교 → 에이전트·결정 로그 → 건물 선택 → 수요반응 시나리오 → AI 비서(요금 조회, 로컬 모델 답변, 적용 카드) → 검증·근거
  - 대시보드를 실제로 조작하며 녹화했고, AI 장면의 답은 로컬 모델이 그 자리에서 만든 것입니다.
    음성은 Windows 기본 한국어 음성이고, 다시 만드는 방법은 [demo/README.md](demo/README.md)에 있습니다.
- **프로젝트 설명서 PDF** (A4 10쪽): [docs/ma-bems-overview-ko.pdf](docs/ma-bems-overview-ko.pdf)
  - 동작 방식, 입력·출력, 성능, 장점과 한계, 다음 단계
  - 원본 HTML: [docs/ma-bems-overview-ko.html](docs/ma-bems-overview-ko.html)

## 결과 한눈에 (시뮬레이션 기준, 9일 × 1분 단위, 1~8일 채점, 95% 신뢰구간)

| 항목 | 에이전트 vs 룰 기반 BMS |
|---|---|
| 전력량요금 절감 | 16.7 ± 0.2% |
| 최대 수요 | 959 vs 1,170 kW (한도 1,000 kW 초과 0분 vs 1,996분) |
| 쾌적 | 99.9% vs 100% |
| 수요 예측 | CV(RMSE) 11.0%, NMBE 0.0% (ASHRAE Guideline 14 기준 이내) |
| 센서 고장 감지 | 정상 운영 오경보 0건, 훈련 63/64 감지 |

시나리오 9종(폭염·흐린 날·DR·한도 하향·EV 몰림·휴일·센서 고장·최악의 날)별 결과와 한계는 [eval/README.md](eval/README.md).
절감은 아직 계량 데이터로 보정하지 않은 시뮬레이션 값입니다.

## 구성

| 폴더 | 내용 |
|---|---|
| `index.html` | 대시보드 (단일 파일, Three.js). 브라우저에서 시뮬레이션·에이전트·예측·고장 감지가 모두 돌아감 |
| `server/` | 로컬 서버 + LLM 게이트웨이: 로컬 Qwen3-8B(Ollama) 우선, Claude 보조, 답변 숫자 검증, 질문 처리(요금 조회·용어 정의·출력 점검, `assist.py`), 공개 API(접근 키·CORS·속도 제한) |
| `build/` | 대시보드 빌드 원본 — `python -I build\inject.py`가 모듈을 `index.html`에 끼워 넣음. 평가 하네스와 원본 결과 |
| `eval/` | 성능 평가 재현 방법과 결과표 |
| `deploy/` | 공개 배포 스크립트(GitHub Pages + Cloudflare 터널, 접근 키) — 운영 가이드 [deploy/README.md](deploy/README.md) |
| `ft/` | 로컬 LLM 파인튜닝(QLoRA): 시뮬레이터로 만든 학습 데이터, 학습·평가 코드, 결과 — [ft/README.md](ft/README.md) |
| `deck/` | 경진대회 발표자료 원본(슬라이드 HTML) |
| `docs/` | 프로젝트 설명서(PDF·HTML). 데모 영상 파일은 용량 때문에 Releases에 둠 |
| `demo/` | 데모 영상 제작: 대본(`script.json`), 한국어 음성(`tts.ps1`), 자동 녹화(`record.mjs`), 합성(`assemble.py`) |
| `data/` | BDG2 실측 샘플(CC BY 4.0) |
| [`HANDOFF.md`](HANDOFF.md) | 인수인계: 현재 상태, 결정 이유, 명령 모음, 남은 일 |

## 실행

```
python -m venv .venv && .venv\Scripts\pip install anthropic
copy .env.example .env          (ANTHROPIC_API_KEY 등 채우기, Ollama에 qwen3 8B 모델)
.venv\Scripts\python server\mabems_server.py      → http://127.0.0.1:5178
```

AI 비서 없이 보기만 하려면 `index.html`을 정적 서버로 열어도 됩니다(시뮬레이션은 브라우저에서 동작).

## 저장소에 없는 것

- `.env`(API 키·접근 키), Python 가상환경, `deploy/bin/cloudflared.exe`(Cloudflare 공식 릴리스에서 받음)
- 파인튜닝 기반 가중치(`Qwen/Qwen3-8B`, Hugging Face)와 합친 모델·GGUF(수십 GB)
- 학습된 LoRA 어댑터는 이 저장소의 **Releases**에 있습니다
