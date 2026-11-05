# StoryGuard 배포 계획 (GitHub · Supabase · Vercel)

> **실행자에게:** 이 계획서를 단계(Task) 단위로 실행한다. 단계마다 체크박스(`- [ ]`)로 진행을 표시하고, 단계가 끝나면 멈추고 사람의 확인을 기다린다(IMPL-PLAN 전역 규칙). 실행 방식은 superpowers:executing-plans 또는 superpowers:subagent-driven-development.

**목표:** 로컬에서 돌던 StoryGuard를 GitHub에 두고, Supabase를 저장소로 쓰며, Vercel 공개 주소로 서비스한다. 로컬 `run.bat`과 시험은 지금처럼 그대로 돈다.

**구조:** FastAPI 앱 하나가 Vercel 함수 하나가 된다. 로컬 파일(SQLite·json)에 쓰던 세 가지(호출 기록, 저장된 결과, 저장한 게임)는 새 모듈 `app/storage.py`를 거쳐 Supabase(설정이 있을 때) 또는 로컬 파일(설정이 없을 때)에 쓴다. 브라우저는 Supabase에 직접 접근하지 않는다.

**기술:** Python 3.12(Vercel 기본) / FastAPI / httpx로 Supabase REST(PostgREST) 호출 / Supabase CLI 3.0.0 마이그레이션 / Vercel CLI 65.11.0

**근거 문서:** `CLAUDE.md`(작업 규칙), `PRD.md`, 노션 「StoryGuard 배포 가이드」, 아래 "확인한 사실"의 공식 문서

작성: 2026-11-05, 코드는 고치지 않고 계획만 세움.

---

## 0. 현재 상태 (2026-11-05 확인)

| 항목 | 상태 | 확인 방법 |
| --- | --- | --- |
| GitHub | private `surplusnnny/storyguard`, master에 `7fb8481` push 완료 → **stage-github 완료** | `git ls-remote origin` |
| Vercel | CLI 65.11.0, `surplusnnny` 로그인, 팀 0510(Hobby). 프로젝트 연결 전 | `vercel whoami`, `vercel teams ls` |
| Supabase | CLI 3.0.0, 프로젝트 `storyguard`(ref `zycgmmedpkwyupjgpkix`, ap-northeast-2, ACTIVE_HEALTHY). `supabase link` 전 | `supabase projects list` |
| 로컬 실행 환경 | 이 PC에 `.venv`, `.env` 없음 → `setup.bat` 먼저 필요 | `ls` |

## 1. 로컬 파일에 쓰는 곳 (전부)

| 파일:줄 | 무엇을 쓰나 | 배포 서버에서 실행되나 | 처리 |
| --- | --- | --- | --- |
| `app/llm_client.py:67-85` | SQLite `data/llm_calls.db`에 LLM 호출 기록(`_db`, `_log`) | 예 (모든 AI 호출) | → `storage.log_call` (Supabase `llm_calls`) |
| `app/llm_client.py:93-97` | `data/recordings/{key}.json` 저장된 결과(`_save_recording`) | 예 (live 성공 시) | → `storage.save_recording` (Supabase `llm_recordings`) |
| `app/llm_client.py:100-105` | 위 파일 읽기(`_load_recording`) | 예 (replay, 실패 시 대체) | → `storage.load_recording` |
| `app/server.py:66` | `/api/status`가 recordings 폴더의 파일 수를 셈 | 예 | → `storage.count_recordings` |
| `app/server.py:147-152` | `data/games/edited_game.json` 저장(`/api/save_game`) | 예 (화면 버튼) | → `storage.save_game` (Supabase `saved_games`) |
| `tools/evaluate.py:198-235` | `eval/results/<시각>/` CSV·PNG·md | 아니오 (로컬 도구) | **로컬에 그대로 둠** (CLAUDE.md 규칙 7: 발표 숫자의 근거는 이 CSV) |
| `tools/health_check.py:71-72` | `data/health_<시각>.json` | 아니오 (로컬 도구) | 그대로 둠 |

