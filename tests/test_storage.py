"""기록 저장소(app/storage.py) 시험. Supabase는 httpx.MockTransport로 흉내 낸다(실제 서버를 부르지 않음)."""
import json

import httpx
import pytest

from app import config, llm_client, storage

URL = "https://example.supabase.co"


@pytest.fixture
def supa(monkeypatch):
    """Supabase 설정을 켜고, REST 요청을 메모리에서 처리하는 가짜 서버를 끼운다."""
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    state = {"requests": [], "recordings": {}, "fail": False}

    def handler(req: httpx.Request) -> httpx.Response:
        if state["fail"]:
            raise httpx.ConnectTimeout("supabase down", request=req)
        state["requests"].append(req)
        path = req.url.path
        if req.method == "POST" and path == "/rest/v1/llm_recordings":
            row = json.loads(req.content)
            state["recordings"][row["key"]] = row
            return httpx.Response(201)
        if req.method == "GET" and path == "/rest/v1/llm_recordings":
            key = req.url.params["key"].removeprefix("eq.")
            row = state["recordings"].get(key)
            return httpx.Response(200, json=[row] if row else [])
        if req.method == "POST":
            return httpx.Response(201)
        return httpx.Response(404)

    monkeypatch.setattr(storage, "_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler), timeout=2))
    return state


def test_backend_local_without_env():
    assert storage.backend() == "local"


def test_backend_none_on_vercel_without_supabase(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert storage.backend() == "none"
    assert storage.save_recording("k", "modify", "m", {"a": 1}) is False
    assert storage.load_recording("k") is None
    assert storage.log_call({"prompt_name": "modify", "source": "mock", "ok": True}) is False
    assert not config.RECORDINGS.exists()
    assert not config.DB_PATH.exists()


def test_backend_supabase_with_env(supa):
    assert storage.backend() == "supabase"


def test_recording_roundtrip_supabase(supa):
    data = {"modified_game": {"items": []}}
    assert storage.save_recording("abc123", "modify", "model-a", data) is True
    got = storage.load_recording("abc123")
    assert got["data"] == data and got["model"] == "model-a" and got["prompt_name"] == "modify"
    post = supa["requests"][0]
    assert post.headers["apikey"] == "sb_secret_test"
    assert "authorization" not in post.headers
    assert post.url.params["on_conflict"] == "key"
    assert "resolution=merge-duplicates" in post.headers["prefer"]


def test_log_call_posts_row(supa):
    assert storage.log_call({"run_tag": "t", "prompt_name": "explain", "model": "m", "source": "live",
                             "ok": True, "error_kind": "", "latency_ms": 12.5,
                             "prompt_tokens": 3, "completion_tokens": 4}) is True
    req = supa["requests"][0]
    assert req.method == "POST" and req.url.path == "/rest/v1/llm_calls"
    row = json.loads(req.content)
    assert row["prompt_name"] == "explain" and row["source"] == "live" and row["ok"] is True
    assert row["env"] == "local"


def test_supabase_down_does_not_break_call(supa, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    supa["fail"] = True
    assert storage.log_call({"prompt_name": "modify", "source": "mock", "ok": True}) is False
    r = llm_client.call_json("analyze", [{"role": "user", "content": "x"}],
                             context={"game": {"items": [], "areas": [], "quests": []}})
    assert r.ok is True and r.source == "mock"


def test_replay_reports_storage_error(supa, monkeypatch):
    """저장소에 닿지 못했을 때 '저장된 결과 없음'으로 뭉개지 않고 연결 실패를 그대로 알린다."""
    monkeypatch.setenv("LLM_MODE", "replay")
    supa["fail"] = True
    r = llm_client.call_json("modify", [{"role": "user", "content": "x"}])
    assert r.ok is False and r.source == "replay"
    assert r.error_kind == "storage_error"


def test_save_game_none_backend_reports_not_saved(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    out = storage.save_game({"items": []})
    assert out["saved"] is False and out["where"] == "" and out["message"]


def test_save_game_local_writes_file():
    out = storage.save_game({"items": ["x"]})
    assert out["saved"] is True
    p = config.DATA / "games" / "edited_game.json"
    assert json.loads(p.read_text(encoding="utf-8")) == {"items": ["x"]}
