"""화면의 '요청하지 않은 변경' 설명(app/static/changes.js)을 node로 시험한다. node가 없으면 건너뛴다."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "app" / "static" / "changes.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node가 없음")

GAME = {"areas": [{"id": "final_dungeon", "name": "마지막 던전"}],
        "quests": [{"id": "q2", "name": "두 번째 퀘스트"}],
        "events": [], "items": [{"id": "golden_key", "name": "황금 열쇠"}]}


def run(changes):
    code = ("const m = require(process.argv[1]);"
            "const r = m.describeChanges(JSON.parse(process.argv[2]), JSON.parse(process.argv[3]));"
            "console.log(JSON.stringify(r));")
    out = subprocess.run(["node", "-e", code, str(JS), json.dumps(changes), json.dumps(GAME)],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


def test_changed_field_uses_names():
    r = run([{"path": "areas[final_dungeon].requires_items", "kind": "changed"}])
    assert r == ["지역 '마지막 던전' — 필요 아이템 바뀜"]


def test_added_entity_without_known_name_uses_id():
    r = run([{"path": "events[hidden_cache]", "kind": "added"}])
    assert r == ["이벤트 'hidden_cache' — 새로 추가됨"]


def test_removed_and_reward_field():
    r = run([{"path": "quests[q2].reward_items", "kind": "changed"}, {"path": "items[golden_key]", "kind": "removed"}])
    assert r == ["퀘스트 '두 번째 퀘스트' — 보상 아이템 바뀜", "아이템 '황금 열쇠' — 삭제됨"]


def test_unknown_path_falls_back_to_raw_text():
    assert run([{"path": "meta.title", "kind": "changed"}]) == ["meta.title — 바뀜"]
