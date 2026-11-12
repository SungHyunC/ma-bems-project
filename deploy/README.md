# MA-BEMS 공개 배포 운영 가이드

- **공개 사이트**: https://sunghyunc.github.io/ma-bems/ (GitHub Pages · 저장소 `SungHyunC/ma-bems` = 이 폴더의 `site/`)
- **AI 비서**: 내 PC의 게이트웨이를 Cloudflare 터널로 공개, 접근 키가 있어야 씀

```
방문자 브라우저 ──HTTPS──> GitHub Pages (site/public)              시뮬레이션·에이전트·예측·FDD는 브라우저에서 실행
       │
       └─ AI 탭 ──HTTPS + 접근 키──> Cloudflare Quick Tunnel ──> 내 PC 127.0.0.1:5179 (게이트웨이 공개 API)
                                                                 ├─ 로컬 LLM: Ollama · Qwen3-8B (모든 키)
                                                                 └─ Claude (관리자 키만)
```

## 발표 당일 순서

1. **Ollama 앱을 켭니다** (작업 표시줄 트레이에 라마 아이콘).
2. **`deploy\start-public.cmd`를 더블클릭**합니다. "공개 모드가 켜졌습니다"가 나오면 성공입니다.
   게이트웨이를 켜고, 터널을 열고, 새 터널 주소를 공개 사이트 설정(`config.json`)에 올립니다.
3. **1분쯤 뒤** 공개 사이트의 AI 탭을 엽니다. 관리자 키 링크로 열면 바로 연결됩니다(`deploy\keys.cmd`).
4. 끝나면 **`deploy\stop-public.cmd`**. 공개 사이트에 "운영자 PC: 꺼짐"으로 표시됩니다.

PC가 절전에 들어가면 AI가 끊깁니다. 발표 중에는 Windows 설정 → 전원에서 절전을 꺼 두세요.
PC를 껐다 켜면 2번만 다시 하면 됩니다(주소가 바뀌어도 자동으로 반영).

## 접근 키

| 종류 | 접두사 | 쓸 수 있는 것 | 속도 제한 |
|---|---|---|---|
| 사용자 키 | `mbk_` | 로컬 모델(Qwen3-8B)만 | 키당 분당 10회, 하루 300회 |
| 관리자 키 | `mba_` | 로컬 모델 + Claude (시간당 60회 상한) | 키당 분당 30회 |

- 지금 있는 키: `judges`(사용자 키, 심사위원용), `owner`(관리자 키, 본인용). 키는 `MA-BEMS\.env`에 있습니다.
- **키와 공유 링크 보기**: `deploy\keys.cmd`. 공유 링크(`https://sunghyunc.github.io/ma-bems/#key=…`)로 들어오면
  키가 그 브라우저에만 저장되고 주소창에서는 바로 지워집니다. AI 탭에 키를 직접 붙여 넣어도 됩니다.
- **새 키**: `.venv\Scripts\python.exe server\mabems_server.py --new-key 이름` (Claude까지 허용하려면 `--admin`)
- **회수**: `.venv\Scripts\python.exe server\mabems_server.py --revoke 이름`. 게이트웨이를 재시작할 필요가 없습니다.
- 발표 영상은 공개되므로 **화면에 키나 공유 링크가 나오지 않게** 하세요. 키 입력란은 가려져 보입니다.
  링크가 퍼졌다면 그 키를 회수하고 새로 발급하면 됩니다.

## 보안 장치

