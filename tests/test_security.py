"""보안 방어: 요청 크기·길이 제한, 실시간 AI 호출 한도, 보안 헤더."""
import pytest
from fastapi.testclient import TestClient

from app import llm_client
from app.server import app

c = TestClient(app)
MSGS = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]


def test_security_headers_on_pages_and_api():
    for path in ("/", "/api/status"):
        h = c.get(path).headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in c.get("/").headers["content-security-policy"]


def test_docs_page_is_not_broken_by_csp():
    assert "content-security-policy" not in c.get("/docs").headers


def test_oversized_body_is_rejected():
    r = c.post("/api/verify", json={"game": {"x": "a" * 400_000}})
    assert r.status_code == 413


def test_overlong_request_text_is_rejected():
    r = c.post("/api/modify", json={"game": {}, "request": "가" * 600})
    assert r.status_code == 422


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("LLM_MODELS", "m1")
    monkeypatch.setenv("LLM_RETRY_WAITS", "0")
    llm_client._live_calls.clear()
    calls = []

    def fake_post(model, messages):
        calls.append(1)
        return '{"a": 1}', {"prompt_tokens": 1, "completion_tokens": 1}
    monkeypatch.setattr(llm_client, "_post_vllm", fake_post)
    return calls


def test_live_call_limit_blocks_extra_calls_honestly(live, monkeypatch):
    monkeypatch.setenv("LLM_LIVE_CALL_LIMIT", "2")
    for i in range(2):
        assert llm_client.call_json("modify", MSGS + [{"role": "user", "content": str(i)}]).ok
    r = llm_client.call_json("modify", MSGS + [{"role": "user", "content": "x"}])
    assert r.ok is False and r.error_kind == "live_limit" and "한도" in r.error_message
    assert len(live) == 2  # 세 번째는 실제 호출을 하지 않았다


def test_limit_is_off_by_default_locally(live, monkeypatch):
    monkeypatch.delenv("LLM_LIVE_CALL_LIMIT", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    for i in range(5):
        assert llm_client.call_json("modify", MSGS + [{"role": "user", "content": str(i)}]).ok


def test_saved_results_still_work_when_limit_reached(live, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "replay_first")
    monkeypatch.setenv("LLM_LIVE_CALL_LIMIT", "1")
    assert llm_client.call_json("modify", MSGS).source == "live"       # 한도 1회를 쓴다
    r = llm_client.call_json("modify", MSGS)                            # 같은 요청은 저장된 결과
    assert r.ok and r.source == "replay"
    assert llm_client.call_json("modify", MSGS + [{"role": "user", "content": "new"}]).error_kind == "live_limit"
