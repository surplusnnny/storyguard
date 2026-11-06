# StoryGuard 프로젝트 지침

AI 기반 1인 인디게임 유지보수 및 스토리 검증 에이전트. NEXT AI 해커톤(2026.11.5~6) 출품작.
핵심 메시지: **AI가 고치고, 알고리즘이 엔딩까지 검증한다.**

방침(2026-11-06, 사용자 결정): **LLM은 외부 API로 부르고, 교내 GPU(틸론)는 주피터에서 로고·배경 이미지를 만드는 데만 쓴다**(사용자 설명). 주최 측이 준 OpenAI 임시 키(2026-11-06 18:00 만료)로 `gpt-5.4-mini`를 부른다(`LLM_BASE_URL=https://api.openai.com/v1`, 키는 `.env`의 `LLM_API_KEY`). 시연 연쇄와 프리셋 3개의 AI 결과는 Supabase `llm_recordings`에 저장돼 있고, **공개 사이트는 `LLM_MODE=replay_first`**(저장된 결과가 있으면 그것을 "저장된 결과"로 표시하고, 없는 새 문구는 실시간으로 OpenAI를 호출)로 운영한다. 발표는 PPT로 하고 구현 화면은 AI가 심사한다(사용자 설명, 심사는 18:00 전에 끝남). 그래서 index.html에 자바스크립트 없이 읽히는 서비스 소개와 시연 결과 요약을 직접 넣었다. Claude API(`LLM_PROVIDER=anthropic`)와 Gemini는 결제 거부·불안정으로 쓰지 않는다(코드 경로는 남아 있음). 아래 구조·실행 절의 'GPU 서버' 설명은 같은 vLLM(OpenAI 호환) 코드 경로를 가리킨다.

## 구조
- `app/engine.py` 게임 규칙(이동, 퀘스트 받기/완료, 이벤트). 검증기와 플레이 화면이 함께 쓴다.
- `app/verifier.py` 엔딩 도달 판정(BFS), 막힌 지점 추적, 수정 전후 비교. **판정은 이 파일만 한다.**
- `app/llm_client.py` GPU 서버 vLLM(OpenAI 호환) 호출, 재시도·모델 전환·기록·저장 결과 대체.
- `app/prompts.py` 서비스 내부 프롬프트 B-1~B-4. `app/mock_llm.py` 서버 없이 쓰는 모의 응답(진짜 LLM 아님).
- `app/pipeline.py` 수정 → 검증 → 설명 → 재수정. `app/server.py` + `app/static/` 화면.
- `data/games/sample_game.json` 시연용 게임, `data/schema.json` 형식.
- `tools/` health_check(서버 시험), demo_check(시연 자동 점검), evaluate(평가 실험), fake_vllm(가짜 서버).
- `eval/requests.json` 평가 요청 20개(실험 전에 사람이 확인하고 reviewed를 true로 바꿈).

## 실행 (Windows)
- 처음: `setup.bat` / 실행: `run.bat` → http://localhost:8501 / 시험: `test.bat`
- 시연 점검: `demo_check.bat` / 서버 시험: `health_check.bat` / 평가: `evaluate.bat --show`
- 설정은 `.env` (`.env.example` 참고). `LLM_MODE=live`이어야 GPU 서버를 부른다.

