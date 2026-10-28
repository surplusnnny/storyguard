"""엔딩 도달 검증기.

엔딩 도달 판정은 이 파일만 한다. LLM의 "문제없다"는 말은 판정에 쓰지 않는다.
- validate(): 형식 검사(JSON Schema)와 참조 검사(없는 id를 가리키는지)
- explore(): BFS로 시작 상태에서 갈 수 있는 모든 상태를 탐색
- diagnose(): 엔딩에 못 가면 막힌 지점(blocker)을 거꾸로 추적
- diff(): 수정 전후를 비교해 요청하지 않은 변경을 찾음
- verify(): 위를 모두 묶은 결과
"""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Any

from .engine import Game, State, _list, josa

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "data" / "schema.json"

MAX_STATES = 50_000      # 상태 폭발 방지
TIME_LIMIT_SEC = 3.0     # 탐색 시간 제한

COLLECTIONS = ["items", "areas", "npcs", "quests", "events"]


# ---------------------------------------------------------------- 형식·참조 검사
def _schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate(data: Any) -> list[dict]:
    """형식 오류와 참조 오류 목록. 비어 있으면 통과."""
    errors: list[dict] = []
    if not isinstance(data, dict):
        return [{"type": "schema", "path": "$", "message": "game.json의 최상위가 객체가 아닙니다."}]
    try:
        import jsonschema
        validator = jsonschema.Draft7Validator(_schema())
        for e in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
            path = "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in e.path)
            errors.append({"type": "schema", "path": path, "message": e.message})
    except ImportError:  # jsonschema가 없으면 참조 검사만 한다
        errors.append({"type": "warning", "path": "$", "message": "jsonschema 미설치로 형식 검사를 건너뜀"})
    if any(e["type"] == "schema" for e in errors):
        return errors

    # 중복 id
    for col in COLLECTIONS:
        seen = set()
        for obj in data.get(col, []):
            if obj["id"] in seen:
                errors.append({"type": "reference", "path": f"{col}[{obj['id']}]",
                               "message": f"{col}에 id '{obj['id']}'가 두 번 있습니다."})
            seen.add(obj["id"])

    g = Game(data)
    def check(ids, table, path, what):
        for i in ids:
            if i not in table:
                errors.append({"type": "reference", "path": path,
                               "message": f"정의되지 않은 {what} '{i}'를 가리킵니다."})

    if g.start.get("area") not in g.areas:
        errors.append({"type": "reference", "path": "start.area",
                       "message": f"시작 지역 '{g.start.get('area')}'가 areas에 없습니다."})
    check(_list(g.start, "items"), g.items, "start.items", "아이템")
    for a in g.areas.values():
        check(_list(a, "connections"), g.areas, f"areas[{a['id']}].connections", "지역")
        check(_list(a, "requires_items"), g.items, f"areas[{a['id']}].requires_items", "아이템")
    for n in g.npcs.values():
        check([n.get("area")], g.areas, f"npcs[{n['id']}].area", "지역")
    for q in g.quests.values():
        p = f"quests[{q['id']}]"
        check([q.get("giver")], g.npcs, f"{p}.giver", "NPC")
        check([q.get("complete_area")], g.areas, f"{p}.complete_area", "지역")
        check(_list(q, "requires_quests"), g.quests, f"{p}.requires_quests", "퀘스트")
        for k in ("requires_items", "consumes_items", "reward_items"):
            check(_list(q, k), g.items, f"{p}.{k}", "아이템")
    for e in g.events.values():
        p = f"events[{e['id']}]"
        check([e.get("area")], g.areas, f"{p}.area", "지역")
        check(_list(e, "requires_quests"), g.quests, f"{p}.requires_quests", "퀘스트")
        for k in ("requires_items", "gives_items"):
            check(_list(e, k), g.items, f"{p}.{k}", "아이템")
    check(_list(g.ending, "requires_items"), g.items, "ending.requires_items", "아이템")
    return errors


