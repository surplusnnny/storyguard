"""가짜 vLLM 서버 (OpenAI 호환 /v1/chat/completions, /v1/models).

GPU 서버 없이 live 모드의 HTTP 경로(재시도, 모델 전환, JSON 다시 요청, 저장 결과 대체)를 시험하려고 만든 것이다.
진짜 LLM이 아니다. 답은 app/mock_llm.py의 규칙 기반 응답을 쓴다.

모델 이름으로 동작을 고른다.
- fake-ok        : 정상 JSON 응답
- fake-think     : <think>…</think> 뒤에 ```json 코드 울타리로 답함 (Qwen 계열 흉내)
- fake-bad-json  : 첫 요청은 JSON이 아닌 문장, "JSON만 다시" 요청에는 정상 답
- fake-429       : 항상 429
- fake-500       : 항상 500
- fake-slow      : 응답 전에 FAKE_SLOW_SEC초(기본 40) 기다림 → 타임아웃 시험

실행:  python tools/fake_vllm.py  (기본 포트 8001)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app import mock_llm  # noqa: E402

app = FastAPI(title="fake-vllm")
MODELS = ["fake-ok", "fake-think", "fake-bad-json", "fake-429", "fake-500", "fake-slow"]


def _between(text: str, start: str, end: str | None) -> str:
    i = text.index(start) + len(start)
    j = text.index(end, i) if end and end in text[i:] else len(text)
    return text[i:j].strip()


def _ctx(system: str, user: str) -> tuple[str, dict]:
    if system.startswith("너는 게임 데이터를 안전하게 수정"):
        return "modify", {"game": json.loads(_between(user, "[현재 게임 데이터]\n", "\n\n[사용자 요청]")),
                          "request": _between(user, "[사용자 요청]\n", None)}
    if system.startswith("너는 게임을 처음 만들어 보는"):
        # 설명은 원본 게임이 메시지에 없으므로 바뀐 것과 검증 결과만으로 규칙 설명을 만든다
        return "explain_raw", {"verify": json.loads(_between(user, "[검증 결과]\n", None)),
                               "changes": json.loads(_between(user, "[이번 수정에서 바뀐 것]\n", "\n\n[검증 결과]"))}
    if system.startswith("너는 게임 데이터를 고치는"):
        chosen = None
        if "[사용자가 고른 해결 방법(chosen_fix)]" in user:
            chosen = json.loads(_between(user, "[사용자가 고른 해결 방법(chosen_fix)]\n", None))
            prev_end = "\n\n[사용자가 고른 해결 방법(chosen_fix)]"
        else:
            prev_end = None
        failed = json.loads(_between(user, "[실패한 게임 데이터]\n", "\n\n[검증 결과]"))
        verify = json.loads(_between(user, "[검증 결과]\n", "\n\n[이전 시도 기록]"))
        from app.verifier import verify as run_verify
        full = run_verify(failed)  # 가짜 서버는 규칙 설명을 위해 검증을 다시 돌린다
        return "repair", {"failed_game": failed, "verify": {**full, **verify}, "chosen_fix": chosen,
                          "previous": json.loads(_between(user, "[이전 시도 기록]\n", prev_end)), "changes": []}
    if system.startswith("너는 스토리 중심 2D 게임의 구조"):
        return "analyze", {"game": json.loads(_between(user, "[게임 데이터]\n", None))}
    return "unknown", {}


def _answer(messages: list[dict]) -> dict:
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user = next((m["content"] for m in messages if m["role"] == "user"), "")
    kind, ctx = _ctx(system, user)
    if kind == "explain_raw":
        v = ctx["verify"]
        b = (v.get("blockers") or [{}])[0]
        return {"problem": "플레이어가 엔딩에 도달할 수 없습니다.", "cause": b.get("message", "검증 결과만으로는 원인을 확인할 수 없음"),
                "blocker_ids": [b["id"]] if b.get("id") else [], "fixes": []}
    if kind == "unknown":
        return {"error": "fake server: 알 수 없는 프롬프트"}
    return mock_llm.respond(kind, ctx)


def _reply(model: str, content: str, prompt_chars: int) -> dict:
    return {"id": "fake", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_chars // 2, "completion_tokens": len(content) // 2}}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    model = body.get("model", "")
    msgs = body.get("messages", [])
    chars = sum(len(m.get("content", "")) for m in msgs)
    if model == "fake-429":
        return JSONResponse({"error": "rate limited"}, status_code=429)
    if model == "fake-500":
        return JSONResponse({"error": "internal"}, status_code=500)
    if model == "fake-slow":
        time.sleep(float(os.environ.get("FAKE_SLOW_SEC", "40")))
    data = _answer(msgs)
    text = json.dumps(data, ensure_ascii=False)
    if model == "fake-think":
        text = "<think>요청을 분석한다...</think>\n```json\n" + text + "\n```"
    if model == "fake-bad-json" and not re.search(r"JSON 형식이 아니었습니다", msgs[-1].get("content", "")):
        text = "네, 요청하신 대로 수정했습니다! 보상을 바꿨어요."
    return _reply(model, text, chars)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FAKE_PORT", "8001")))
