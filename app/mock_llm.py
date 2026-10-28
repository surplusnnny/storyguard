"""GPU 서버 없이 개발·연습할 때 쓰는 모의 LLM (LLM_MODE=mock).

진짜 LLM이 아니다. 시연 시나리오와 몇 가지 정해진 요청 형태만 처리한다.
처리하지 못하는 요청은 지어내지 않고 question으로 "모의 모드에서는 처리할 수 없음"을 돌려준다.
화면에는 항상 "모의 응답"으로 표시되며, 모의 결과는 발표 숫자로 쓰지 않는다.

rule_explain()은 LLM 설명이 실패했을 때 파이프라인이 쓰는 규칙 기반 설명이기도 하다.
"""
from __future__ import annotations

import copy
import hashlib
import re

from .engine import Game, _list, josa

KNOWN_IDS = {"마법 지팡이": "magic_staff", "은 열쇠": "silver_key", "방패": "shield", "지도": "map",
             "물약": "potion", "횃불": "torch", "황금 열쇠": "golden_key"}
ORDINALS = {"첫": 0, "첫 번째": 0, "두": 1, "두 번째": 1, "세": 2, "세 번째": 2, "네": 3, "네 번째": 3}


def _item_id(game: dict, name: str) -> tuple[str, bool]:
    for it in game.get("items", []):
        if it.get("name") == name:
            return it["id"], False
    base = KNOWN_IDS.get(name) or "item_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:6]
    return base, True


def _find_quest(game: dict, text: str) -> dict | None:
    quests = game.get("quests", [])
    m = re.search(r"(첫|두|세|네)\s*번째\s*퀘스트", text)
    if m and ORDINALS[m.group(1)] < len(quests):
        return quests[ORDINALS[m.group(1)]]
    m = re.search(r"\b(q\d+)\b", text)
    if m:
        return next((q for q in quests if q["id"] == m.group(1)), None)
    for q in quests:
        if q.get("name") and q["name"] in text:
            return q
    return None


# ------------------------------------------------------------------ 수정 (B-2)
def _modify(ctx: dict) -> dict:
    game, req = ctx["game"], ctx["request"]
    g2 = copy.deepcopy(game)

    m = re.search(r"보상(?:을|를)?\s*(.+?)에서\s*(.+?)(?:으로|로)\s*(?:바꿔|변경)", req)
    q = _find_quest(game, req)
    if m and q:
        old_name, new_name = m.group(1).strip(), m.group(2).strip()
        new_id, is_new = _item_id(game, new_name)
        q2 = next(x for x in g2["quests"] if x["id"] == q["id"])
        old_id, _ = _item_id(game, old_name)
        rewards = [new_id if r == old_id else r for r in _list(q2, "reward_items")]
        if new_id not in rewards:
            rewards.append(new_id)
        q2["reward_items"] = rewards
        change = [{"path": f"quests[{q['id']}].reward_items", "from": old_name, "to": new_name}]
        if is_new:
            g2["items"].append({"id": new_id, "name": new_name, "description": f"{q['name']} 보상"})
            change.append({"path": f"items[{new_id}]", "from": None, "to": new_name})
        return {"plan": {"change": change, "keep": ["다른 퀘스트와 지역 조건"]},
                "modified_game": g2,
                "warnings": [f"{josa(old_name, '이가')} 다른 곳에 필요하면 진행이 막힐 수 있음"], "question": None}

    m = re.search(r"(\S+?)(?:의)?\s*대화를\s*['\"“]?(.+?)['\"”]?\s*(?:으로|로)\s*(?:바꿔|변경)", req)
    if m:
        npc = next((n for n in g2["npcs"] if n["name"] == m.group(1)), None)
        if npc:
            npc["dialogue"] = [m.group(2)]
            return {"plan": {"change": [{"path": f"npcs[{npc['id']}].dialogue", "from": None, "to": m.group(2)}],
                             "keep": ["퀘스트와 아이템"]},
                    "modified_game": g2, "warnings": [], "question": None}

    return {"plan": {"change": [], "keep": []}, "modified_game": None, "warnings": [],
            "question": "모의 모드에서는 이 요청을 처리할 수 없습니다. GPU 서버에 연결한 live 모드에서 다시 시도해 주세요."}