- 공개 포트(5179)는 127.0.0.1에서만 열립니다. 외부에서는 Cloudflare 터널로만 들어올 수 있고, 공유기 포트 개방이 필요 없습니다.
- 공개 포트는 **파일을 하나도 내주지 않습니다**(`.env`, 코드 모두 404). API만 응답합니다.
- 모든 API 호출에 접근 키(`Authorization: Bearer …`)가 필요하고, 키 비교는 상수 시간으로 합니다.
- 브라우저 호출은 공개 사이트(`https://sunghyunc.github.io`)와 이 PC에서 연 페이지만 허용합니다(CORS·Origin 검사). 이 PC의 로컬 포트(5178)도 Origin과 Content-Type을 검사합니다.
- 프롬프트 추출 시도 검사는 모든 작업(질문·브리핑·설명·제안)에 적용되고, 스트리밍으로 보내기 전에 유출 검사를 합니다.
- 키별 속도 제한, 동시 처리 2건 제한, 요청 크기 256 KB 제한.
- Anthropic API 키는 `.env`에만 있고 저장소에 올라가지 않습니다. 배포 전 CI가 비밀값을 스캔합니다.

## 서버 코드(server\*.py)를 고친 뒤

`deploy\start-public.cmd -RestartGateway`: 게이트웨이만 다시 띄웁니다. 터널과 주소는 그대로라 사이트 설정을 바꿀 필요가 없습니다.

## 대시보드를 고친 뒤 다시 배포

`deploy\publish-site.cmd`를 실행합니다. `index.html`과 `data\`를 `site\public`으로 복사하고, 검사(페이지 스크립트 문법,
config 형식, 비밀값)를 통과하면 푸시합니다. GitHub Actions가 같은 검사를 한 번 더 한 뒤 1~2분 안에 배포합니다
(진행 상황: https://github.com/SungHyunC/ma-bems/actions).

## 다른 프로그램에서 내 로컬 LLM 쓰기

게이트웨이는 OpenAI 호환 엔드포인트(`/v1/chat/completions`, `/v1/models`)도 엽니다. **`/v1/chat/completions`는 관리자 키(`mba_`)만
쓸 수 있습니다.** 사용자 키(`mbk_`, 심사위원용)로 부르면 거절되고, 심사위원은 대시보드의 AI 탭(`/api/llm/chat`, 로컬 모델만)을 씁니다.
모델은 항상 로컬 Qwen3-8B이고, 스트리밍 없이 한 번에 답합니다. 터널 주소는 실행할 때마다 바뀌므로 `start-public` 출력이나 `site\public\config.json`에서 확인하세요.

```
curl https://<터널 주소>/v1/chat/completions ^
  -H "Authorization: Bearer mba_..." -H "Content-Type: application/json" ^
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"안녕\"}],\"max_tokens\":200}"
```

OpenAI 호환 클라이언트라면 base URL을 `https://<터널 주소>/v1`, API 키를 관리자 접근 키로 넣으면 됩니다.

## 한계와 업그레이드

- 지금 터널은 계정 없는 **Cloudflare Quick Tunnel**입니다. Cloudflare는 테스트·개발용으로 안내합니다.
  주소가 실행마다 바뀌고(스크립트가 자동 반영), 응답이 스트리밍 없이 한 번에 도착하며, 동시 요청 200건 제한이 있습니다.
- 상시 운영으로 가려면 Cloudflare 계정과 자체 도메인(연 1~2만 원)으로 **이름 있는 터널**을 쓰면 됩니다.
  주소가 고정되고 스트리밍도 됩니다. 이때 바뀌는 것은 `config.json`의 주소 한 줄뿐입니다.
- PC가 꺼지면 AI 비서만 꺼지고, 대시보드의 나머지 기능은 그대로 동작합니다.

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| AI 탭에 "운영자 PC: 꺼짐" | `start-public.cmd`를 다시 실행하고 1분 기다리기 |
| "키가 맞지 않습니다" | `keys.cmd`로 키 확인. 회수된 키일 수 있음 |
| 터널이 안 열림 | 인터넷 연결, `deploy\logs\tunnel.log` |
| 게이트웨이가 안 켜짐 | `deploy\logs\gateway.log`, `.venv`가 있는지 |
| 푸시 실패 | `gh auth status`로 GitHub 로그인 확인 |
| 로컬 모델이 꺼짐으로 표시 | Ollama 앱 켜기 |
