"""수정 → 검증 → (실패 시) 설명 → 자동 재수정 파이프라인.

판정은 항상 verifier.verify()가 한다. LLM 답은 판정에 쓰지 않는다.
원래 요청이 되돌려졌는지(intent_kept)도 코드로 확인한다.
"""
from __future__ import annotations

import re
import time
from typing import Any

from . import config, graph, llm_client, prompts
from .mock_llm import rule_explain
from .verifier import verify

_PATH = re.compile(r"^(\w+)(?:\[([\w]+)\])?(?:\.(\w+))?$")


def get_by_path(data: dict, path: str) -> Any:
    """quests[q2].reward_items / items[magic_staff] / ending.requires_flags 형태의 경로 값을 읽는다."""
    m = _PATH.match(path.strip())
    if not m:
        return None
    col, id_, key = m.groups()
    if id_ is None:
        sec = data.get(col)
        return sec.get(key) if isinstance(sec, dict) and key else sec
    obj = next((o for o in data.get(col, []) if isinstance(o, dict) and o.get("id") == id_), None)
    if obj is None or key is None:
        return obj
    return obj.get(key)


def _declared(plan_changes: list[dict]) -> list[str]:
    return [c.get("path", "") for c in plan_changes if isinstance(c, dict) and c.get("path")]


def intent_check(first_game: dict, final_game: dict, intent_paths: list[str]) -> dict:
    """첫 수정에서 바꾼 값(사용자 요청)이 최종 결과에도 남아 있는지."""
    lost = []
    for p in intent_paths:
        before, after = get_by_path(first_game, p), get_by_path(final_game, p)
        if isinstance(before, list) and isinstance(after, list):
            if not set(map(str, before)) <= set(map(str, after)):
                lost.append({"path": p, "requested": before, "final": after})
        elif before is not None and after is None:
            lost.append({"path": p, "requested": before, "final": after})
        elif not isinstance(before, list) and before != after and p.count(".") == 1 and "[" in p:
            lost.append({"path": p, "requested": before, "final": after})
    return {"kept": not lost, "lost": lost}


def _attempt_record(kind: str, r: llm_client.LLMResult, game: dict | None, v: dict | None,
                    note: str = "", action: Any = None) -> dict:
    return {
        "kind": kind, "llm": r.summary(), "note": note, "action": action,
        "passed": bool(v and v.get("passed")),
        "verify": None if v is None else {
            "reachable": v["reachable"], "passed": v["passed"],
            "blockers": v["blockers"], "unintended_changes": [
                {"path": c["path"], "kind": c["kind"]} for c in v["unintended_changes"]],
            "schema_errors": v["schema_errors"], "path": v["path"], "stats": v.get("stats", {}),
        },
        "game": game,
    }


def _over_budget(t0: float) -> bool:
    """요청 하나의 시간 한도(LLM_REQUEST_BUDGET)를 넘었는지. Vercel 함수 최대 시간(300초)을 넘기지 않으려고."""
    budget = config.request_budget()
    return budget > 0 and time.perf_counter() - t0 > budget


def _budget_record() -> dict:
    r = llm_client.LLMResult(ok=False, source="", error_kind="budget_exceeded",
                             error_message=f"요청 시간 한도({config.request_budget():g}초)를 넘어 다시 고치기를 멈췄습니다.")
    return _attempt_record("repair", r, None, None, note="시간 제한으로 중단")


def explain(original: dict, game: dict, v: dict, request: str, run_tag: str = "") -> dict:
    changes = v.get("changes", [])
    r = llm_client.call_json("explain", prompts.explain_messages(request, v, changes),
                             context={"game": game, "verify": v, "changes": changes}, run_tag=run_tag)
    if r.ok and isinstance(r.data, dict) and r.data.get("problem"):
        out = dict(r.data)
        out["source"] = r.source
        valid = {b["id"] for b in v.get("blockers", [])}
        out["blocker_ids_valid"] = all(b in valid for b in out.get("blocker_ids", []))
        if not out.get("fixes"):
            out["fixes"] = rule_explain(game, v, changes).get("fixes", [])
        return out
    out = rule_explain(game, v, changes)
    out["source"] = "template"
    out["llm_error"] = r.error_message or r.error_kind
    return out


