"""LLM 연결과 파이프라인 시험. 가짜 vLLM 서버(tools/fake_vllm.py)로 live 경로를 시험한다.
시연 요청과 겹치지 않는 사례도 함께 쓴다(검증 엔진을 만들 때 쓴 사례만으로는 시험이 의미 없음)."""
import copy
import sqlite3

from app import config, llm_client, pipeline
from app.verifier import load_game, verify

SAMPLE = load_game(config.ROOT / "data" / "games" / "sample_game.json")
DEMO = "두 번째 퀘스트 보상을 황금 열쇠에서 마법 지팡이로 바꿔 줘"
MSG = [{"role": "system", "content": "너는 게임 데이터를 안전하게 수정하는 게임 개발자다."},
       {"role": "user", "content": "[현재 게임 데이터]\n{}\n\n[사용자 요청]\n테스트"}]


def test_extract_json_variants():
    assert llm_client.extract_json('{"a": 1}') == {"a": 1}
    assert llm_client.extract_json('<think>음</think>\n```json\n{"a": 2}\n```') == {"a": 2}
    assert llm_client.extract_json('결과는 다음과 같습니다 {"a": 3} 끝') == {"a": 3}


# ------------------------------------------------------------ live (가짜 서버)
def test_live_ok_logs_and_records(live, monkeypatch):
    monkeypatch.setenv("LLM_MODELS", "fake-ok")
    r = pipeline.modify(SAMPLE, DEMO, auto_retry=False)
    assert r["status"] == "failed" and r["sources"] == ["live"]
    assert r["verify"]["blockers"][0]["requirement"] == "item:golden_key"
    con = sqlite3.connect(config.DB_PATH)
    rows = con.execute("select model, source, ok from calls").fetchall()
    assert ("fake-ok", "live", 1) in rows
    assert any(config.RECORDINGS.glob("*.json"))


def test_live_think_tags(live, monkeypatch):
    monkeypatch.setenv("LLM_MODELS", "fake-think")
    r = llm_client.call_json("modify", pipeline.prompts.modify_messages(SAMPLE, DEMO))
    assert r.ok and r.data["modified_game"]


def test_live_bad_json_then_retry_same_model(live, monkeypatch):
    monkeypatch.setenv("LLM_MODELS", "fake-bad-json")
    r = llm_client.call_json("modify", pipeline.prompts.modify_messages(SAMPLE, DEMO))
    assert r.ok and r.model == "fake-bad-json"
    assert [t["ok"] for t in r.tries] == [False, True]
    assert r.tries[0]["error_kind"] == "json_error"


def test_live_fallback_to_second_model(live, monkeypatch):
    monkeypatch.setenv("LLM_MODELS", "fake-429,fake-ok")
    r = llm_client.call_json("modify", pipeline.prompts.modify_messages(SAMPLE, DEMO))
    assert r.ok and r.model == "fake-ok"
    assert [t["error_kind"] for t in r.tries[:2]] == ["rate_limited", "rate_limited"]


def test_live_timeout_is_reported_honestly(live, monkeypatch):
    monkeypatch.setenv("LLM_MODELS", "fake-slow")
    monkeypatch.setenv("LLM_REPLAY_FALLBACK", "0")
    r = pipeline.modify(SAMPLE, DEMO)
    assert r["status"] == "llm_failed"
    assert r["attempts"][0]["llm"]["error_kind"] == "timeout"
    assert r["final_game"] is None            # 이전 결과를 남겨 두지 않음


def test_live_all_fail_uses_recording_only_if_exists(live, monkeypatch):
    msgs = pipeline.prompts.modify_messages(SAMPLE, DEMO)
    monkeypatch.setenv("LLM_MODELS", "fake-500")
    assert llm_client.call_json("modify", msgs).ok is False          # 저장된 결과가 아직 없음
    monkeypatch.setenv("LLM_MODELS", "fake-ok")
    assert llm_client.call_json("modify", msgs).source == "live"     # 성공 → 저장됨
    monkeypatch.setenv("LLM_MODELS", "fake-500")
    r = llm_client.call_json("modify", msgs)
    assert r.ok and r.source == "replay" and "저장된 결과" in r.error_message


def test_replay_mode_without_recording(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "replay")
    r = llm_client.call_json("modify", MSG)
    assert not r.ok and r.error_kind == "no_recording"


def test_config_error_when_no_models(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("LLM_MODELS", "")
    assert llm_client.call_json("modify", MSG).error_kind == "config_error"


# ------------------------------------------------------------ 파이프라인 (mock)
def test_demo_auto_retry_passes_and_keeps_intent(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    r = pipeline.modify(SAMPLE, DEMO, auto_retry=True)
    assert r["first_pass"] is False and r["status"] == "passed"
    assert r["attempts"][-1]["intent"]["kept"]
    staff = pipeline.get_by_path(r["final_game"], "quests[q2].reward_items")
    assert "magic_staff" in staff


def test_demo_manual_fix_each_option_passes(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    r = pipeline.modify(SAMPLE, DEMO, auto_retry=False)
    assert r["status"] == "failed" and len(r["explanation"]["fixes"]) == 3
    for fix in r["explanation"]["fixes"]:
        r2 = pipeline.apply_fix(SAMPLE, DEMO, r["final_game"], fix, r["intent_paths"], r["declared"])
        assert r2["status"] == "passed", fix["title"]


def test_intent_reverted_is_caught():
    first = copy.deepcopy(SAMPLE)
    first["items"].append({"id": "magic_staff", "name": "마법 지팡이"})
    next(q for q in first["quests"] if q["id"] == "q2")["reward_items"] = ["magic_staff"]
    reverted = copy.deepcopy(SAMPLE)        # 재수정이 원래대로 되돌린 경우
    ic = pipeline.intent_check(first, reverted, ["quests[q2].reward_items"])
    assert ic["kept"] is False


def test_unsupported_request_in_mock_asks_question(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    r = pipeline.modify(SAMPLE, "보스를 더 강하게 만들어 줘")
    assert r["status"] == "question" and "모의 모드" in r["question"]


def test_explain_falls_back_to_template_when_llm_fails(live, monkeypatch):
    monkeypatch.setenv("LLM_MODELS", "fake-500")
    monkeypatch.setenv("LLM_REPLAY_FALLBACK", "0")
    d = copy.deepcopy(SAMPLE)
    d["items"].append({"id": "magic_staff", "name": "마법 지팡이"})
    next(q for q in d["quests"] if q["id"] == "q2")["reward_items"] = ["magic_staff"]
    v = verify(d, SAMPLE, ["quests[q2].reward_items"])
    out = pipeline.explain(SAMPLE, d, v, DEMO)
    assert out["source"] == "template" and out["fixes"]


def test_graph_marks_blocker():
    d = copy.deepcopy(SAMPLE)
    d["items"].append({"id": "magic_staff", "name": "마법 지팡이"})
    next(q for q in d["quests"] if q["id"] == "q2")["reward_items"] = ["magic_staff"]
    gr = pipeline.graph.build(d, verify(d))
    st = {n["id"]: n["status"] for n in gr["nodes"]}
    assert st["area:final_dungeon"] == "blocked"
    assert st["item:golden_key"] == "missing"
    assert st["ending:ending"] == "unreachable"
    assert st["area:cave"] == "ok"
