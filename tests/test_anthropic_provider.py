"""LLM_PROVIDER=anthropic 경로. 진짜 API를 부르지 않고 가짜 클라이언트로 시험한다(돈이 들지 않음)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config, llm_client
from app.server import app

MSGS = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]


def _resp(text='{"ok": true}', stop="end_turn", extra_blocks=()):
    blocks = list(extra_blocks) + [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=blocks, stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=11, output_tokens=7))


class FakeClient:
    def __init__(self, behavior):
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)
        self._behavior = behavior

    def _create(self, **kw):
        self.calls.append(kw)
        return self._behavior(kw)


@pytest.fixture
def anthropic_env(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODELS", "claude-haiku-5-5")
    monkeypatch.setenv("LLM_RETRY_WAITS", "0")


def _use(monkeypatch, behavior):
    fake = FakeClient(behavior)
    monkeypatch.setattr(llm_client, "_anthropic_client", lambda: fake)
    return fake


def test_provider_defaults_to_vllm(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert config.provider() == "vllm"


def test_anthropic_call_splits_system_and_omits_temperature(anthropic_env, monkeypatch):
    fake = _use(monkeypatch, lambda kw: _resp())
    r = llm_client.call_json("modify", MSGS, run_tag="t")
    assert r.ok and r.source == "live" and r.data == {"ok": True}
    assert (r.prompt_tokens, r.completion_tokens) == (11, 7)
    kw = fake.calls[0]
    assert kw["system"] == "SYS"
    assert kw["messages"] == [{"role": "user", "content": "USER"}]
    assert kw["model"] == "claude-haiku-5-5"
    assert "temperature" not in kw
    assert kw["output_config"] == {"effort": "low"}


def test_anthropic_ignores_thinking_blocks(anthropic_env, monkeypatch):
    think = SimpleNamespace(type="thinking", thinking="")
    _use(monkeypatch, lambda kw: _resp('```json\n{"a": 1}\n```', extra_blocks=[think]))
    r = llm_client.call_json("modify", MSGS)
    assert r.ok and r.data == {"a": 1}


def test_anthropic_refusal_is_reported_not_hidden(anthropic_env, monkeypatch):
    _use(monkeypatch, lambda kw: _resp("", stop="refusal"))
    r = llm_client.call_json("modify", MSGS)
    assert r.ok is False and r.error_kind == "refusal"


def test_anthropic_429_is_classified_rate_limited(anthropic_env, monkeypatch):
    class Limited(Exception):
        status_code = 429

    def boom(kw):
        raise Limited("slow down")
    _use(monkeypatch, boom)
    r = llm_client.call_json("modify", MSGS)
    assert r.ok is False and r.error_kind == "rate_limited"


def test_status_reports_provider_and_hides_base_url(anthropic_env, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://10.0.0.5:8000")
    j = TestClient(app).get("/api/status").json()
    assert j["provider"] == "anthropic" and j["base_url"] == ""
