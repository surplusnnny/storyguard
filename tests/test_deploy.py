"""Vercel 배포 구조 시험 (docs/DEPLOY-PLAN.md Task 2)."""
import copy
import json
import time

import httpx
from fastapi.testclient import TestClient

from app import config, llm_client, pipeline
from app.server import app
from app.verifier import load_game

SAMPLE = load_game(config.ROOT / "data" / "games" / "sample_game.json")
DEMO = "두 번째 퀘스트 보상을 황금 열쇠에서 마법 지팡이로 바꿔 줘"
GPU = "http://10.0.0.5:8000"


def test_main_entrypoint_exposes_app():
    import main
    assert main.app.title == "StoryGuard"


def test_status_hides_base_url_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("LLM_BASE_URL", GPU)
    monkeypatch.setenv("LLM_MODELS", "m1")
    resp = TestClient(app).get("/api/status")
    assert resp.json()["base_url"] == ""
    assert "10.0.0.5" not in resp.text


def test_health_error_hides_address_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("LLM_BASE_URL", GPU)

    def refuse():
        raise httpx.ConnectError(f"connection to {GPU}/v1/models refused")

    monkeypatch.setattr(llm_client, "list_models", refuse)
    resp = TestClient(app).get("/api/health")
    assert resp.json()["ok"] is False
    assert "10.0.0.5" not in resp.text


def test_budget_stops_retries(monkeypatch):
    """요청 하나의 시간 한도를 넘으면 다음 재시도를 하지 않고 '시간 제한으로 중단'을 그대로 남긴다."""
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.setenv("LLM_REQUEST_BUDGET", "0.3")
    real = llm_client.call_json
    first = {}

    def slow_and_stuck(prompt_name, messages, context=None, **kw):
        time.sleep(0.2)
        r = real(prompt_name, messages, context=context, **kw)
        if prompt_name == "modify":
            first["game"] = r.data["modified_game"]
        if prompt_name == "repair":   # 매번 같은(엔딩이 막힌) 게임을 돌려줌
            r.data = {"modified_game": copy.deepcopy(first["game"]), "reasoning": "같은 실패 반복"}
        return r

    monkeypatch.setattr(pipeline.llm_client, "call_json", slow_and_stuck)
    r = pipeline.modify(SAMPLE, DEMO, auto_retry=True)
    assert r["status"] == "failed"
    assert len(r["attempts"]) < 4
    assert r["attempts"][-1]["llm"]["error_kind"] == "budget_exceeded"
    assert r["explanation"]["source"] == "template"   # 한도를 넘었으니 설명도 AI를 부르지 않음


def test_vercel_json_values():
    cfg = json.loads((config.ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert cfg["regions"] == ["icn1"]
    assert cfg["functions"]["main.py"]["maxDuration"] == 300