# ------------------------------------------------------------------ 설명 (B-3) / 규칙 기반 설명
def rule_explain(game: dict, verify: dict, changes: list[dict]) -> dict:
    g = Game(game)
    blockers = verify.get("blockers", [])
    if not blockers and verify.get("unintended_changes"):
        paths = ", ".join(c["path"] for c in verify["unintended_changes"][:3])
        return {"problem": "요청하지 않은 부분까지 바뀌었습니다.",
                "cause": f"이번 수정에서 요청과 관계없는 곳({paths})이 함께 바뀌었습니다.",
                "blocker_ids": [],
                "fixes": [{"title": "요청한 부분만 다시 수정", "description": "요청하지 않은 변경을 되돌립니다.",
                           "keeps_user_intent": True, "action": {"type": "revert_unintended"}}]}
    if not blockers:
        return {"problem": "문제가 발견되지 않았습니다.", "cause": "검증 결과만으로는 원인을 확인할 수 없음",
                "blocker_ids": [], "fixes": []}
    b = blockers[0]
    if b["type"] == "missing_source" and b["requirement"].startswith("item:"):
        item = b["requirement"].split(":", 1)[1]
        item_name = g.name_of("item", item)
        tkind, tid = b["target"].split(":", 1)
        tname = g.name_of(tkind, tid)
        quest_id, new_item = None, None
        for c in changes:
            if c["path"].endswith(".reward_items") and isinstance(c.get("before"), list) and item in c["before"]:
                quest_id = c["path"].split("[", 1)[1].split("]")[0]
                added = [x for x in (c.get("after") or []) if x not in c["before"]]
                new_item = added[0] if added else None
        problem = (f"플레이어가 {tname} 앞에서 더 이상 진행할 수 없습니다." if tkind == "area"
                   else f"플레이어가 '{tname}' 단계를 할 수 없어 엔딩에 도달하지 못합니다.")
        cause = (f"{tname}에 들어가려면 {josa(item_name, '이가')} 필요한데, 이번 수정으로 {josa(item_name, '을를')} 얻을 수 있는 곳이 사라졌습니다."
                 if tkind == "area" else f"'{tname}'에 {josa(item_name, '이가')} 필요한데 얻을 방법이 없습니다.")
        fixes = []
        if quest_id:
            qname = g.name_of("quest", quest_id)
            fixes.append({"title": f"보상에 {item_name}도 함께 주기",
                          "description": f"'{qname}'의 보상을 {josa(g.name_of('item', new_item) if new_item else '새 아이템', '과와')} {item_name} 두 가지로 바꿉니다.",
                          "keeps_user_intent": True,
                          "action": {"type": "add_reward", "quest": quest_id, "item": item}})
        if tkind == "area" and new_item:
            fixes.append({"title": f"{tname} 입장 조건을 {josa(g.name_of('item', new_item), '으로')} 바꾸기",
                          "description": f"{tname}에 {item_name} 대신 {josa(g.name_of('item', new_item), '을를')} 가지고 들어가게 합니다.",
                          "keeps_user_intent": True,
                          "action": {"type": "swap_requirement", "area": tid, "from": item, "to": new_item}})
        near = None
        if tkind == "area":
            near = next((a for a, aa in g.areas.items() if tid in _list(aa, "connections")), None)
        if near:
            fixes.append({"title": f"{g.name_of('area', near)}에서 {item_name} 얻기",
                          "description": f"{g.name_of('area', near)}에 {josa(item_name, '을를')} 줍는 이벤트를 추가합니다.",
                          "keeps_user_intent": True,
                          "action": {"type": "add_event", "area": near, "item": item}})
        return {"problem": problem, "cause": cause, "blocker_ids": [b["id"]], "fixes": fixes}
    return {"problem": "플레이어가 엔딩에 도달할 수 없습니다.",
            "cause": b["message"], "blocker_ids": [b["id"]],
            "fixes": [{"title": "막힌 조건 다시 보기", "description": "검증 결과에 나온 조건을 직접 고칩니다.",
                       "keeps_user_intent": True, "action": {"type": "none"}}]}


