# 구현 계획서 (IMPL-PLAN)

실행자는 이 계획서와 PRD.md, 실행기록.md를 함께 읽는다.

## 전역 규칙
- 각 단계가 끝나면 멈추고 사람의 확인을 기다린다.
- 단계마다 `stage-번호` 브랜치에서 작업하고, 확인이 끝나면 `--no-ff`로 master에 병합한다.
- 태스크마다 점검 명령이 통과한 뒤 그 태스크에서 바꾼 파일만 커밋한다.
- 계획과 다르게 정해야 할 일이 생기면 정하기 전에 먼저 묻는다.

## 현재 상태 (대회 전 사전 구현, 2026-10-28)
| 단계 | 상태 | 점검 명령 | 결과 |
| --- | --- | --- | --- |
| 1 게임 데이터·검증 엔진 | 완료 | `pytest -q tests/test_verifier.py` | 20개 통과 (2026-10-28 실행) |
| 2 LLM 연결·파이프라인 | 완료 (가짜 서버로 시험) | `pytest -q tests/test_llm_and_pipeline.py` | 15개 통과 (2026-10-28 실행) |
| 3 화면 | 완료 (mock 모드로 확인) | `demo_check.bat` | 6단계 성공 (mock, 가짜 서버 live 모두) |
| 4 평가 실험 | 도구 완료, **실제 실험은 대회장에서** | `evaluate.bat --show` → 확인 → `evaluate.bat` | 실제 GPU 결과 없음 |
| 5 시연 안정화 | 백업 모드·자동 점검 완료, **실제 서버로 리허설은 대회장에서** | `demo_check.bat --repeat 5` | 실제 GPU 결과 없음 |

**실제 GPU 서버로는 아직 한 번도 시험하지 않았다.** vLLM 주소, 모델 이름, JSON 모드 지원 여부를 모른다.

## 대회장에서 할 일 (순서대로)
1. `setup.bat` → 시험 35개 통과 확인.
2. `.env`에 `LLM_MODE=live`, `LLM_BASE_URL`, `LLM_MODELS` 입력 → `health_check.bat`.
   - JSON이 계속 실패하면 `LLM_JSON_MODE=0`으로 바꿔 다시 시험.
   - 응답이 30초를 넘으면 `LLM_TIMEOUT`을 늘리거나 작은 모델을 앞에 둔다.
3. `demo_check.bat --repeat 3` (실제 모델). 실패하면 실패한 단계의 오류 원문으로 원인 확인.
   - 실제 모델은 mock과 다르게 답하므로 수정안 문장, 재시도 횟수가 달라질 수 있다.
4. `evaluate.bat --show`로 평가 세트 20개를 사람이 확인 → `eval/requests.json`의 `reviewed`를 true → `evaluate.bat --models 모델A,모델B --retry both`.
5. 평가 결과로 기본 모델 순서(`LLM_MODELS`)를 정한다. 성공률을 정확도보다 앞에 둔다.
6. 실제 모델로 시연을 한 번 끝까지 하면 `data/recordings/`에 결과가 저장된다. 발표 중 서버가 죽으면 이 저장 결과가 "저장된 결과"로 표시되며 쓰인다.
7. 발표 2시간 전: 새 기능 금지, `demo_check.bat --repeat 5`.

## 태스크 목록 (사전 구현에서 한 것)
| # | 태스크 | 파일 | 점검 |
| --- | --- | --- | --- |
| 1 | game.json 형식과 샘플 게임 | data/schema.json, data/games/sample_game.json | 원본 검증 통과 |
| 2 | 규칙 엔진 | app/engine.py | 플레이 경로 15단계 |
| 3 | 검증기(BFS, 막힌 지점, 비교) | app/verifier.py | test_verifier.py |
| 4 | 스토리 지도 | app/graph.py | test_graph_marks_blocker |
| 5 | LLM 클라이언트 | app/llm_client.py, app/config.py | live 시험 7개 |
| 6 | 프롬프트 B-1~B-4 | app/prompts.py | 가짜 서버 파싱 |
| 7 | 모의 응답, 규칙 설명 | app/mock_llm.py | 시연 수정안 3개 모두 통과 |
| 8 | 파이프라인 | app/pipeline.py | 자동 재시도, 의도 유지 확인 |
| 9 | 서버와 화면 | app/server.py, app/static/* | demo_check, 브라우저 캡처 |
| 10 | 도구 | tools/*.py, *.bat, .claude/commands/* | 실행 확인 |

## PRD 대응표
| PRD 항목 | 태스크 |
| --- | --- |
| 2-1 LLM은 game.json만 수정 | 6(프롬프트 규칙 2), 8 |
| 2-2 판정은 코드 | 3, 8 |
| 2-3 실패 그대로 표시 | 5, 9 (결과 카드 "AI 응답 실패") |
| 2-4 호출 기록 | 5 (data/llm_calls.db) |
| 2-5 요청 유지 확인 | 8 (intent_check) |
| 4 시연 시나리오 | 7, 8, 9, demo_check |
| 6-4 평가 실험 | tools/evaluate.py, eval/requests.json |
| 6-5 백업 모드 | 5 (저장 결과 대체), 9 (출처 표시) |
