"""기록 저장소: LLM 호출 기록, 저장된 결과(replay), 저장한 게임.

어디에 쓰는지는 backend()가 정한다.
- "supabase": SUPABASE_URL과 SUPABASE_SECRET_KEY가 모두 있을 때. Supabase REST(PostgREST)를 httpx로 부른다.
  secret 키는 apikey 헤더로만 보낸다(Authorization: Bearer 아님, Supabase API Keys 문서).
- "local": 그 밖의 로컬 실행. 지금까지처럼 SQLite(data/llm_calls.db)와 json 파일(data/recordings)을 쓴다.
- "none": Vercel에서 Supabase 설정이 없을 때. 파일을 쓰지 않고(서버리스라 남지 않음) False를 돌려준다.

기록 저장 실패는 시연을 멈추지 않는다(False 반환). 다만 저장된 결과를 읽다가 저장소에 닿지 못하면
StorageError를 내서, 부르는 쪽이 "저장된 결과 없음"과 "저장소 연결 실패"를 구분해 보여 줄 수 있게 한다.
로컬 경로는 시험이 config를 바꿔 끼울 수 있게 부를 때마다 config에서 읽는다.
"""
from __future__ import annotations

import json
import sqlite3
import time

import httpx

from . import config


class StorageError(Exception):
    """저장소(Supabase)에 닿지 못했거나 오류 응답을 받음."""


def backend() -> str:
    if config.supabase_url() and config.supabase_secret_key():
        return "supabase"
    if config.on_vercel():
        return "none"
    return "local"


def _env() -> str:
    return "vercel" if config.on_vercel() else "local"


# ------------------------------------------------------------------ Supabase REST
def _client() -> httpx.Client:
    """시험에서 httpx.MockTransport를 끼운 Client로 바꿔 끼우는 지점."""
    return httpx.Client(timeout=config.supabase_timeout())


def _url(table: str) -> str:
    return f"{config.supabase_url()}/rest/v1/{table}"


def _headers(prefer: str = "") -> dict:
    h = {"apikey": config.supabase_secret_key(), "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    return h


def _insert(table: str, row: dict, params: dict | None = None, prefer: str = "return=minimal") -> bool:
    try:
        with _client() as c:
            r = c.post(_url(table), params=params, headers=_headers(prefer), json=row)
        return r.status_code < 300
    except httpx.HTTPError:
        return False


def _select(table: str, params: dict, prefer: str = "") -> httpx.Response:
    try:
        with _client() as c:
            r = c.get(_url(table), params=params, headers=_headers(prefer))
    except httpx.HTTPError as exc:
        raise StorageError(f"저장소에 연결하지 못함: {type(exc).__name__}") from exc
    if r.status_code >= 300:
        raise StorageError(f"저장소 오류 응답 {r.status_code}")
    return r


# ------------------------------------------------------------------ 로컬 파일
def _sqlite():
    config.DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS calls (
        ts REAL, run_tag TEXT, prompt_name TEXT, model TEXT, source TEXT, ok INTEGER,
        error_kind TEXT, latency_ms REAL, prompt_tokens INTEGER, completion_tokens INTEGER)""")
    return con


# ------------------------------------------------------------------ 공개 함수
def log_call(row: dict) -> bool:
    """LLM 호출 1건 기록. row 키: run_tag, prompt_name, model, source, ok, error_kind,
    latency_ms, prompt_tokens, completion_tokens."""
    b = backend()
    if b == "supabase":
        return _insert("llm_calls", {**row, "env": _env()})
    if b == "none":
        return False
    try:
        con = _sqlite()
        con.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (time.time(), row.get("run_tag", ""), row.get("prompt_name", ""), row.get("model", ""),
                     row.get("source", ""), int(bool(row.get("ok"))), row.get("error_kind", ""),
                     row.get("latency_ms", 0.0), row.get("prompt_tokens", 0), row.get("completion_tokens", 0)))
        con.commit()
        con.close()
        return True
    except sqlite3.Error:
        return False


def save_recording(key: str, prompt_name: str, model: str, data: dict) -> bool:
    b = backend()
    if b == "supabase":
        return _insert("llm_recordings", {"key": key, "prompt_name": prompt_name, "model": model, "data": data},
                       params={"on_conflict": "key"}, prefer="resolution=merge-duplicates,return=minimal")
    if b == "none":
        return False
    config.RECORDINGS.mkdir(parents=True, exist_ok=True)
    (config.RECORDINGS / f"{key}.json").write_text(
        json.dumps({"prompt_name": prompt_name, "model": model, "data": data, "saved_at": time.time()},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def load_recording(key: str) -> dict | None:
    """저장된 결과 {"prompt_name","model","data","saved_at"} 또는 None(없음).
    Supabase에 닿지 못하면 StorageError."""
    b = backend()
    if b == "supabase":
        r = _select("llm_recordings", {"key": f"eq.{key}", "select": "prompt_name,model,data,saved_at"})
        rows = r.json()
        return rows[0] if rows else None
    if b == "none":
        return None
    p = config.RECORDINGS / f"{key}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def count_recordings() -> int | None:
    """저장된 결과 수. 셀 수 없으면 None."""
    b = backend()
    if b == "supabase":
        try:
            r = _select("llm_recordings", {"select": "key"}, prefer="count=exact")
        except StorageError:
            return None
        total = r.headers.get("content-range", "").rsplit("/", 1)[-1]
        return int(total) if total.isdigit() else None
    if b == "none":
        return None
    return len(list(config.RECORDINGS.glob("*.json"))) if config.RECORDINGS.exists() else 0


def save_game(game: dict, name: str = "edited_game") -> dict:
    """화면의 "수정본 저장". {"saved": bool, "where": str, "message": str}"""
    b = backend()
    if b == "supabase":
        ok = _insert("saved_games", {"name": name, "game": game, "env": _env()})
        return {"saved": ok, "where": "supabase" if ok else "",
                "message": "Supabase에 저장했습니다." if ok else "저장소에 연결하지 못해 저장하지 못했습니다."}
    if b == "none":
        return {"saved": False, "where": "", "message": "기록 저장소가 설정되지 않아 저장하지 않았습니다."}
    games = config.DATA / "games"
    games.mkdir(parents=True, exist_ok=True)
    p = games / f"{name}.json"
    p.write_text(json.dumps(game, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        where = str(p.relative_to(config.ROOT))
    except ValueError:
        where = str(p)
    return {"saved": True, "where": where, "message": f"{where}에 저장했습니다."}
