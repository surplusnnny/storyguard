"""스토리 진행 그래프. 화면에 그릴 노드와 화살표를 만든다.

화살표는 "앞의 것이 있어야 뒤의 것을 할 수 있다"는 선행 관계다.
노드 색은 검증 결과(도달 가능/불가/막힌 지점)로 정한다.
"""
from __future__ import annotations

from .engine import Game, _list


def build(data: dict, verify_result: dict) -> dict:
    g = Game(data)
    reached = verify_result.get("reached") or {}
    R = {
        "area": set(reached.get("areas", [])), "item": set(reached.get("items", [])),
        "flag": set(reached.get("flags", [])), "quest": set(reached.get("quests", [])),
        "event": set(reached.get("events", [])),
    }
    first = verify_result.get("first_step") or {}
    blocked_targets = {b["target"] for b in verify_result.get("blockers", [])}
    blocked_reqs = {b["requirement"] for b in verify_result.get("blockers", [])}
    path_refs = set()
    for p in verify_result.get("path", []):
        a = p["action"]
        kind = {"move": "area", "accept": "quest", "complete": "quest", "event": "event"}[a["type"]]
        path_refs.add(f"{kind}:{a['target']}")

    nodes, edges = {}, []

    def node(ref: str, label: str, kind: str, sub: str = ""):
        k, id_ = ref.split(":", 1)
        if ref == "ending:ending":
            ok = verify_result.get("reachable", False)
        else:
            ok = id_ in R.get(k, set())
        status = "ok" if ok else "unreachable"
        if ref in blocked_targets:
            status = "blocked"
        if ref in blocked_reqs and not ok:
            status = "missing"
        nodes[ref] = {"id": ref, "label": label, "kind": kind, "sub": sub, "status": status,
                      "depth": first.get(ref), "on_path": ref in path_refs or (ref == "ending:ending" and ok)}

    def edge(a: str, b: str, rel: str):
        if a in nodes and b in nodes:
            edges.append({"from": a, "to": b, "rel": rel})

    for a in g.areas.values():
        node(f"area:{a['id']}", a["name"], "area")
    for q in g.quests.values():
        node(f"quest:{q['id']}", q["name"], "quest", g.name_of("npc", q.get("giver", "")))
    for e in g.events.values():
        node(f"event:{e['id']}", e["name"], "event")
    used_items = set()
    for col in (g.quests.values(), g.events.values(), g.areas.values()):
        for o in col:
            for k in ("requires_items", "reward_items", "gives_items", "consumes_items"):
                used_items |= set(_list(o, k))
    used_items |= set(_list(g.ending, "requires_items"))
    for i in sorted(used_items):
        node(f"item:{i}", g.name_of("item", i), "item")
    node("ending:ending", g.ending.get("name", "엔딩"), "ending")

    # 조건(flag)은 노드로 그리지 않고, 조건을 만드는 곳 → 조건이 필요한 곳으로 바로 잇는다(지도를 작게 유지)
    flag_src: dict[str, list[str]] = {}
    for q in g.quests.values():
        for f in _list(q, "reward_flags"):
            flag_src.setdefault(f, []).append(f"quest:{q['id']}")
    for e in g.events.values():
        for f in _list(e, "sets_flags"):
            flag_src.setdefault(f, []).append(f"event:{e['id']}")

    def flag_edges(f: str, dst: str):
        for src in flag_src.get(f, []):
            edge(src, dst, g.name_of("flag", f))

    # 지역 연결: 시작 지역에서 가까운 쪽 → 먼 쪽 방향 한 번만
    seen_pairs = set()
    for a in g.areas.values():
        for b in _list(a, "connections"):
            pair = tuple(sorted([a["id"], b]))
            if pair in seen_pairs or b not in g.areas:
                continue
            seen_pairs.add(pair)
            da, db = first.get(f"area:{a['id']}", 99), first.get(f"area:{b}", 99)
            src, dst = (a["id"], b) if da <= db else (b, a["id"])
            edge(f"area:{src}", f"area:{dst}", "길")
        for i in _list(a, "requires_items"):
            edge(f"item:{i}", f"area:{a['id']}", "입장 조건")
        for f in _list(a, "requires_flags"):
            flag_edges(f, f"area:{a['id']}")
    for q in g.quests.values():
        ref = f"quest:{q['id']}"
        for pq in _list(q, "requires_quests"):
            edge(f"quest:{pq}", ref, "선행 퀘스트")
        edge(f"area:{q.get('complete_area')}", ref, "완료 장소")
        for i in _list(q, "requires_items"):
            edge(f"item:{i}", ref, "필요")
        for i in _list(q, "reward_items"):
            edge(ref, f"item:{i}", "보상")
    for e in g.events.values():
        ref = f"event:{e['id']}"
        edge(f"area:{e.get('area')}", ref, "장소")
        for i in _list(e, "requires_items"):
            edge(f"item:{i}", ref, "필요")
        for f in _list(e, "requires_flags"):
            flag_edges(f, ref)
        for pq in _list(e, "requires_quests"):
            edge(f"quest:{pq}", ref, "선행 퀘스트")
        for i in _list(e, "gives_items"):
            edge(ref, f"item:{i}", "획득")
    for i in _list(g.ending, "requires_items"):
        edge(f"item:{i}", "ending:ending", "엔딩 조건")
    for f in _list(g.ending, "requires_flags"):
        flag_edges(f, "ending:ending")

    # 열 배치: 도달한 것은 처음 도달한 단계, 아닌 것은 선행 요소 다음 열
    _assign_columns(nodes, edges)
    return {"nodes": list(nodes.values()), "edges": edges}


def _assign_columns(nodes: dict, edges: list[dict]):
    preds: dict[str, list[str]] = {n: [] for n in nodes}
    for e in edges:
        preds[e["to"]].append(e["from"])
    col: dict[str, int] = {}

    def depth(n: str, stack: frozenset) -> int:
        if n in col:
            return col[n]
        if n in stack:
            return 0
        ps = [p for p in preds[n] if p not in stack]
        d = 0 if not ps else 1 + max(depth(p, stack | {n}) for p in ps)
        col[n] = d
        return d

    for n in nodes:
        depth(n, frozenset())
    for n, v in nodes.items():
        v["col"] = col[n]