# ---------------------------------------------------------------- BFS 탐색
def explore(g: Game) -> dict:
    start = g.initial_state()
    t0 = time.perf_counter()
    parent: dict[State, tuple[State | None, dict | None]] = {start: (None, None)}
    q = deque([start])
    goal: State | None = start if g.ending_reached(start) else None
    reached = {"areas": {start.area}, "items": set(start.items), "flags": set(start.flags),
               "quests": set(), "accepted": set(), "events": set()}
    first_step = {f"area:{start.area}": 0}
    depth = {start: 0}
    truncated = False

    while q and goal is None:
        if len(parent) > MAX_STATES or time.perf_counter() - t0 > TIME_LIMIT_SEC:
            truncated = True
            break
        s = q.popleft()
        for act in g.actions(s):
            n = g.apply(s, act)
            if n in parent:
                continue
            parent[n] = (s, act)
            depth[n] = depth[s] + 1
            d = depth[n]
            reached["areas"].add(n.area)
            first_step.setdefault(f"area:{n.area}", d)
            for i in n.items:
                reached["items"].add(i); first_step.setdefault(f"item:{i}", d)
            for fl in n.flags:
                reached["flags"].add(fl); first_step.setdefault(f"flag:{fl}", d)
            for qq in n.done:
                reached["quests"].add(qq); first_step.setdefault(f"quest:{qq}", d)
            reached["accepted"] |= set(n.accepted)
            for e in n.events:
                reached["events"].add(e); first_step.setdefault(f"event:{e}", d)
            if g.ending_reached(n):
                goal = n
                first_step.setdefault("ending:ending", d)
                break
            q.append(n)

    path: list[dict] = []
    if goal is not None:
        cur = goal
        while parent[cur][0] is not None:
            prev, act = parent[cur]
            path.append({"action": act, "text": g.describe(act)})
            cur = prev
        path.reverse()
        # 경로를 끝까지 찾았으면 나머지 상태를 더 탐색하지 않았으므로,
        # 그래프 표시용 도달 집합은 경로 위의 것이 아니라 전체 탐색 결과를 다시 모은다.
        reached_full = _reach_all(g)
        reached, first_step = reached_full["reached"], {**reached_full["first_step"], **first_step}
    return {
        "reachable": goal is not None,
        "path": path,
        "explored_states": len(parent),
        "truncated": truncated,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        "reached": {k: sorted(v) for k, v in reached.items()},
        "first_step": first_step,
    }


def _reach_all(g: Game) -> dict:
    """엔딩 여부와 무관하게 도달 가능한 모든 요소를 모은다(그래프 색칠용)."""
    start = g.initial_state()
    seen = {start}
    q = deque([(start, 0)])
    reached = {"areas": {start.area}, "items": set(start.items), "flags": set(start.flags),
               "quests": set(), "accepted": set(), "events": set()}
    first = {f"area:{start.area}": 0}
    t0 = time.perf_counter()
    while q:
        if len(seen) > MAX_STATES or time.perf_counter() - t0 > TIME_LIMIT_SEC:
            break
        s, d = q.popleft()
        for act in g.actions(s):
            n = g.apply(s, act)
            if n in seen:
                continue
            seen.add(n)
            reached["areas"].add(n.area); first.setdefault(f"area:{n.area}", d + 1)
            for i in n.items:
                reached["items"].add(i); first.setdefault(f"item:{i}", d + 1)
            for fl in n.flags:
                reached["flags"].add(fl); first.setdefault(f"flag:{fl}", d + 1)
            for qq in n.done:
                reached["quests"].add(qq); first.setdefault(f"quest:{qq}", d + 1)
            reached["accepted"] |= set(n.accepted)
            for e in n.events:
                reached["events"].add(e); first.setdefault(f"event:{e}", d + 1)
            if g.ending_reached(n):
                first.setdefault("ending:ending", d + 1)
            q.append((n, d + 1))
    return {"reached": reached, "first_step": first}


# ---------------------------------------------------------------- 막힌 지점 추적
def _sources(g: Game, kind: str, id_: str) -> list[str]:
    """아이템이나 플래그를 주는 곳."""
    out = []
    if kind == "item":
        if id_ in _list(g.start, "items"):
            out.append("start:start")
        out += [f"quest:{q['id']}" for q in g.quests.values() if id_ in _list(q, "reward_items")]
        out += [f"event:{e['id']}" for e in g.events.values() if id_ in _list(e, "gives_items")]
    elif kind == "flag":
        if id_ in _list(g.start, "flags"):
            out.append("start:start")
        out += [f"quest:{q['id']}" for q in g.quests.values() if id_ in _list(q, "reward_flags")]
        out += [f"event:{e['id']}" for e in g.events.values() if id_ in _list(e, "sets_flags")]
    return out


