-- StoryGuard 저장소 (docs/DEPLOY-PLAN.md 3절)
-- 서버(FastAPI)만 secret 키로 접근한다. RLS를 켜고 정책은 만들지 않는다:
-- publishable/anon 키로는 읽기·쓰기 모두 막히고, secret 키는 RLS를 우회한다.

-- LLM 호출 기록 (SQLite calls 테이블과 같은 컬럼 + env)
create table if not exists public.llm_calls (
  id bigint generated always as identity primary key,
  ts timestamptz not null default now(),
  run_tag text,
  prompt_name text,
  model text,
  source text,
  ok boolean,
  error_kind text,
  latency_ms real,
  prompt_tokens integer,
  completion_tokens integer,
  env text
);

-- 실시간 호출에 성공한 결과 (replay와 실패 시 대체에 씀). key는 llm_client._key()
create table if not exists public.llm_recordings (
  key text primary key,
  prompt_name text,
  model text,
  data jsonb not null,
  saved_at timestamptz not null default now()
);

-- 화면의 "수정본 저장"
create table if not exists public.saved_games (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  name text,
  game jsonb not null,
  env text
);

alter table public.llm_calls enable row level security;
alter table public.llm_recordings enable row level security;
alter table public.saved_games enable row level security;
