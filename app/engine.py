"""게임 규칙 엔진.

검증기(verifier.py)와 게임 플레이 화면이 같은 규칙을 쓰도록 규칙을 이 파일 한 곳에만 둔다.
LLM은 이 파일을 고치지 않는다. LLM은 game.json만 수정한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def josa(word: str, pair: str) -> str:
    """받침에 맞는 조사를 붙인다. pair: 이가, 을를, 은는, 과와, 으로"""
    if not word:
        return word
    ch = word[-1]
    code = ord(ch) - 0xAC00
    has_final = 0 <= code <= 11171 and code % 28 != 0
    final_is_l = 0 <= code <= 11171 and code % 28 == 8  # ㄹ 받침
    if pair == "으로":
        return word + ("로" if (not has_final or final_is_l) else "으로")
    first, second = pair[0], pair[1]
    if not (0 <= code <= 11171):  # 한글이 아니면 받침 없는 것으로 본다
        return word + second
    return word + (first if has_final else second)


def _list(obj: dict, key: str) -> list:
    value = obj.get(key) or []
    return list(value) if isinstance(value, list) else []


@dataclass(frozen=True)
class State:
    """플레이어 상태. BFS에서 집합 비교가 가능하도록 모두 frozenset으로 둔다."""

    area: str
    items: frozenset = field(default_factory=frozenset)
    flags: frozenset = field(default_factory=frozenset)
    accepted: frozenset = field(default_factory=frozenset)
    done: frozenset = field(default_factory=frozenset)
    events: frozenset = field(default_factory=frozenset)

    def to_dict(self) -> dict:
        return {
            "area": self.area,
            "items": sorted(self.items),
            "flags": sorted(self.flags),
            "accepted": sorted(self.accepted),
            "done": sorted(self.done),
            "events": sorted(self.events),
        }

    @staticmethod
    def from_dict(d: dict) -> "State":
        return State(
            area=d["area"],
            items=frozenset(d.get("items", [])),
            flags=frozenset(d.get("flags", [])),
            accepted=frozenset(d.get("accepted", [])),
            done=frozenset(d.get("done", [])),
            events=frozenset(d.get("events", [])),
        )


class Game:
    """game.json을 읽기 쉬운 형태로 감싼다."""

    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.items = {i["id"]: i for i in data.get("items", [])}
        self.areas = {a["id"]: a for a in data.get("areas", [])}
        self.npcs = {n["id"]: n for n in data.get("npcs", [])}
        self.quests = {q["id"]: q for q in data.get("quests", [])}
        self.events = {e["id"]: e for e in data.get("events", [])}
        self.ending = data.get("ending", {}) or {}
        self.start = data.get("start", {}) or {}

    # ---------- 이름 ----------
    def name_of(self, kind: str, id_: str) -> str:
        table = {
            "item": self.items, "area": self.areas, "npc": self.npcs,
            "quest": self.quests, "event": self.events,
        }.get(kind, {})
        if id_ in table:
            return table[id_].get("name", id_)
        if kind == "flag":
            return FLAG_NAMES.get(id_, id_)
        return id_

    def initial_state(self) -> State:
        return State(
            area=self.start.get("area", ""),
            items=frozenset(_list(self.start, "items")),
            flags=frozenset(_list(self.start, "flags")),
        )

    # ---------- 조건 ----------
    def area_open(self, area_id: str, s: State) -> bool:
        a = self.areas.get(area_id)
        if not a:
            return False
        return set(_list(a, "requires_items")) <= s.items and set(_list(a, "requires_flags")) <= s.flags

    def ending_reached(self, s: State) -> bool:
        return (set(_list(self.ending, "requires_items")) <= s.items
                and set(_list(self.ending, "requires_flags")) <= s.flags)

    # ---------- 행동 ----------
    def actions(self, s: State) -> list[dict]:
        """현재 상태에서 할 수 있는 행동 목록. 순서가 고정되어 있어 BFS 결과가 매번 같다."""
        acts: list[dict] = []
        here = self.areas.get(s.area)
        if here:
            for nxt in _list(here, "connections"):
                if nxt in self.areas and self.area_open(nxt, s):
                    acts.append({"type": "move", "target": nxt})
        for q in self.quests.values():
            qid = q["id"]
            giver = self.npcs.get(q.get("giver", ""))
            if (qid not in s.accepted and qid not in s.done and giver
                    and giver.get("area") == s.area
                    and set(_list(q, "requires_quests")) <= s.done):
                acts.append({"type": "accept", "target": qid})
        for q in self.quests.values():
            qid = q["id"]
            if (qid in s.accepted and qid not in s.done
                    and q.get("complete_area") == s.area
                    and set(_list(q, "requires_items")) <= s.items):
                acts.append({"type": "complete", "target": qid})
        for e in self.events.values():
            eid = e["id"]
            if (eid not in s.events and e.get("area") == s.area
                    and set(_list(e, "requires_items")) <= s.items
                    and set(_list(e, "requires_flags")) <= s.flags
                    and set(_list(e, "requires_quests")) <= s.done):
                acts.append({"type": "event", "target": eid})
        return acts

    def apply(self, s: State, act: dict) -> State:
        t, target = act["type"], act["target"]
        if t == "move":
            return State(target, s.items, s.flags, s.accepted, s.done, s.events)
        if t == "accept":
            return State(s.area, s.items, s.flags, s.accepted | {target}, s.done, s.events)
        if t == "complete":
            q = self.quests[target]
            items = (s.items - set(_list(q, "consumes_items"))) | set(_list(q, "reward_items"))
            flags = s.flags | set(_list(q, "reward_flags"))
            return State(s.area, frozenset(items), frozenset(flags), s.accepted, s.done | {target}, s.events)
        if t == "event":
            e = self.events[target]
            items = s.items | set(_list(e, "gives_items"))
            flags = s.flags | set(_list(e, "sets_flags"))
            return State(s.area, frozenset(items), frozenset(flags), s.accepted, s.done, s.events | {target})
        raise ValueError(f"알 수 없는 행동: {t}")

    def describe(self, act: dict) -> str:
        t, target = act["type"], act["target"]
        if t == "move":
            return f"{josa(self.name_of('area', target), '으로')} 이동"
        if t == "accept":
            q = self.quests[target]
            return f"{self.name_of('npc', q.get('giver', ''))}에게서 '{q.get('name', target)}' 퀘스트 받기"
        if t == "complete":
            q = self.quests[target]
            rewards = ", ".join(self.name_of("item", i) for i in _list(q, "reward_items"))
            tail = f" → {rewards} 획득" if rewards else ""
            return f"'{q.get('name', target)}' 완료{tail}"
        if t == "event":
            e = self.events[target]
            gives = ", ".join(self.name_of("item", i) for i in _list(e, "gives_items"))
            tail = f" → {gives} 획득" if gives else ""
            return f"{e.get('name', target)}{tail}"
        return f"{t} {target}"


FLAG_NAMES = {"boss_defeated": "보스 처치"}
