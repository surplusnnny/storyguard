"""LLM_MODE=replay_first: 저장된 결과가 있으면 그것을, 없으면 실시간으로 부르고 성공하면 저장한다."""
import pytest

from app import llm_client

MSGS = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]


@pytest.fixture
def rf(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "replay_first")
    monkeypatch.setenv("LLM_MODELS", "m1")
    monkeypatch.setenv("LLM_RETRY_WAITS", "0")
    calls = []

    def fake_post(model, messages):
        calls.append(model)
        return '{"a": 1}', {"prompt_tokens": 3, "completion_tokens": 2}
    monkeypatch.setattr(llm_client, "_post_vllm", fake_post)
    return calls


def test_miss_calls_live_then_saved_result_is_used_first(rf):
    r1 = llm_client.call_json("modify", MSGS)
    assert r1.ok and r1.source == "live" and len(rf) == 1
    r2 = llm_client.call_json("modify", MSGS)
    assert r2.ok and r2.source == "replay" and r2.data == {"a": 1}
    assert len(rf) == 1  # 두 번째는 실시간 호출을 하지 않았다


def test_hit_never_calls_live(rf):
    llm_client.call_json("modify", MSGS)
    rf.clear()
    for _ in range(3):
        assert llm_client.call_json("modify", MSGS).source == "replay"
    assert rf == []


def test_miss_and_live_failure_is_reported_not_hidden(rf, monkeypatch):
    def boom(model, messages):
        raise RuntimeError("down")
    monkeypatch.setattr(llm_client, "_post_vllm", boom)
    r = llm_client.call_json("modify", MSGS)
    assert r.ok is False and r.source == "live" and r.error_kind == "server_error"


def test_health_does_not_probe_server_in_replay_first(monkeypatch):
    from fastapi.testclient import TestClient
    from app.server import app
    monkeypatch.setenv("LLM_MODE", "replay_first")

    def must_not_call():
        raise AssertionError("연결 확인이 서버를 불렀다")
    monkeypatch.setattr(llm_client, "list_models", must_not_call)
    j = TestClient(app).get("/api/health").json()
    assert j["ok"] is None