## 2. 확인한 사실 (공식 문서, 2026-11-05 조회)

| 항목 | 내용 | 출처 |
| --- | --- | --- |
| FastAPI 진입점 | `app.py`, `index.py`, `server.py`, `main.py`, `wsgi.py`, `asgi.py` 또는 `src/`·`app/` 안의 같은 이름. 최상위 변수 `app` | [Vercel FastAPI](https://vercel.com/docs/frameworks/backend/fastapi), [Python 런타임](https://vercel.com/docs/functions/runtimes/python) |
| 정적 파일 | `app.mount()`+`StaticFiles`는 빌드 때 CDN으로 올라감. 원본 폴더는 기본으로 함수 번들에도 남아 런타임에 읽을 수 있음 | Vercel FastAPI |
| Python 버전 | 3.12(기본), 3.13, 3.14. `requirements.txt` 지원 | Python 런타임 |
| 번들 크기 | Python 함수 500MB(압축 전) | [함수 제한](https://vercel.com/docs/functions/limitations) |
| 최대 실행 시간 | **Hobby: 기본 300초, 최대 300초.** 넘으면 504 `FUNCTION_INVOCATION_TIMEOUT` | 함수 제한 |
| 요청·응답 크기 | 4.5MB | 함수 제한 |
| 함수 지역 | 새 프로젝트는 기본 `iad1`(미국 워싱턴). `vercel.json`의 `regions`로 변경, Hobby는 1개 지역 | [지역 설정](https://vercel.com/docs/functions/configuring-functions/region) |
| 상대 경로 | `open()`의 상대 경로 기준은 프로젝트 루트 | Python 런타임 |
| Supabase 키 | `sb_secret_…`는 서버 전용이고 **RLS를 모두 우회**. 브라우저에서 쓰면 401. 키는 `apikey` 헤더로 보냄(`Authorization: Bearer` 아님). 새 키는 JWT가 아님 | [Supabase API Keys](https://supabase.com/docs/guides/api/api-keys) |

**배포 후 확인 결과** (2026-11-05 첫 배포 `dpl_2QHJq9yeebBNts5FCKrsgud1tBCY`, https://storyguard.vercel.app)
- 런타임 `VERCEL=1`: **있음.** `/api/status`가 `"store":"none"`을 돌려줌 (curl 결과)
- 루트 `main.py` 진입점과 `app` 패키지의 상대 import: **동작함.** `/`, `/api/games`, `/api/game/sample_game` 200 (curl 결과)
- 정적 파일: `/static/style.css`, `/static/app.js`, Galmuri 글꼴 200 (curl 결과)
- 파일시스템 쓰기 가능 여부: **확인하지 않았음.** 저장소가 `none`이라 쓰기를 시도하지 않으므로 지금은 필요 없음
- 시연 6단계: `demo_check.py --url https://storyguard.vercel.app` 모두 성공 (mock 모드)
- 공개 응답에 `sb_secret_`, `LLM_API_KEY`, 사설 IP 없음 (curl + grep, 0건)
- 참고: Git 연결 없이 `vercel deploy`로 올린 첫 배포가 Preview가 아니라 **Production**(`storyguard.vercel.app`)으로 올라감 (vercel inspect의 target)

## 3. Supabase 테이블 초안

모든 테이블에 RLS를 켜고 정책은 만들지 않는다. 서버만 secret 키로 접근하고, publishable/anon 키로는 아무것도 읽거나 쓸 수 없다.

| 테이블 | 컬럼 | 키 | 대체하는 것 |
| --- | --- | --- | --- |
| `llm_calls` | `id bigint identity`, `ts timestamptz default now()`, `run_tag text`, `prompt_name text`, `model text`, `source text`, `ok boolean`, `error_kind text`, `latency_ms real`, `prompt_tokens int`, `completion_tokens int`, `env text` (`local`/`vercel`) | `id` | SQLite `calls` 테이블(같은 컬럼 + `env`) |
| `llm_recordings` | `key text`, `prompt_name text`, `model text`, `data jsonb not null`, `saved_at timestamptz default now()` | `key` (upsert) | `data/recordings/{key}.json` |
| `saved_games` | `id bigint identity`, `created_at timestamptz default now()`, `name text`, `game jsonb not null`, `env text` | `id` | `data/games/edited_game.json` |

마이그레이션 파일: `supabase/migrations/<시각>_storyguard_storage.sql` (Task 1)

## 4. 공개 사이트의 AI 모드

| 상황 | 공개 사이트 `LLM_MODE` | 화면 | 동작 |
| --- | --- | --- | --- |
| GPU 서버가 공개 주소이고 Vercel에서 접속됨 | `live` | "실시간 GPU 연결" | 실제 호출. 실패하면 Supabase의 저장된 결과로 대체하고 "저장된 결과"로 표시 (지금 코드 그대로) |
| GPU 서버가 내부망이라 접속 안 됨 (**가능성 높음, 미확인**) | `replay` | "저장된 결과 재생" | 노트북에서 live로 한 번이라도 성공한 요청만 결과가 나온다. 새 요청은 "저장된 결과 없음" 실패로 그대로 표시 |
| 위 둘 다 어려움 | `mock` | "모의 모드 (발표 숫자로 쓰지 않음)" | 시연 시나리오만 동작 |

- replay가 공개 사이트에서 동작하려면 노트북에서 live로 시연할 때 `.env`에 SUPABASE 값이 있어야 한다. 그래야 저장된 결과가 Supabase에 쌓이고 공개 사이트가 그것을 읽는다.
- 어느 모드든 실패나 저장된 결과를 실시간 성공처럼 보이게 하지 않는다(CLAUDE.md 규칙 6). 지금의 출처 배지(`app/static/app.js:10` `SRC`)를 그대로 쓴다.

## 5. 실행 시간 계산 (Hobby 300초)

- `/api/modify`는 `call_json`을 최대 5번 부른다: modify 1 + explain 1 + repair 최대 3 (`app/pipeline.py:116`).
- `call_json` 1번의 최악 시간 ≈ 모델 수 × 2번 시도 × `LLM_TIMEOUT` + 대기(`LLM_RETRY_WAITS`, 2·4초).
  - 모델 1개, 30초: 약 62초 → /modify 최악 약 310초 (**300초 초과**)
  - 모델 2개, 30초: 약 126초 → 최악 약 630초 (**초과**)
- 대응(Task 2): 요청 하나의 전체 시간 한도를 두는 `LLM_REQUEST_BUDGET`(기본 0 = 끔, Vercel에서 240)을 추가한다. 한도를 넘으면 다음 재시도를 하지 않고 "시간 제한으로 중단"(`error_kind="budget_exceeded"`)을 그대로 보여 준다. `vercel.json`의 `maxDuration`은 300.
- `replay`/`mock` 모드는 몇 초 안에 끝나므로 해당하지 않는다.

---

## 전역 제약 (모든 단계에 적용)

- 모든 답과 보고는 한국어. 사실 뒤에는 확인 방법을 괄호로 적는다 (CLAUDE.md 1~3, 11).
- 단계마다 `stage-…` 브랜치에서 작업하고, 사람 확인 뒤 `--no-ff`로 master에 병합한다. 강제 push 금지.
- 판정은 `app/verifier.py`만 한다. `engine.py`·`verifier.py`의 규칙은 바꾸지 않는다 (CLAUDE.md 5).
- `.venv\Scripts\python -m pytest -q`는 기존 35개 + 새 시험이 모두 통과해야 한다. Supabase 환경 변수가 **없을 때** 지금과 똑같이 동작해야 한다.
- 비밀값(`SUPABASE_SECRET_KEY`, `LLM_API_KEY`, DB 비밀번호)은 코드·Git·로그·화면·채팅에 남기지 않는다. `app/static/`에는 어떤 키도 넣지 않는다.
- 새 패키지는 추가하지 않는다. Supabase는 이미 있는 `httpx`로 부른다.
- DB 변경은 `supabase/migrations` + `db push --dry-run` 확인 후 반영. `db reset` 금지.
- 해커톤 일정이 먼저다. 발표 2시간 전부터는 이 계획도 진행하지 않는다 (CLAUDE.md 10).

## 놓치기 쉬운 것 (각 단계 시험에 넣음)

1. **Supabase가 느리거나 죽었을 때:** 기록 저장 실패가 시연을 멈추면 안 된다. 2초 타임아웃 후 False를 반환하고 계속 진행한다 → Task 1 `test_supabase_down_does_not_break_call`.
2. **공개 사이트에서 GPU 서버 주소 노출:** `/api/status`의 `base_url`과 `/api/health`의 예외 문구에 내부 주소가 들어간다(`app/server.py:64,79`). Vercel에서는 숨긴다 → Task 2 `test_status_hides_base_url_on_vercel`.
3. **설정 없이 Vercel에 올렸을 때:** 쓰기 시도로 500이 나면 안 된다. 저장소 `none`으로 쓰기를 건너뛰고, 화면에 "기록 저장 안 됨"을 표시한다 → Task 1 `test_backend_none_on_vercel_without_supabase`.
4. **replay 키 불일치:** 로컬에서 저장한 결과를 공개 사이트가 찾으려면 키 계산(`_key`)이 같아야 한다. 저장소만 바꾸고 키 계산은 바꾸지 않는다 → Task 1 `test_recording_roundtrip_supabase`가 같은 key로 저장하고 읽는다.
5. **아무나 공개 사이트에서 live로 GPU를 부르는 것:** live 공개 시에만 해당한다. 이 계획에서는 막지 않고 "결정할 것" 5번으로 남긴다.

---

## Task 1 (stage-supabase): Supabase 저장소 연결

**파일**
- 만들기: `supabase/config.toml`(`supabase init`), `supabase/migrations/<시각>_storyguard_storage.sql`, `app/storage.py`, `tests/test_storage.py`
- 고치기: `app/llm_client.py:67-105`(`_db`·`_log`·`_save_recording`·`_load_recording`가 storage를 부르게), `app/server.py:62-66,147-152`, `app/config.py`(설정 함수 추가), `.env.example`(이름만 추가)

**인터페이스** (`app/storage.py`)
- `backend() -> str`: `"supabase"`(SUPABASE_URL과 SUPABASE_SECRET_KEY가 모두 있음) / `"none"`(둘 중 하나라도 없고 `config.on_vercel()`) / `"local"`(그 밖)
- `log_call(row: dict) -> bool`: row 키는 `llm_calls` 컬럼과 같음
- `save_recording(key: str, prompt_name: str, model: str, data: dict) -> bool`
- `load_recording(key: str) -> dict | None`: `{"prompt_name","model","data","saved_at"}` (지금 json 파일과 같은 모양)
- `count_recordings() -> int | None`: 셀 수 없으면 None
- `save_game(game: dict, name: str = "edited_game") -> dict`: `{"saved": bool, "where": "supabase"|"data/games/edited_game.json"|"", "message": str}`
- `_client() -> httpx.Client`: 시험에서 `httpx.MockTransport`로 바꿔 끼우는 지점. timeout은 `SUPABASE_TIMEOUT`(기본 2초)
- `app/config.py` 추가: `supabase_url() -> str`, `supabase_secret_key() -> str`, `on_vercel() -> bool`(`VERCEL` 환경 변수가 `"1"`)
- local 백엔드는 `config.DB_PATH`·`config.RECORDINGS`·`config.DATA`를 **호출할 때마다** 읽는다. `tests/conftest.py:16-22`의 monkeypatch가 계속 동작해야 하기 때문이다.

**Supabase REST 호출 규칙**
- 기본 주소 `{SUPABASE_URL}/rest/v1/<테이블>`, 헤더 `apikey: <secret>`, `Content-Type: application/json`
- 쓰기 `Prefer: return=minimal`. recordings는 `?on_conflict=key`와 `Prefer: resolution=merge-duplicates`로 upsert
- 읽기 `?key=eq.<key>&select=prompt_name,model,data,saved_at`
- 세기 `Prefer: count=exact` + `Range: 0-0` 응답의 `Content-Range` 끝 숫자

- [ ] **1-1 브랜치:** `git branch` 확인 → `git checkout -b stage-supabase` (사람 확인 후)
- [ ] **1-2 마이그레이션:** `supabase init`(없을 때만) → `supabase link --project-ref zycgmmedpkwyupjgpkix`(DB 비밀번호는 사람이 입력) → 3절의 표대로 SQL 작성. 테이블마다 `alter table … enable row level security;`, 정책 없음
- [ ] **1-3 dry-run:** `supabase db push --help`로 3.0.0 옵션 확인 → `supabase db push --dry-run`(원격 대상 옵션은 help 기준). 출력에 위 SQL 파일 하나만 있는지 확인 → **사람 확인** → 실제 반영
- [ ] **1-4 실패하는 시험 작성** (`tests/test_storage.py`)
  - `test_backend_local_without_env`: SUPABASE_* 없음, VERCEL 없음 → `backend() == "local"`
  - `test_backend_none_on_vercel_without_supabase`: `VERCEL=1`, SUPABASE_* 없음 → `"none"`, `save_recording(...) is False`, `load_recording("k") is None`, 파일이 생기지 않음
  - `test_backend_supabase_with_env`: 두 값 있음 → `"supabase"`
  - `test_recording_roundtrip_supabase`: MockTransport가 POST 본문을 저장하고 GET에 돌려줌 → `load_recording(k)["data"] == data`. 요청 헤더에 `apikey`가 있고 `Authorization`은 없음
  - `test_log_call_posts_row`: POST 경로가 `/rest/v1/llm_calls`, 본문에 `prompt_name`·`source`·`ok`·`env`
  - `test_supabase_down_does_not_break_call`: MockTransport가 `httpx.ConnectTimeout`을 냄 → `log_call` False, `llm_client.call_json`(mock 모드)은 `ok=True`
  - `test_save_game_none_backend_reports_not_saved`: `"none"`일 때 `{"saved": False, ...}`이고 예외 없음
- [ ] **1-5 실행해서 실패 확인:** `.venv\Scripts\python -m pytest -q tests/test_storage.py` → `ModuleNotFoundError: app.storage` 또는 FAIL
- [ ] **1-6 구현:** `app/storage.py`, `config.py` 함수. `llm_client`의 `_log`/`_save_recording`/`_load_recording`은 storage에 넘기기만 한다(`_key`는 그대로). `server.py`의 `/api/status`에 `"store": storage.backend()`를 추가하고 recordings 수는 `count_recordings()`. `/api/save_game`은 `storage.save_game` 결과를 그대로 반환
- [ ] **1-7 전체 시험:** `.venv\Scripts\python -m pytest -q` → 기존 35 + 새 7 = 42 passed
- [ ] **1-8 실제 확인 (사람이 `.env`에 SUPABASE_URL, SUPABASE_SECRET_KEY 입력 후):** `.venv\Scripts\python -c "from app import storage; print(storage.backend(), storage.save_recording('plan-check','t','m',{'a':1}), storage.load_recording('plan-check'))"` → `supabase True {...'data': {'a': 1}...}`. 확인 후 이 행은 Supabase Table Editor에서 지운다
- [ ] **1-9 시연 점검:** `demo_check.bat` → 6단계 성공. Supabase `llm_calls` 건수가 늘었는지 확인
- [ ] **1-10 커밋:** 바꾼 파일만 add → `feat: 기록·저장 결과·저장 게임을 Supabase에 저장(설정 없으면 로컬)` → 멈추고 확인 요청

## Task 2 (stage-vercel): Vercel에 맞추기와 Preview 배포

**파일**
- 만들기: `main.py`(루트, 한 줄: `from app.server import app`), `vercel.json`, `.vercelignore`, `requirements-dev.txt`, `tests/test_deploy.py`
- 고치기: `requirements.txt`(런타임만), `setup.bat`·`test.bat`(dev 설치), `app/server.py:62-80`(Vercel에서 주소 숨기기), `app/pipeline.py:116`(시간 한도), `app/config.py`(`request_budget()`), `app/static/app.js:36` 근처(저장소 상태 표시)

**정해 둔 값**
- `vercel.json`: `{"$schema": "https://openapi.vercel.sh/vercel.json", "regions": ["icn1"], "functions": {"main.py": {"maxDuration": 300}}}` (icn1 = 서울. Supabase가 ap-northeast-2라서. 지역 코드는 Vercel 지역 목록에서 확인)
- `requirements.txt` = fastapi, uvicorn, httpx, jsonschema, pydantic (지금 버전 하한 유지) / `requirements-dev.txt` = `-r requirements.txt` + pytest, matplotlib
- `.vercelignore`: `.venv/`, `tests/`, `eval/`, `docs/`, `tools/`, `data/recordings/`, `data/llm_calls.db`, `data/health_*.json`, `*.bat`, `supabase/`. **`data/games/`와 `data/schema.json`은 넣지 않는다(런타임에 필요)**
- `config.request_budget() -> float`: `LLM_REQUEST_BUDGET` 초, 기본 0(끔)
- 정적 파일은 지금 방식(`app.mount("/static", StaticFiles)`)을 유지한다. Vercel이 CDN으로 올린다. `public/`으로 옮기지 않는다(로컬 run.bat과 경로가 같게 유지하려고)

- [ ] **2-1 브랜치:** stage-supabase가 병합된 master에서 `git checkout -b stage-vercel` (사람 확인 후)
- [ ] **2-2 Vercel 연결:** `vercel link` → 새 프로젝트 이름은 사람에게 묻는다(제안: storyguard). `.vercel/`이 `.gitignore`에 있는지 확인(있음, 7fb8481)
- [ ] **2-3 실패하는 시험 작성** (`tests/test_deploy.py`)
  - `test_main_entrypoint_exposes_app`: `import main; assert main.app.title == "StoryGuard"`
  - `test_status_hides_base_url_on_vercel`: `VERCEL=1`, `LLM_MODE=live`, `LLM_BASE_URL=http://10.0.0.5:8000` → `/api/status`의 `base_url == ""`, 응답 전체 문자열에 `10.0.0.5` 없음
  - `test_health_error_hides_address_on_vercel`: `VERCEL=1`, live, 연결 실패 → message에 주소 없음
  - `test_budget_stops_retries`: `LLM_REQUEST_BUDGET=1`, 가짜 vLLM이 매번 엔딩을 깨는 수정을 돌려주고 1초 이상 지연 → `modify()` 결과의 시도 수 < 4, 마지막 기록 `error_kind == "budget_exceeded"`, `passed is False`
  - `test_vercel_json_values`: `vercel.json`의 regions == `["icn1"]`, `functions["main.py"]["maxDuration"] == 300`
- [ ] **2-4 실패 확인:** `.venv\Scripts\python -m pytest -q tests/test_deploy.py` → FAIL
- [ ] **2-5 구현:** 위 파일들. 시간 한도는 `pipeline.modify`의 재시도 반복 앞에서 경과 시간을 확인한다. 화면 상단 배지 옆에 `store`(Supabase / 로컬 / 기록 저장 안 됨)를 표시한다
- [ ] **2-6 전체 시험·시연:** `setup.bat`(dev 설치 확인) → `.venv\Scripts\python -m pytest -q` 47 passed → `demo_check.bat` 6단계 성공 → `run.bat`으로 화면 직접 확인
- [ ] **2-7 Preview 배포:** 커밋 → `git push -u origin stage-vercel` → Vercel Preview 주소 확인(GitHub 자동 연결 전이면 `vercel deploy`). 아직 환경 변수가 없으므로 `LLM_MODE` 기본값 mock, store `none`이 정상이다
- [ ] **2-8 Preview에서 확인:** `/`, `/static/style.css`, 글꼴, `/api/status`(`store: none` → `VERCEL=1` 확인), `/api/save_game`이 500이 아닌지, `vercel logs`에 쓰기 오류가 없는지. "확인하지 못한 것" 3가지에 결과를 적는다
- [ ] **2-9 멈추고 확인 요청**

## Task 3 (배포): 환경 변수 · 병합 · Production

- [ ] **3-1 환경 변수 목록:** 코드에서 읽는 이름 전체를 표로 만든다(`LLM_MODE`, `LLM_BASE_URL`, `LLM_MODELS`, `LLM_API_KEY`, `LLM_TIMEOUT`, `LLM_RETRY_WAITS`, `LLM_REPLAY_FALLBACK`, `LLM_JSON_MODE`, `LLM_MAX_TOKENS`, `LLM_REQUEST_BUDGET`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_TIMEOUT`)
- [ ] **3-2 등록:** 사람이 별도 창에서 `vercel env add <이름> production`으로 넣는다(값은 채팅·로그에 남기지 않음). 공개 사이트 기본값: `LLM_MODE`=결정 1, `LLM_REQUEST_BUDGET=240`. Preview에도 쓸 값은 `preview`에 따로
- [ ] **3-3 자동 배포 연결:** `vercel git connect` 상태 확인. `vercel link`만으로 연결됐다고 하지 않는다
- [ ] **3-4 병합:** 사람 확인 후 `git checkout master` → `git merge --no-ff stage-vercel` → `git push`(강제 push 금지) → Production 배포 Ready 확인
- [ ] **3-5 공개 사이트 검증:** `.venv\Scripts\python tools\demo_check.py --url <공개 주소>` → 결과 표. Supabase `llm_calls`에서 `env='vercel'` 건수 확인. 공개 HTML·JS·API 응답에 `sb_secret_`, `LLM_API_KEY` 값, GPU 주소가 없는지 확인
- [ ] **3-6 기록:** `CLAUDE.md`에 '배포' 절(저장소 URL, 공개 주소, 환경 변수 이름, 배포 방법)을 추가하고 `실행기록.md`에 결정·이유·알려진 문제를 적어 커밋

---

## 결정 사항 (2026-11-05, 사용자가 권장안 승인)

| # | 항목 | 결정 | 이유 |
| --- | --- | --- | --- |
| 1 | 공개 사이트 AI 모드 | **`replay`** | GPU 서버가 내부망일 가능성이 높음(미확인). 노트북에서 live로 성공한 요청만 나오고 화면에 "저장된 결과"로 표시. GPU 주소가 공개로 확인되면 다시 정한다 |
| 2 | Vercel 함수 지역 | **`icn1` (서울)** | Supabase(ap-northeast-2)와 가까움 |
| 3 | 저장한 게임(`/api/save_game`) | **공개 사이트에서도 Supabase `saved_games`에 저장** | 파일 쓰기 대신 DB에 남김 |
| 4 | Supabase 키 | **새 secret 키(`sb_secret_…`)** 를 대시보드 → Project Settings → API Keys에서 만들어 사용 | legacy `service_role`은 Supabase가 2026년 말 폐지 예정이라고 안내 |
| 5 | live 공개 시 접근 제한 | **지금은 만들지 않음** | replay 모드에서는 GPU를 부르지 않음. live로 바꿀 때 다시 정한다 |
| 6 | 진행 시점 | **해커톤 순서표(GPU 연결 시험 → demo-check 3회 → 평가 실험)를 마친 뒤 Task 1 시작** | 시연 안정화가 먼저 (CLAUDE.md 10) |

버린 대안: 공개 사이트 `mock` 모드(시연 시나리오는 항상 동작하지만 실제 AI 결과가 아님), 공개 사이트에서 저장 끄기, legacy `service_role` 키.
