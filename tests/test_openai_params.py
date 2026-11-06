"""api.openai.com(gpt-5 계열)은 temperature·max_tokens를 예전 방식으로 받지 않는다. 요청 본문만 가로채 시험한다."""
import json

import httpx
import pytest

from app import llm_client

MSGS = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]


def _capture(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 4}})
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


def test_openai_body_uses_new_params(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    seen = _capture(monkeypatch)
    text, usage = llm_client._post_vllm("gpt-5-mini", MSGS)
    body = seen["body"]
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert "temperature" not in body and "max_tokens" not in body
    assert body["max_completion_tokens"] >= 8000   # 추론 토큰이 한도를 같이 쓰므로 넉넉히
    assert body["reasoning_effort"] == "low"
    assert text == '{"a": 1}' and usage["prompt_tokens"] == 5


def test_vllm_body_unchanged(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu:8000")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    seen = _capture(monkeypatch)
    llm_client._post_vllm("m", MSGS)
    body = seen["body"]
    assert body["temperature"] == 0.2 and body["max_tokens"] == 4096
    assert "max_completion_tokens" not in body and "reasoning_effort" not in body
