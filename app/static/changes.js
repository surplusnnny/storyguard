// 검증기가 찾은 '요청하지 않은 변경'(path, kind)을 사용자가 읽을 수 있는 문장으로 바꾼다.
// 예: areas[final_dungeon].requires_items → "지역 '마지막 던전' — 필요 아이템 바뀜"
const CHANGE_TYPE = { areas: "지역", quests: "퀘스트", events: "이벤트", items: "아이템", npcs: "NPC" };
const CHANGE_FIELD = {
  requires_items: "필요 아이템", requires_flags: "필요 조건", requires_quests: "필요 퀘스트",
  reward_items: "보상 아이템", reward_flags: "보상으로 생기는 조건", consumes_items: "소모 아이템",
  gives_items: "얻는 아이템", sets_flags: "만드는 조건", connections: "연결된 지역",
  complete_area: "완료 장소", giver: "퀘스트를 주는 사람", name: "이름", description: "설명", area: "발생 장소",
};
const CHANGE_KIND = { changed: "바뀜", added: "새로 추가됨", removed: "삭제됨" };

function describeChange(c, game) {
  const m = /^(\w+)\[([^\]]+)\](?:\.(\w+))?$/.exec(c.path || "");
  const kind = CHANGE_KIND[c.kind] || c.kind;
  if (!m || !CHANGE_TYPE[m[1]]) return `${c.path} — ${kind}`;
  const [, col, id, field] = m;
  const found = ((game || {})[col] || []).find((x) => x.id === id);
  const label = `${CHANGE_TYPE[col]} '${(found && found.name) || id}'`;
  if (field) return `${label} — ${CHANGE_FIELD[field] || field} ${kind}`;
  return `${label} — ${kind}`;
}

function describeChanges(list, game) {
  return (list || []).map((c) => describeChange(c, game));
}

if (typeof module !== "undefined") module.exports = { describeChange, describeChanges };