# ------------------------------------------------------------------ 재수정 (B-4)
def _repair(ctx: dict) -> dict:
    failed = copy.deepcopy(ctx["failed_game"])
    fix = ctx.get("chosen_fix") or {}
    action = fix.get("action")
    if not action:
        fixes = rule_explain(ctx["failed_game"], ctx["verify"], ctx.get("changes", [])).get("fixes", [])
        tried = {str(p.get("action")) for p in ctx.get("previous", [])}
        action = next((f["action"] for f in fixes if str(f["action"]) not in tried), None)
    if not action or action.get("type") in (None, "none"):
        return {"reasoning": "모의 모드에서 적용할 수 있는 해결 방법이 없습니다.", "changes": [],
                "modified_game": None, "reason": "모의 모드에서는 이 문제를 고칠 수 없음"}
    t = action["type"]
    if t == "add_reward":
        q = next(x for x in failed["quests"] if x["id"] == action["quest"])
        before = list(_list(q, "reward_items"))
        q["reward_items"] = before + [action["item"]]
        return {"reasoning": "새 보상은 유지하고 원래 필요한 아이템도 함께 주도록 했습니다.",
                "changes": [{"path": f"quests[{q['id']}].reward_items", "from": before, "to": q["reward_items"]}],
                "modified_game": failed, "reason": None, "_action": action}
    if t == "swap_requirement":
        a = next(x for x in failed["areas"] if x["id"] == action["area"])
        before = list(_list(a, "requires_items"))
        a["requires_items"] = [action["to"] if i == action["from"] else i for i in before]
        return {"reasoning": "입장 조건을 새 보상 아이템으로 바꿨습니다.",
                "changes": [{"path": f"areas[{a['id']}].requires_items", "from": before, "to": a["requires_items"]}],
                "modified_game": failed, "reason": None, "_action": action}
    if t == "add_event":
        eid = f"find_{action['item']}"
        failed["events"].append({"id": eid, "name": "숨겨진 상자", "area": action["area"],
                                 "requires_items": [], "requires_flags": [], "requires_quests": [],
                                 "gives_items": [action["item"]], "sets_flags": []})
        return {"reasoning": "가까운 지역에 필요한 아이템을 얻는 이벤트를 추가했습니다.",
                "changes": [{"path": f"events[{eid}]", "from": None, "to": "숨겨진 상자"}],
                "modified_game": failed, "reason": None, "_action": action}
    return {"reasoning": "", "changes": [], "modified_game": None, "reason": f"알 수 없는 해결 방법: {t}"}


def _analyze(ctx: dict) -> dict:
    g = Game(ctx["game"])
    flow = [{"step": f"{g.name_of('npc', q.get('giver', ''))}의 '{q['name']}'", "refs": [q["id"]]}
            for q in g.quests.values()]
    flow.append({"step": g.ending.get("name", "엔딩"), "refs": ["ending"]})
    keys = []
    for a in g.areas.values():
        for i in _list(a, "requires_items"):
            keys.append({"item": g.name_of("item", i), "why_important": f"{a['name']} 입장에 필요", "refs": [a["id"], i]})
    return {"summary": f"{g.data.get('meta', {}).get('title', '게임')}: 지역 {len(g.areas)}곳, 퀘스트 {len(g.quests)}개, "
                       f"아이템 {len(g.items)}개로 된 게임입니다. (모의 모드 요약)",
            "main_flow": flow, "key_items": keys,
            "risky_points": [{"point": f"{josa(k['item'], '을를')} 주는 곳을 바꾸면 {k['why_important'].split(' ')[0]}에 못 갈 수 있음",
                              "refs": k["refs"]} for k in keys]}


def respond(prompt_name: str, ctx: dict) -> dict:
    if prompt_name == "modify":
        return _modify(ctx)
    if prompt_name == "explain":
        return rule_explain(ctx["game"], ctx["verify"], ctx.get("changes", []))
    if prompt_name == "repair":
        return _repair(ctx)
    if prompt_name == "analyze":
        return _analyze(ctx)
    return {}
