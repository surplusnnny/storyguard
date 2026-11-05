"""GPU 서버의 vLLM(OpenAI 호환 API)을 부르는 클라이언트.

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
import time
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
    import httpx
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.2,
                            "max_tokens": config.max_tokens()}
    if config.json_mode():
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {config.api_key()}"}
    with httpx.Client(timeout=config.timeout()) as client:
        resp = client.post(f"{config.base_url()}/v1/chat/completions", json=body, headers=headers)
    if resp.status_code >= 400:
        raise _HTTPError(resp.status_code, resp.text[:500])
    j = resp.json()
    choices = j.get("choices") or []
    if not choices:
        raise _HTTPError(resp.status_code, "응답에 choices가 없음: " + json.dumps(j, ensure_ascii=False)[:300])
    return choices[0]["message"].get("content") or "", j.get("usage") or {}


class _HTTPError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text}")
        self.status = status


def _classify(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if isinstance(exc, _HTTPError):
        return "rate_limited" if exc.status == 429 else "server_error"
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
    import httpx
    with httpx.Client(timeout=config.timeout()) as client:
        resp = client.get(f"{config.base_url()}/v1/models",
                          headers={"Authorization": f"Bearer {config.api_key()}"})
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]
