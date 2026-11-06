"""LLM 클라이언트. GPU 서버의 vLLM(OpenAI 호환 API) 또는 Claude API(LLM_PROVIDER=anthropic)를 부른다.

- 모든 호출의 모델, 응답 시간, 토큰 수, 성공 여부를 기록한다(발표 숫자의 근거).
  어디에 쓰는지는 app/storage.py가 정한다: Supabase(설정 있을 때) 또는 SQLite(data/llm_calls.db).
- 실패하면: 같은 모델로 한 번 더 → 다른 모델로 전환. 대기 2초, 4초(LLM_RETRY_WAITS).
- JSON이 아니면 "JSON만 다시 보내라"고 한 번 더 요청한다.
- 실시간 호출이 모두 실패하면, 같은 요청을 예전에 성공했던 저장 결과가 있을 때만 그것을 쓰고
  source="replay"로 표시한다. 화면은 이것을 "저장된 결과"로 보여 준다.
- 최종 실패는 숨기지 않고 ok=False와 원인(timeout / server_error / json_error / config_error)을 돌려준다.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from . import config, mock_llm, storage


@dataclass
class LLMResult:
    ok: bool
    data: dict | None = None
    raw: str = ""
    model: str = ""
    source: str = ""            # live / mock / replay
    error_kind: str = ""        # timeout / server_error / json_error / config_error / no_recording
    error_message: str = ""
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tries: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {"ok": self.ok, "model": self.model, "source": self.source,
                "error_kind": self.error_kind, "error_message": self.error_message,
                "latency_ms": round(self.latency_ms, 1), "tries": self.tries}


# ------------------------------------------------------------------ 실시간 호출 한도
_live_calls: deque = deque()
_live_lock = threading.Lock()


def _take_live_slot(limit: int) -> bool:
    """최근 한 시간 안의 실시간 호출이 limit보다 적으면 한 자리를 쓰고 True."""
    now = time.time()
    with _live_lock:
        while _live_calls and now - _live_calls[0] > 3600:
            _live_calls.popleft()
        if len(_live_calls) >= limit:
            return False
        _live_calls.append(now)
        return True


# ------------------------------------------------------------------ JSON 꺼내기
_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> dict:
    """모델 답에서 JSON 객체를 꺼낸다. <think> 블록과 ``` 코드 울타리는 지운다."""
    t = _THINK.sub("", text or "").strip()
    m = _FENCE.search(t)
    if m:
        t = m.group(1).strip()
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start < 0 or end <= start:
            raise
        obj = json.loads(t[start:end + 1])
    if not isinstance(obj, dict):
        raise json.JSONDecodeError("최상위가 객체가 아님", t, 0)
    return obj


# ------------------------------------------------------------------ 기록 (app/storage.py가 어디에 쓸지 정함)
def _log(run_tag: str, prompt_name: str, r: LLMResult) -> None:
    # 기록 실패가 시연을 멈추지 않게 한다 (storage가 False를 돌려줄 뿐 예외를 내지 않음)
    storage.log_call({"run_tag": run_tag, "prompt_name": prompt_name, "model": r.model, "source": r.source,
                      "ok": r.ok, "error_kind": r.error_kind, "latency_ms": r.latency_ms,
                      "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens})


def _key(prompt_name: str, messages: list[dict]) -> str:
    h = hashlib.sha256((prompt_name + json.dumps(messages, ensure_ascii=False, sort_keys=True)).encode("utf-8"))
    return h.hexdigest()[:24]


def _save_recording(key: str, prompt_name: str, r: LLMResult) -> None:
    storage.save_recording(key, prompt_name, r.model, r.data or {})


# ------------------------------------------------------------------ 실시간 호출
def _post(model: str, messages: list[dict]) -> tuple[str, dict]:
    if config.provider() == "anthropic":
        return _post_anthropic(model, messages)
    return _post_vllm(model, messages)


ANTHROPIC_URL = "https://api.anthropic.com"  # 환경의 ANTHROPIC_BASE_URL(다른 서버일 수 있음)을 따르지 않게 고정


def _anthropic_client():
    """시험에서 가짜로 바꿔 끼우는 지점. 재시도는 call_json이 하므로 SDK 재시도는 끈다.
    키는 ANTHROPIC_API_KEY만 쓴다. 서버 주소를 고정해 키가 다른 서버로 가지 않게 하고,
    키가 비어 있으면 환경의 ANTHROPIC_AUTH_TOKEN 같은 다른 자격으로 대신 부르지 않고 설정 오류로 끝낸다."""
    import anthropic
    key = config.get("ANTHROPIC_API_KEY")
    if not key:
        raise _ConfigError(".env의 ANTHROPIC_API_KEY가 비어 있습니다.")
    return anthropic.Anthropic(api_key=key, base_url=ANTHROPIC_URL, timeout=config.timeout(), max_retries=0)


def _post_anthropic(model: str, messages: list[dict]) -> tuple[str, dict]:
    # system 메시지는 별도 인자로 보낸다. temperature는 보내지 않는다(Haiku 5.5는 기본값 외 값이면 400).
    system = (chr(10) * 2).join(m["content"] for m in messages if m["role"] == "system")
    chat = [m for m in messages if m["role"] != "system"]
    resp = _anthropic_client().messages.create(
        model=model, max_tokens=config.max_tokens(), system=system, messages=chat,
        output_config={"effort": "low"})  # 생각이 기본으로 켜져 있어 낮춰 비용·시간을 줄인다
    if resp.stop_reason == "refusal":
        raise _Refused("모델이 이 요청에 답하기를 거절함")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    usage = {"prompt_tokens": resp.usage.input_tokens, "completion_tokens": resp.usage.output_tokens}
    return text, usage


def _post_vllm(model: str, messages: list[dict]) -> tuple[str, dict]:
    import httpx
    if config.is_openai():
        # gpt-5 계열은 temperature 기본값 외 값과 max_tokens를 받지 않는다. 추론 토큰이 한도를 같이 쓴다.
        body: dict[str, Any] = {"model": model, "messages": messages,
                                "max_completion_tokens": max(config.max_tokens(), 8000),
                                "reasoning_effort": config.reasoning_effort()}
    else:
        body = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": config.max_tokens()}
    if config.json_mode():
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {config.api_key()}"}
    with httpx.Client(timeout=config.timeout()) as client:
        resp = client.post(f"{config.api_root()}/chat/completions", json=body, headers=headers)
    if resp.status_code >= 400:
        raise _HTTPError(resp.status_code, resp.text[:500])
    j = resp.json()
    choices = j.get("choices") or []
    if not choices:
        raise _HTTPError(resp.status_code, "응답에 choices가 없음: " + json.dumps(j, ensure_ascii=False)[:300])
    return choices[0]["message"].get("content") or "", j.get("usage") or {}


class _Refused(Exception):
    pass


class _ConfigError(Exception):
    pass


class _HTTPError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text}")
        self.status = status


def _classify(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if isinstance(exc, _Refused):
        return "refusal"
    if isinstance(exc, _ConfigError):
        return "config_error"
    if isinstance(exc, _HTTPError):
        return "rate_limited" if exc.status == 429 else "server_error"
    if getattr(exc, "status_code", None) == 429:  # anthropic SDK의 RateLimitError
        return "rate_limited"
    if isinstance(exc, json.JSONDecodeError):
        return "json_error"
    return "server_error"


def call_json(prompt_name: str, messages: list[dict], context: dict | None = None,
              models: list[str] | None = None, allow_fallback: bool = True, run_tag: str = "") -> LLMResult:
    mode = config.mode()
    key = _key(prompt_name, messages)

    if mode == "mock":
        t0 = time.perf_counter()
        data = mock_llm.respond(prompt_name, context or {})
        r = LLMResult(ok=True, data=data, raw=json.dumps(data, ensure_ascii=False), model="mock",
                      source="mock", latency_ms=(time.perf_counter() - t0) * 1000)
        _log(run_tag, prompt_name, r)
        return r

    if mode == "replay":
        try:
            rec = storage.load_recording(key)
            r = (LLMResult(ok=True, data=rec["data"], model=rec.get("model", ""), source="replay") if rec else
                 LLMResult(ok=False, source="replay", error_kind="no_recording",
                           error_message="이 요청에 대한 저장된 결과가 없습니다."))
        except storage.StorageError as exc:
            r = LLMResult(ok=False, source="replay", error_kind="storage_error",
                          error_message=f"저장된 결과를 불러오지 못했습니다. {exc}")
        _log(run_tag, prompt_name, r)
        return r

    if mode == "replay_first":
        # 저장된 결과가 있으면 그것을 쓴다(같은 요청은 같은 연쇄를 재현). 없으면 아래 실시간 호출로 넘어간다.
        try:
            rec = storage.load_recording(key)
        except storage.StorageError:
            rec = None  # 저장소를 못 읽으면 없는 것으로 보고 실시간을 시도한다
        if rec:
            r = LLMResult(ok=True, data=rec["data"], model=rec.get("model", ""), source="replay")
            _log(run_tag, prompt_name, r)
            return r

    limit = config.live_call_limit()
    if limit and not _take_live_slot(limit):
        r = LLMResult(ok=False, source="live", error_kind="live_limit",
                      error_message=f"실시간 AI 호출 한도(시간당 {limit}회)에 도달했습니다. 저장된 결과는 계속 볼 수 있습니다.")
        _log(run_tag, prompt_name, r)
        return r

    models = models or config.models()
    if not models:
        r = LLMResult(ok=False, source="live", error_kind="config_error",
                      error_message=".env의 LLM_MODELS가 비어 있습니다.")
        _log(run_tag, prompt_name, r)
        return r
    if not allow_fallback or config.get("LLM_NO_FALLBACK") == "1":
        models = models[:1]  # 모델 비교 실험에서는 다른 모델로 넘어가지 않게 한다

    waits = config.retry_waits() or [0]
    tries: list[dict] = []
    t_all = time.perf_counter()
    wait_i = 0
    for model in models:
        msgs = list(messages)
        for attempt in range(2):  # 같은 모델로 최대 2번
            if tries:
                time.sleep(waits[min(wait_i, len(waits) - 1)])
                wait_i += 1
            t0 = time.perf_counter()
            try:
                text, usage = _post(model, msgs)
                data = extract_json(text)
                r = LLMResult(ok=True, data=data, raw=text, model=model, source="live",
                              latency_ms=(time.perf_counter() - t0) * 1000,
                              prompt_tokens=int(usage.get("prompt_tokens") or 0),
                              completion_tokens=int(usage.get("completion_tokens") or 0))
                tries.append({"model": model, "ok": True, "ms": round(r.latency_ms, 1)})
                r.tries = tries
                _log(run_tag, prompt_name, r)
                _save_recording(key, prompt_name, r)
                return r
            except Exception as exc:  # noqa: BLE001 - 모든 실패를 원인별로 기록한다
                kind = _classify(exc)
                tries.append({"model": model, "ok": False, "error_kind": kind, "error": str(exc)[:300],
                              "ms": round((time.perf_counter() - t0) * 1000, 1)})
                _log(run_tag, prompt_name, LLMResult(ok=False, model=model, source="live", error_kind=kind,
                                                     latency_ms=(time.perf_counter() - t0) * 1000))
                if kind == "json_error":
                    msgs = list(messages) + [{"role": "user", "content":
                                              "직전 답이 JSON 형식이 아니었습니다. 설명 없이 JSON 객체 하나만 다시 보내세요."}]

    last = tries[-1] if tries else {}
    failed = LLMResult(ok=False, model=last.get("model", ""), source="live",
                       error_kind=last.get("error_kind", "server_error"),
                       error_message=last.get("error", ""), tries=tries,
                       latency_ms=(time.perf_counter() - t_all) * 1000)
    if config.replay_fallback():
        try:
            rec = storage.load_recording(key)
        except storage.StorageError as exc:
            rec = None
            failed.error_message += f" (저장된 결과도 불러오지 못함: {exc})"
        if rec:
            r = LLMResult(ok=True, data=rec["data"], model=rec.get("model", ""), source="replay",
                          tries=tries, error_kind=failed.error_kind,
                          error_message="실시간 호출이 실패해 저장된 결과를 사용함: " + failed.error_message)
            _log(run_tag, prompt_name, r)
            return r
    return failed


def list_models() -> list[str]:
    if config.provider() == "anthropic":
        return [m.id for m in _anthropic_client().models.list()]
    import httpx
    with httpx.Client(timeout=config.timeout()) as client:
        resp = client.get(f"{config.api_root()}/models",
                          headers={"Authorization": f"Bearer {config.api_key()}"})
    resp.raise_for_status()
    return [m["id"].removeprefix("models/") for m in resp.json().get("data", [])]  # Gemini는 models/ 접두어를 붙임