def diagnose(g: Game, reached: dict) -> tuple[list[dict], list[dict]]:
    """엔딩부터 거꾸로 따라가며 처음 끊긴 곳을 blocker로 낸다. (blockers, 경고)"""
    R = {
        "area": set(reached["areas"]), "item": set(reached["items"]), "flag": set(reached["flags"]),
        "quest": set(reached["quests"]), "event": set(reached["events"]),
    }
    blockers: list[dict] = []
    seen_keys: set[str] = set()

    def add(btype, target, requirement, message, chain):
        key = f"{btype}|{target}|{requirement}"
        if key in seen_keys:
            return
        seen_keys.add(key)
        blockers.append({
            "id": f"b{len(blockers) + 1}", "type": btype, "target": target,
            "requirement": requirement, "message": message, "chain": chain,
        })

    def label(ref: str) -> str:
        kind, id_ = ref.split(":", 1)
        if kind == "ending":
            return f"엔딩 '{g.ending.get('name', '엔딩')}'"
        kname = {"item": "아이템", "flag": "조건", "area": "지역", "quest": "퀘스트", "event": "이벤트", "start": "시작"}[kind]
        return f"{kname} '{g.name_of(kind, id_)}'"

    def need(kind: str, id_: str, chain: list[str], stack: set[str]):
        ref = f"{kind}:{id_}"
        if ref in stack:
            add("circular_dependency", chain[-1], ref,
                f"{label(chain[-1])}의 조건을 따라가면 다시 {josa(label(ref), '으로')} 돌아오는 순환이 있습니다.", chain + [ref])
            return
        stack = stack | {ref}
        chain = chain + [ref]
        if kind in ("item", "flag"):
            if id_ in R[kind]:
                return
            src = _sources(g, kind, id_)
            if not src:
                add("missing_source", chain[-2] if len(chain) > 1 else ref, ref,
                    f"{josa(label(ref), '을를')} 얻는 방법이 게임 어디에도 없습니다. "
                    f"그래서 {label(chain[-2]) if len(chain) > 1 else '엔딩'}의 조건을 채울 수 없습니다.", chain)
                return
            for s in src:
                if s.startswith("start"):
                    continue
                k, i = s.split(":", 1)
                need(k, i, chain, stack)
            return
        if kind == "area":
            if id_ in R["area"]:
                return
            a = g.areas[id_]
            missing = [("item", i) for i in _list(a, "requires_items") if i not in R["item"]]
            missing += [("flag", f) for f in _list(a, "requires_flags") if f not in R["flag"]]
            neighbors = [n for n, aa in g.areas.items() if id_ in _list(aa, "connections")]
            if not neighbors and id_ != g.start.get("area"):
                add("no_route", ref, ref, f"{josa(label(ref), '으로')} 이어지는 길이 없습니다.", chain)
                return
            if not missing:
                if not any(n in R["area"] for n in neighbors):
                    for n in neighbors:
                        need("area", n, chain, stack)
                return
            for k, i in missing:
                need(k, i, chain, stack)
            return
        if kind == "quest":
            if id_ in R["quest"]:
                return
            q = g.quests[id_]
            giver = g.npcs.get(q.get("giver", ""))
            for pq in _list(q, "requires_quests"):
                need("quest", pq, chain, stack)
            if giver and giver.get("area") not in R["area"]:
                need("area", giver["area"], chain, stack)
            if q.get("complete_area") not in R["area"]:
                need("area", q["complete_area"], chain, stack)
            for i in _list(q, "requires_items"):
                need("item", i, chain, stack)
            return
        if kind == "event":
            if id_ in R["event"]:
                return
            e = g.events[id_]
            if e.get("area") not in R["area"]:
                need("area", e["area"], chain, stack)
            for i in _list(e, "requires_items"):
                need("item", i, chain, stack)
            for f in _list(e, "requires_flags"):
                need("flag", f, chain, stack)
            for pq in _list(e, "requires_quests"):
                need("quest", pq, chain, stack)
            return

    root = ["ending:ending"]
    for i in _list(g.ending, "requires_items"):
        need("item", i, root, {"ending:ending"})
    for f in _list(g.ending, "requires_flags"):
        need("flag", f, root, {"ending:ending"})

    # 소비 아이템 때문에 막히는 경우처럼, 각각은 얻을 수 있지만 함께는 못 채우는 경우
    if not blockers:
        add("unreachable_combination", "ending:ending", "ending:ending",
            "엔딩 조건을 하나씩은 얻을 수 있지만 한 번의 플레이에서 함께 만족시킬 수 없습니다. "
            "아이템을 소모하는 퀘스트나 이벤트 순서를 확인해야 합니다.", root)

    warnings = []
    for qid, q in g.quests.items():
        if qid not in R["quest"]:
            warnings.append({"target": f"quest:{qid}", "message": f"퀘스트 '{q['name']}'는 완료할 수 없습니다."})
    for aid, a in g.areas.items():
        if aid not in R["area"]:
            warnings.append({"target": f"area:{aid}", "message": f"지역 '{a['name']}'에는 들어갈 수 없습니다."})
    return blockers, warnings


def unused_warnings(g: Game, reached: dict) -> list[dict]:
    out = []
    for qid, q in g.quests.items():
        if qid not in reached["quests"]:
            out.append({"target": f"quest:{qid}", "message": f"퀘스트 '{q['name']}'는 완료할 수 없습니다(엔딩에는 필요 없음)."})
    for aid, a in g.areas.items():
        if aid not in reached["areas"]:
            out.append({"target": f"area:{aid}", "message": f"지역 '{a['name']}'에는 들어갈 수 없습니다(엔딩에는 필요 없음)."})
    return out