def _repair_once(original: dict, request: str, failed_game: dict, v: dict, previous: list[dict],
                 declared: list[str], intent_paths: list[str], first_game: dict,
                 chosen_fix: dict | None, run_tag: str) -> tuple[dict, dict | None, dict | None, list[str]]:
    prev_summary = [{"note": p.get("note"), "action": p.get("action"),
                     "blockers": [b["message"] for b in (p.get("verify") or {}).get("blockers", [])]}
                    for p in previous]
    ctx = {"request": request, "failed_game": failed_game, "verify": v, "previous": previous,
           "chosen_fix": chosen_fix, "changes": v.get("changes", []), "original_game": original}
    r = llm_client.call_json("repair", prompts.repair_messages(request, failed_game, v, prev_summary, chosen_fix),
                             context=ctx, run_tag=run_tag)
    if not r.ok:
        return _attempt_record("repair", r, None, None, note="AI 응답 실패"), None, None, declared
    data = r.data or {}
    new_game = data.get("modified_game")
    if not isinstance(new_game, dict):
        return (_attempt_record("repair", r, None, None, note=data.get("reason") or "수정안을 만들지 못함",
                                action=data.get("_action")), None, None, declared)
    declared2 = declared + _declared(data.get("changes") or [])
    v2 = verify(new_game, original, declared2)
    ic = intent_check(first_game, new_game, intent_paths)
    if not ic["kept"]:
        v2["passed"] = False
        v2["blockers"] = v2["blockers"] + [{
            "id": f"b{len(v2['blockers']) + 1}", "type": "intent_reverted", "target": ic["lost"][0]["path"],
            "requirement": "", "message": "재수정이 사용자의 원래 요청을 되돌렸습니다.", "chain": []}]
    rec = _attempt_record("repair", r, new_game, v2, note=data.get("reasoning", ""), action=data.get("_action"))
    rec["intent"] = ic
    return rec, new_game, v2, declared2


def modify(original: dict, request: str, auto_retry: bool = True, max_retries: int = 3,
           run_tag: str = "") -> dict:
    t0 = time.perf_counter()
    attempts: list[dict] = []
    r = llm_client.call_json("modify", prompts.modify_messages(original, request),
                             context={"game": original, "request": request}, run_tag=run_tag)
    if not r.ok:
        attempts.append(_attempt_record("modify", r, None, None, note="AI 응답 실패"))
        return _result("llm_failed", original, None, None, attempts, None, request, t0)
    data = r.data or {}
    new_game = data.get("modified_game")
    plan = (data.get("plan") or {}).get("change") or []
    if not isinstance(new_game, dict):
        attempts.append(_attempt_record("modify", r, None, None, note=data.get("question") or "수정하지 않음"))
        res = _result("question", original, None, None, attempts, None, request, t0)
        res["question"] = data.get("question") or "요청을 처리하지 못했습니다."
        return res

    declared = _declared(plan)
    intent_paths = [p for p in declared if not re.match(r"^\w+\[\w+\]$", p)]  # 추가 정의(items[x])는 의도 확인에서 뺌
    v = verify(new_game, original, declared)
    rec = _attempt_record("modify", r, new_game, v, note="; ".join(map(str, data.get("warnings") or [])))
    rec["plan"] = plan
    attempts.append(rec)
    first_game, first_v = new_game, v
    cur_game, cur_v = new_game, v

    retries = 0
    while auto_retry and not cur_v["passed"] and retries < max_retries:
        if _over_budget(t0):
            attempts.append(_budget_record())
            break
        retries += 1
        rec2, g2, v2, declared = _repair_once(original, request, cur_game, cur_v, attempts[1:], declared,
                                              intent_paths, first_game, None, run_tag)
        attempts.append(rec2)
        if g2 is None:
            break
        cur_game, cur_v = g2, v2

    explanation = None
    if not first_v["passed"]:
        if _over_budget(t0):  # 한도를 넘었으면 AI 설명 대신 규칙 설명(출처 "규칙 설명")
            changes = first_v.get("changes", [])
            explanation = {**rule_explain(first_game, first_v, changes), "source": "template",
                           "llm_error": "요청 시간 한도를 넘어 AI 설명을 부르지 않음"}
        else:
            explanation = explain(original, first_game, first_v, request, run_tag)
    status = "passed" if cur_v["passed"] else "failed"
    res = _result(status, original, cur_game, cur_v, attempts, explanation, request, t0)
    res["first_pass"] = first_v["passed"]
    res["first_game"] = first_game
    res["intent_paths"] = intent_paths
    res["declared"] = declared
    return res


def apply_fix(original: dict, request: str, failed_game: dict, fix: dict, intent_paths: list[str],
              declared: list[str], previous: list[dict] | None = None, run_tag: str = "") -> dict:
    t0 = time.perf_counter()
    v = verify(failed_game, original, declared)
    rec, g2, v2, declared2 = _repair_once(original, request, failed_game, v, previous or [], declared,
                                          intent_paths, failed_game, fix, run_tag)
    status = "passed" if (v2 and v2["passed"]) else "failed"
    res = _result(status, original, g2 or failed_game, v2 or v, [rec], None, request, t0)
    res["declared"] = declared2
    res["intent_paths"] = intent_paths
    return res


def _result(status: str, original: dict, final_game: dict | None, final_v: dict | None,
            attempts: list[dict], explanation: dict | None, request: str, t0: float) -> dict:
    shown = final_game or original
    v_for_graph = final_v or verify(original)
    sources = sorted({a["llm"]["source"] for a in attempts if a.get("llm")})
    if explanation and explanation.get("source"):
        sources = sorted(set(sources) | {explanation["source"]})
    return {
        "status": status, "request": request, "final_game": final_game,
        "verify": final_v, "attempts": attempts, "explanation": explanation,
        "graph": graph.build(shown, v_for_graph), "sources": sources,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def analyze(game: dict, run_tag: str = "") -> dict:
    r = llm_client.call_json("analyze", prompts.analyze_messages(game), context={"game": game}, run_tag=run_tag)
    return {"ok": r.ok, "data": r.data, "llm": r.summary()}
