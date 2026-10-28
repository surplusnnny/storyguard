---
description: 시연 시나리오 6단계를 자동으로 돌려 단계마다 성공/실패를 표로 보여 준다
argument-hint: "[반복 횟수, 생략하면 1]"
allowed-tools: Bash(python:*), Bash(py:*), Read
---

파일은 고치지 마. 실행하고 보고만 해.

1. `tools/demo_check.py`를 실행한다. 반복 횟수는 `$ARGUMENTS`(비어 있으면 1).
   - Windows: `.venv\Scripts\python tools\demo_check.py --repeat <횟수>`
   - 서버를 따로 켜 둔 상태에서 확인하려면 `--url http://localhost:8501`을 붙인다.
2. 출력을 줄이지 말고 표로 옮긴다: 회차 | 단계 | 성공/실패 | 시간 | 내용.
3. 맨 위에 현재 모드(live / mock / replay)와 모델을 적는다. mock이면 "모의 모드 결과라 발표 숫자로 쓰지 않음"을 붙인다.
4. 실패한 단계가 있으면 원인을 추측하지 말고 출력된 오류 원문을 따옴표로 옮긴다.
   GPU 서버 문제로 보이면 `/game-verify`가 아니라 `tools/health_check.py`를 실행해 보자고 제안한다.