## 작업 규칙 (괄호는 그 규칙이 막으려는 것)
1. 사실을 말한 문장 끝에는 괄호로 확인한 방법을 적는다. 예: (pytest 실행 결과), (git branch 출력) (확인하지 않은 것을 확인한 것처럼 말하는 것)
2. 확인하지 않은 것은 "확인하지 않았음"이라고 적고 짐작으로 채우지 않는다. (없는 답을 억지로 만드는 것)
3. "~가 없다"고 말할 때는 어디를 찾아봤는지 함께 적는다. (엉뚱한 곳을 보고 없다고 하는 것)
4. 작업을 시작하기 전에 git branch로 현재 브랜치를 확인하고, 어느 브랜치에서 만들지 먼저 말한 뒤 멈춘다. (master에 미완성 코드가 쌓이는 것)
5. LLM은 game.json만 수정한다. 엔딩 도달 판정은 verifier.py만 한다. engine.py의 규칙을 LLM 출력에 맞춰 바꾸지 않는다. (LLM이 "문제없다"고 지어내는 것)
6. LLM 호출이 실패하면 화면과 보고에 실패를 그대로 적는다. 이전 결과를 이번 결과처럼 보이게 두지 않는다. (실패가 성공처럼 보이는 것)
7. 발표와 보고에 쓰는 숫자는 `eval/results/` 의 CSV에서만 가져오고, CSV 경로를 함께 적는다. mock 결과는 숫자로 쓰지 않는다. (근거 없는 숫자)
8. 평가와 테스트에는 검증 엔진을 만들 때 쓴 사례와 겹치지 않는 사례를 쓴다. (시험한 범위 안에서만 옳은 것을 옳다고 하는 것)
9. 다른 결과나 도구의 말을 옮길 때는 줄이지 말고 원문을 따옴표로 옮긴다. (옮기면서 뜻이 바뀌는 것)
10. 새 기능보다 시연 시나리오가 먼저다. 발표 2시간 전부터는 새 기능을 넣지 않고 버그만 고친다. (시연 직전에 깨지는 것)
11. 모든 답과 보고는 한국어로 한다.
12. 세션을 마칠 때마다 완료한 단계, 결정과 그 이유, 버린 대안, 알려진 문제, 다음에 할 일을 `실행기록.md`에 추가한다.

## 시험
- `python -m pytest -q` 89개가 모두 통과해야 한다. 가짜 vLLM 서버를 자동으로 띄워 live 경로도 시험한다.
- 시험이 통과해도 화면은 브라우저에서 직접 눌러 확인한다.

## 배포
- 코드: https://github.com/surplusnnny/storyguard (공개 저장소). 공개 사이트: https://storyguard.vercel.app (Vercel 프로젝트 0510-a7b9/storyguard, 함수 지역 icn1)
- 배포 방법: master에 push하면 Vercel이 Production으로 자동 배포한다. 수동은 `vercel.cmd deploy --prod`(PowerShell은 vercel.ps1이 막혀 .cmd를 쓴다).
- 저장소: Supabase 프로젝트 storyguard(ref zycgmmedpkwyupjgpkix). 테이블 llm_calls, llm_recordings, saved_games(RLS 켬, 정책 없음). DB 변경은 `supabase/migrations`에 SQL을 두고 `supabase db push`로만 한다. `db reset` 금지.
- Vercel Production 환경 변수 이름: LLM_MODE, LLM_REQUEST_BUDGET, SUPABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_TIMEOUT. 값은 문서·채팅·로그에 적지 않는다. 확인은 `vercel.cmd env ls production`.
- 공개 사이트 AI 모드는 지금 replay_first다(Vercel `LLM_MODE`, 키는 Vercel `LLM_API_KEY`에 Sensitive로 등록). 심사가 끝나면 `LLM_API_KEY`를 삭제하고 `vercel.cmd env update LLM_MODE --environment production --value replay --yes` 후 `vercel.cmd deploy --prod`로 저장된 결과만 보이게 되돌린다. 키는 코드·GitHub·발표자료·화면 캡처에 넣지 않는다.
- 공개 사이트 점검: `python tools/demo_check.py --url https://storyguard.vercel.app` (실행할 때마다 Supabase llm_calls에 env=vercel 행이 6건 늘어난다).
- 자세한 계획과 결정: docs/DEPLOY-PLAN.md
- 보안(2026-11-06): 요청 본문 300KB·수정 문구 500자 제한, 보안 헤더(CSP 등), 실시간 AI 호출 한도(`LLM_LIVE_CALL_LIMIT`, 비우면 Vercel에서 시간당 60회, 저장된 결과 재생은 세지 않음). 키는 코드·GitHub·화면에 넣지 않는다(현재 파일과 전체 커밋 기록 검사에서 0건).
