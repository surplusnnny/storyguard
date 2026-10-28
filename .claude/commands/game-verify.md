---
description: game.json을 verifier.py로 검증하고 엔딩 도달 여부, 막힌 지점, 의도하지 않은 변경을 표로 보여 준다 (파일은 고치지 않음)
argument-hint: "[게임 파일 경로, 생략하면 data/games/sample_game.json]"
allowed-tools: Bash(python:*), Bash(py:*), Read
---

검증만 하고 파일은 고치지 마.

1. 검사할 파일은 `$ARGUMENTS`이고, 비어 있으면 `data/games/sample_game.json`이다.
2. 검증 규칙을 여기에 다시 적지 말고 아래 명령으로 `app/verifier.py`를 실행해 결과를 얻는다.
   - Windows: `.venv\Scripts\python -c "import json,sys; from app.verifier import verify, load_game; r=verify(load_game(sys.argv[1])); print(json.dumps({k:r[k] for k in ['passed','reachable','blockers','schema_errors','warnings']}, ensure_ascii=False, indent=1)); print(len(r['path']))" <파일>`
3. 결과를 다음 표로 보여 준다. 칸마다 끝에 괄호로 확인 방법을 적는다. 예: (verifier.py 실행 결과)
   | 항목 | 결과 |
   | 엔딩 도달 | 가능/불가 |
   | 경로 길이 | n단계 |
   | 막힌 지점 | blocker마다 한 줄 |
   | 형식 오류 | 건수와 경로 |
   | 경고 | 엔딩에는 필요 없지만 도달 못 하는 퀘스트·지역 |
4. 판정은 verifier.py 결과만 옮긴다. 네가 게임을 읽고 따로 판단한 내용은 "참고(검증 엔진 판정 아님)"으로 구분해 적는다.
