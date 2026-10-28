"""검증 엔진 시험. 통과해야 할 사례 5개, 실패해야 할 사례 5개 + 비교(diff)·탐색 한도 시험."""
import copy

import pytest

from app import verifier
from app.verifier import load_game, verify

SAMPLE = load_game(verifier.ROOT / "data" / "games" / "sample_game.json")


def g():
    return copy.deepcopy(SAMPLE)


def q(data, qid):
    return next(x for x in data["quests"] if x["id"] == qid)


def area(data, aid):
    return next(x for x in data["areas"] if x["id"] == aid)


# ------------------------------------------------------------ 통과해야 할 사례 5개
def test_pass_1_sample():
    r = verify(g())
    assert r["passed"] and r["reachable"]
    assert r["path"][-1]["text"].startswith("보스 처치")


def test_pass_2_dialogue_only():
    d = g()
    next(n for n in d["npcs"] if n["id"] == "chief")["dialogue"] = ["안녕하신가, 여행자여."]
    assert verify(d)["passed"]


def test_pass_3_key_from_event_instead_of_quest():
    d = g()
    q(d, "q2")["reward_items"] = []
    d["events"].append({"id": "chest", "name": "보물 상자", "area": "cave", "gives_items": ["golden_key"]})
    assert verify(d)["reachable"]


def test_pass_4_extra_optional_quest():
    d = g()
    d["items"].append({"id": "potion", "name": "물약"})
    d["quests"].append({"id": "q4", "name": "약초꾼의 부탁", "giver": "chief", "complete_area": "forest",
                        "reward_items": ["potion"]})
    r = verify(d)
    assert r["passed"] and not r["warnings"]


def test_pass_5_ending_also_needs_item():
    d = g()
    d["ending"]["requires_items"] = ["legend_sword"]
    assert verify(d)["reachable"]


# ------------------------------------------------------------ 실패해야 할 사례 5개
def test_fail_1_demo_reward_swap():
    d = g()
    d["items"].append({"id": "magic_staff", "name": "마법 지팡이"})
    q(d, "q2")["reward_items"] = ["magic_staff"]
    r = verify(d)
    assert not r["reachable"]
    b = r["blockers"][0]
    assert b["type"] == "missing_source"
    assert b["target"] == "area:final_dungeon" and b["requirement"] == "item:golden_key"


def test_fail_2_circular_quests():
    d = g()
    q(d, "q1")["requires_quests"] = ["q2"]          # q1 ↔ q2 서로를 기다림
    r = verify(d)
    assert not r["reachable"]
    assert any(b["type"] == "circular_dependency" for b in r["blockers"])


def test_fail_3_item_consumed_twice():
    d = g()
    # 철광석은 한 번만 나오는데, 검을 만들 때 소모되고 보스도 철광석을 요구함
    next(e for e in d["events"] if e["id"] == "boss_battle")["requires_items"] = ["legend_sword", "iron_ore"]
    r = verify(d)
    assert not r["reachable"]
    assert r["blockers"][0]["type"] == "unreachable_combination"


def test_fail_4_no_route_to_cave():
    d = g()
    area(d, "forest")["connections"] = ["village"]
    area(d, "final_dungeon")["connections"] = []
    area(d, "cave")["connections"] = ["final_dungeon"]
    r = verify(d)
    assert not r["reachable"]
    assert any(b["type"] == "no_route" and b["target"] == "area:cave" for b in r["blockers"])


def test_fail_5_undefined_item_reference():
    d = g()
    q(d, "q2")["reward_items"] = ["silver_key"]      # items에 정의하지 않음
    r = verify(d)
    assert not r["passed"]
    assert r["schema_errors"] and r["schema_errors"][0]["type"] == "reference"
    assert r["blockers"][0]["type"] == "invalid_data"


# ------------------------------------------------------------ 형식, 비교, 한도
def test_schema_error_bad_id():
    d = g()
    d["items"][0]["id"] = "Torch!"
    assert verify(d)["schema_errors"][0]["type"] == "schema"


def test_diff_flags_unintended_change():
    d = g()
    d["items"].append({"id": "magic_staff", "name": "마법 지팡이"})
    q(d, "q2")["reward_items"] = ["magic_staff", "golden_key"]
    area(d, "cave")["requires_items"] = []           # 요청하지 않은 변경
    r = verify(d, SAMPLE, ["quests[q2].reward_items"])
    paths = [c["path"] for c in r["unintended_changes"]]
    assert paths == ["areas[cave].requires_items"]
    assert not r["passed"]                           # 엔딩은 가능해도 요청하지 않은 변경이 있으면 실패


def test_diff_allows_new_item_referenced_by_declared_change():
    d = g()
    d["items"].append({"id": "magic_staff", "name": "마법 지팡이"})
    q(d, "q2")["reward_items"] = ["magic_staff", "golden_key"]
    r = verify(d, SAMPLE, ["quests[q2].reward_items"])
    assert r["unintended_changes"] == [] and r["passed"]


def test_removed_element_is_unintended():
    d = g()
    d["npcs"] = [n for n in d["npcs"] if n["id"] != "smith"]
    q(d, "q3")["giver"] = "chief"
    r = verify(d, SAMPLE, ["quests[q3].giver"])
    assert any(c["path"] == "npcs[smith]" and c["kind"] == "removed" for c in r["unintended_changes"])


def test_search_limit(monkeypatch):
    monkeypatch.setattr(verifier, "MAX_STATES", 5)
    r = verify(g())
    assert not r["reachable"]
    assert r["stats"]["truncated"] is True
    assert r["blockers"][0]["type"] == "search_limit"


@pytest.mark.parametrize("word,pair,expect", [
    ("황금 열쇠", "이가", "황금 열쇠가"), ("마법 지팡이", "을를", "마법 지팡이를"),
    ("동굴", "으로", "동굴로"), ("숲", "으로", "숲으로"), ("마지막 던전", "으로", "마지막 던전으로"),
])
def test_josa(word, pair, expect):
    from app.engine import josa
    assert josa(word, pair) == expect
