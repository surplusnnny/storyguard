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


def test_client_ignores_base_url_and_token_from_environment(anthropic_env, monkeypatch):
    """환경에 다른 서버 주소·토큰이 있어도 키가 api.anthropic.com으로만 가야 한다(실제로 한 번 새어 나갈 뻔함)."""
    from urllib.parse import urlparse
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://other.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "gateway-token")
    client = llm_client._anthropic_client()
    assert urlparse(str(client.base_url)).netloc == "api.anthropic.com"
    assert all("gateway-token" not in v for v in client.auth_headers.values())


def test_missing_api_key_is_config_error_without_using_other_credentials(anthropic_env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "gateway-token")
    r = llm_client.call_json("modify", MSGS)
    assert r.ok is False and r.error_kind == "config_error"


@pytest.mark.parametrize("base,expected", [
    ("http://gpu:8000", "http://gpu:8000/v1"),
    ("http://gpu:8000/", "http://gpu:8000/v1"),
    ("https://x.example/v1", "https://x.example/v1"),
    ("https://generativelanguage.googleapis.com/v1beta/openai", "https://generativelanguage.googleapis.com/v1beta/openai"),
])
def test_api_root_does_not_double_v1(monkeypatch, base, expected):
    monkeypatch.setenv("LLM_BASE_URL", base)
    assert config.api_root() == expected


def test_list_models_strips_models_prefix(monkeypatch):
    """Gemini는 'models/gemini-...'로 돌려준다. .env에는 접두어 없이 적으므로 비교가 맞아야 한다."""
    import httpx

    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "models/gemini-3.5-flash-lite"}, {"id": "plain-model"}]})
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert llm_client.list_models() == ["gemini-3.5-flash-lite", "plain-model"]
