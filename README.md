# StoryGuard

AI가 게임을 고치고, 알고리즘이 엔딩까지 갈 수 있는지 검증하는 1인 인디게임 유지보수 도구.
NEXT AI 해커톤(한양여자대학교 × Tilon × KTNF GPU, 2026.11.5~6) 출품작.

## Windows 노트북에서 처음 실행

필요한 것: Python 3.10 이상 (`py --version`으로 확인). 없으면 PowerShell에서 `winget install Python.Python.3.13`.

1. 이 폴더를 원하는 곳에 압축 해제
2. `setup.bat` 더블클릭 → 가상환경, 패키지 설치, 시험 89개 실행 (마지막에 `89 passed`가 보여야 함)
3. `run.bat` 더블클릭 → 브라우저가 http://localhost:8501 을 연다

처음에는 `.env`가 `LLM_MODE=mock`(모의 모드)이라 GPU 서버 없이 시연 흐름을 연습할 수 있다. 화면 상단에 "모의 모드"가 표시된다.

## 대회장에서 GPU 서버 연결

`.env`를 메모장으로 열어 바꾼다.

```
LLM_MODE=live
LLM_BASE_URL=http://(교육에서 받은 서버 주소):(포트)
LLM_MODELS=(모델 이름1),(모델 이름2)
LLM_API_KEY=(받았으면 입력, 없으면 EMPTY)
```

그다음 `health_check.bat` → 모델마다 JSON 응답, 게임 수정, 시간이 표로 나온다.
JSON이 계속 실패하면 `.env`에서 `LLM_JSON_MODE=0`으로 바꿔 다시 시험한다.

## 자주 쓰는 것

| 파일 | 하는 일 |
| --- | --- |
| `run.bat` | 화면 실행 |
| `demo_check.bat` | 시연 6단계 자동 점검 (`demo_check.bat --repeat 5`) |
| `health_check.bat` | GPU 서버 연결 시험 |
| `evaluate.bat --show` | 평가 세트 20개 보기 (실험 전 확인) |
| `evaluate.bat --models A,B --retry both` | 평가 실험, 결과는 `eval/results/` |
| `run_fake_llm.bat` | 가짜 vLLM 서버(연습용). `.env`를 `LLM_MODE=live`, `LLM_BASE_URL=http://127.0.0.1:8001`, `LLM_MODELS=fake-ok`로 두면 live 경로 연습 |
| `test.bat` | 시험 89개 |

## 시연 순서 (3분)
1. 화면을 연다. 지도에 "원본 게임: 엔딩까지 갈 수 있습니다".
2. 오른쪽 첫 번째 예시 "두 번째 퀘스트 보상을 황금 열쇠에서 마법 지팡이로 바꿔 줘" → 수정 요청.
3. "엔딩에 갈 수 없습니다", 지도에서 마지막 던전이 빨간색, 황금 열쇠가 빨간 점선. 왼쪽 게임 창에서 실제로 막히는 것을 보여 줄 수 있다.
4. 수정안 하나를 누른다 → "고쳐서 통과했습니다", 엔딩까지 경로가 차례로 켜짐.
5. 평가 결과 그래프(`eval/results/<시각>/chart.png`)로 숫자를 보여 준다.

## 발표 중 GPU 서버가 죽으면
실제 모델로 한 번이라도 성공한 요청은 `data/recordings/`에 저장된다. 실시간 호출이 실패하면 저장된 결과를 쓰고, 화면에 "저장된 결과"로 표시된다. 저장된 결과도 없으면 "AI 응답 실패"와 원인이 그대로 뜬다.
`.env`를 `LLM_MODE=replay`로 바꾸면 처음부터 저장된 결과만 쓴다.

## 구조
자세한 구조와 작업 규칙은 `CLAUDE.md`, 요구 사항은 `PRD.md`, 진행 상황은 `IMPL-PLAN.md`, 결정 기록은 `실행기록.md`.

## 글꼴
Galmuri11, Pretendard (SIL Open Font License 1.1). `app/static/fonts/README.txt` 참고.
