# 데모 영상 만들기

결과물: `docs\ma-bems-demo-ko.mp4` (2분 36초, 1920×1080, 한국어 내레이션 + 자막)

맥에서도 됩니다.
- 음성은 `say -v Yuna`가 모든 문장을 같은 목소리와 같은 속도로 읽습니다.
- 자막 글꼴은 Apple SD Gothic Neo입니다.
- Node 20에서는 `node --experimental-websocket demo/record.mjs W`로 실행합니다.
- Chrome은 `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --remote-debugging-port=9444 --user-data-dir=<임시 폴더> --hide-scrollbars --mute-audio about:blank`로 켭니다.
- AI 장면은 게이트웨이가 `LLM_LOCAL_BASE_URL`·`LLM_LOCAL_MODEL` 환경 변수로 가리키는 Ollama 모델이 답합니다.
- 2026-11-12 영상은 맥에서 만들었고, AI 장면은 Modal GPU에서 v2.2 Q8_0 모델을 Ollama로 돌렸습니다.

대시보드를 헤드리스 Chrome으로 직접 조작하며 녹화하고, Windows 기본 한국어 음성(Microsoft Heami)으로 내레이션을 만든 뒤,
ffmpeg로 화면·음성·자막을 합칩니다. 다운로드나 외부 음성 서비스는 쓰지 않습니다.

## 고치는 곳

- 대본과 장면 동선: `script.json`
  - `text` = 자막
  - `say` = 음성이 읽을 문장. 숫자·영문 약어는 한글로 씁니다(예: "엠에이 벰스", "십육 점 칠 퍼센트")
  - `do` = 그 문장이 시작될 때 할 페이지 동작
  - `after` = 문장 시작 몇 초 뒤에 할 동작
- 페이지 동작(강조, 클릭, AI 질문 입력 등): `record.mjs`의 `ACT`

## 다시 만들기

준비:
- 게이트웨이가 켜져 있어야 합니다(`http://127.0.0.1:5178`). AI 장면에서 로컬 모델이 실제로 답합니다.
- 작업 폴더 `W`는 프레임 저장용이라 1 GB 정도 여유가 필요합니다.

1. 녹화용 Chrome을 켭니다(평가용 9333과 다른 포트):
   `chrome --headless=new --remote-debugging-port=9444 --user-data-dir=%TEMP%\mabems-demo-9444 --hide-scrollbars --mute-audio about:blank`
2. 내레이션 음성, 시간표, 자막 만들기:
   `python demo\timeline.py W` (PIL이 있는 파이썬, 예: anaconda)
3. 녹화:
   `node demo\record.mjs W`
   - 맨 뒤에 `dry`를 붙이면 동작마다 스크린샷만 찍어 동선을 빠르게 확인합니다.
   - `only=s2,s3`처럼 장면만 다시 찍을 수 있습니다. 같은 페이지에서 이어지는 장면은 주소가 있는 장면부터 함께 다시 찍으세요(s1~s5a, s5b, s6~s8).
4. 합치기:
   `python demo\assemble.py W docs\ma-bems-demo-ko.mp4`
