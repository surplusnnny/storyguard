"""두 번째 데모 게임(등대의 불빛). 엔진을 만들 때 쓴 샘플 게임과 겹치지 않는 사례로 서비스를 시험한다(규칙 8)."""
import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.server import app

PATH = Path(__file__).resolve().parent.parent / "data" / "games" / "lighthouse_game.json"
c = TestClient(app)


def game():
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_game_is_listed_and_loadable():
    assert "lighthouse_game" in c.get("/api/games").json()
    r = c.get("/api/game/lighthouse_game").json()
    assert r["game"]["meta"]["title"] == "등대의 불빛"


def test_original_reaches_ending_with_schema_ok():
    v = c.post("/api/verify", json={"game": game()}).json()["verify"]
    assert v["reachable"] is True and v["passed"] is True
    assert v["schema_errors"] == [] and len(v["path"]) >= 5


def test_swapping_gear_reward_blocks_the_ending():
    g = copy.deepcopy(game())
    g["quests"][0]["reward_items"] = ["blue_glass"]  # 황동 톱니 대신 푸른 유리를 주면 열쇠를 못 만든다
    v = c.post("/api/verify", json={"game": g}).json()["verify"]
    assert v["reachable"] is False
    assert any("lighthouse_key" in json.dumps(b, ensure_ascii=False) or "brass_gear" in json.dumps(b, ensure_ascii=False)
               for b in v["blockers"])


def test_game_can_be_played_to_the_ending():
    g = game()
    v = c.post("/api/verify", json={"game": g}).json()["verify"]
    st = None
    for step in v["path"]:
        out = c.post("/api/play", json={"game": g, "state": st, "action": step["action"]}).json()
        st = out["state"]
    assert out["ending"] is True
