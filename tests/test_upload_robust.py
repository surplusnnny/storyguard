"""외부 사용자가 올린(깨졌을 수도 있는) game.json을 서버가 안전하게 다루는지 시험한다."""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import llm_client
from app.server import app

c = TestClient(app, raise_server_exceptions=False)
GOOD = json.loads((Path(__file__).resolve().parent.parent / "data" / "games" / "lighthouse_game.json").read_text(encoding="utf-8"))


def broken(kind):
    g = copy.deepcopy(GOOD)
    if kind == "items_not_list":
        g["items"] = "문자열"
    elif kind == "area_entry_not_dict":
        g["areas"] = ["harbor"]
    elif kind == "unknown_ref":
        g["areas"][0]["connections"] = ["nowhere"]
    elif kind == "empty":
        g = {}
    return g


@pytest.mark.parametrize("kind", ["items_not_list", "area_entry_not_dict", "unknown_ref", "empty"])
def test_verify_returns_error_list_not_500(kind):
    r = c.post("/api/verify", json={"game": broken(kind)})
    assert r.status_code == 200
    j = r.json()
    assert j["verify"]["schema_errors"], "오류 목록이 있어야 한다"
    assert j["verify"]["reachable"] is False and j["verify"]["passed"] is False
    assert j["graph"] is None


@pytest.mark.parametrize("path,body", [
    ("/api/modify", {"request": "대사를 바꿔 줘"}),
    ("/api/analyze", {}),
    ("/api/play", {}),
    ("/api/save_game", {}),
])
def test_other_endpoints_reject_broken_game_with_422(path, body):
    r = c.post(path, json={"game": broken("items_not_list"), **body})
    assert r.status_code == 422
    assert r.json()["schema_errors"]


def test_apply_fix_rejects_broken_game():
    r = c.post("/api/apply_fix", json={"original": broken("items_not_list"), "request": "x", "failed_game": GOOD, "fix": {}})
    assert r.status_code == 422


def test_broken_game_never_reaches_the_ai(monkeypatch):
    """형식이 깨진 게임은 AI를 부르기 전에 거절해서 호출 예산을 쓰지 않는다."""
    calls = []
    monkeypatch.setattr(llm_client, "call_json", lambda *a, **k: calls.append(1))
    c.post("/api/modify", json={"game": broken("unknown_ref"), "request": "대사를 바꿔 줘"})
    assert calls == []


def test_valid_game_still_works():
    r = c.post("/api/verify", json={"game": GOOD})
    assert r.status_code == 200 and r.json()["verify"]["passed"] is True and r.json()["graph"]