# ---------------------------------------------------------------- 수정 전후 비교
def _index(data: dict, col: str) -> dict:
    return {o.get("id"): o for o in data.get(col, []) if isinstance(o, dict)}


def diff(before: dict, after: dict) -> list[dict]:
    """필드 단위 변경 목록. path 예: quests[q2].reward_items, items[magic_staff](추가)"""
    changes: list[dict] = []
    for col in COLLECTIONS:
        b, a = _index(before, col), _index(after, col)
        for id_ in b.keys() - a.keys():
            changes.append({"path": f"{col}[{id_}]", "kind": "removed", "before": b[id_], "after": None})
        for id_ in a.keys() - b.keys():
            changes.append({"path": f"{col}[{id_}]", "kind": "added", "before": None, "after": a[id_]})
        for id_ in sorted(a.keys() & b.keys()):
            for key in sorted(set(a[id_]) | set(b[id_])):
                if a[id_].get(key) != b[id_].get(key):
                    changes.append({"path": f"{col}[{id_}].{key}", "kind": "changed",
                                    "before": b[id_].get(key), "after": a[id_].get(key)})
    for sec in ("start", "ending"):
        bs, as_ = before.get(sec) or {}, after.get(sec) or {}
        for key in sorted(set(bs) | set(as_)):
            if bs.get(key) != as_.get(key):
                changes.append({"path": f"{sec}.{key}", "kind": "changed", "before": bs.get(key), "after": as_.get(key)})
    return changes


def _covered(path: str, declared: list[str]) -> bool:
    for d in declared:
        d = d.strip()
        if not d:
            continue
        if path == d or path.startswith(d + ".") or d.startswith(path + "."):
            return True
    return False


def unintended(changes: list[dict], declared: list[str] | None) -> list[dict]:
    """선언(plan.change)에 없는 변경. 선언된 변경의 새 값이 가리키는 새 아이템 정의 추가는 보조 변경으로 허용."""
    if declared is None:
        return []
    referenced: set[str] = set()
    for c in changes:
        if _covered(c["path"], declared) and isinstance(c.get("after"), (list, str)):
            vals = c["after"] if isinstance(c["after"], list) else [c["after"]]
            referenced |= {v for v in vals if isinstance(v, str)}
    out = []
    for c in changes:
        if _covered(c["path"], declared):
            continue
        if c["kind"] == "added" and c["path"].startswith(("items[", "npcs[", "events[", "quests[", "areas[")):
            new_id = c["path"].split("[", 1)[1].rstrip("]")
            if new_id in referenced:
                continue
        out.append(c)
    return out


# ---------------------------------------------------------------- 전체 검증
def verify(data: dict, original: dict | None = None, declared_paths: list[str] | None = None) -> dict:
    errors = validate(data)
    hard = [e for e in errors if e["type"] in ("schema", "reference")]
    result: dict[str, Any] = {
        "passed": False, "schema_errors": hard, "reachable": False, "path": [],
        "blockers": [], "warnings": [], "changes": [], "unintended_changes": [],
        "stats": {},
    }
    if original is not None:
        result["changes"] = diff(original, data)
        result["unintended_changes"] = unintended(result["changes"], declared_paths)
    if hard:
        result["blockers"] = [{
            "id": f"b{i + 1}", "type": "invalid_data", "target": e["path"], "requirement": e["path"],
            "message": e["message"], "chain": [],
        } for i, e in enumerate(hard)]
        return result

    g = Game(data)
    ex = explore(g)
    result["reachable"] = ex["reachable"]
    result["path"] = ex["path"]
    result["stats"] = {"explored_states": ex["explored_states"], "truncated": ex["truncated"],
                       "elapsed_ms": ex["elapsed_ms"]}
    result["reached"] = ex["reached"]
    result["first_step"] = ex["first_step"]
    if ex["reachable"]:
        result["warnings"] = unused_warnings(g, ex["reached"])
    else:
        full = _reach_all(g)
        result["reached"] = {k: sorted(v) for k, v in full["reached"].items()}
        result["first_step"] = full["first_step"]
        result["blockers"], result["warnings"] = diagnose(g, full["reached"])
        if ex["truncated"]:
            result["blockers"].insert(0, {
                "id": "b0", "type": "search_limit", "target": "ending:ending", "requirement": "",
                "message": f"탐색 한도({MAX_STATES}개 상태 또는 {TIME_LIMIT_SEC}초)에 걸려 끝까지 확인하지 못했습니다.",
                "chain": [],
            })
    result["passed"] = result["reachable"] and not result["unintended_changes"]
    return result


def load_game(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
