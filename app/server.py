"""웹 서버. 실행: python -m uvicorn app.server:app --port 8501 (run.bat)

상태는 서버에 두지 않고 화면이 들고 다닌다(원본 게임, 현재 게임). 새로 고쳐도 서버가 꼬이지 않게 하기 위함.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, graph, llm_client, pipeline
from .engine import Game, State
from .verifier import load_game, verify

STATIC = Path(__file__).resolve().parent / "static"
GAMES = config.DATA / "games"

app = FastAPI(title="StoryGuard")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class GameBody(BaseModel):
    game: dict


class VerifyBody(BaseModel):
    game: dict
    original: dict | None = None
    declared: list[str] | None = None


class ModifyBody(BaseModel):
    game: dict
    request: str
    auto_retry: bool = True


class FixBody(BaseModel):
    original: dict
    request: str
    failed_game: dict
    fix: dict
    intent_paths: list[str] = []
    declared: list[str] = []


class PlayBody(BaseModel):
    game: dict
    state: dict | None = None
    action: dict | None = None


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    return {"mode": config.mode(), "models": config.models(), "base_url": config.base_url() if config.mode() == "live" else "",
            "replay_fallback": config.replay_fallback(),
            "recordings": len(list(config.RECORDINGS.glob("*.json"))) if config.RECORDINGS.exists() else 0}


@app.get("/api/health")
def health():
    """GPU 서버 연결 확인(화면 상단 배지용). live 모드가 아니면 확인하지 않는다."""
    if config.mode() != "live":
        return {"ok": None, "message": f"{config.mode()} 모드라 GPU 서버를 확인하지 않음"}
    try:
        ids = llm_client.list_models()
        missing = [m for m in config.models() if m not in ids]
        return {"ok": not missing, "server_models": ids, "missing": missing,
                "message": "연결됨" if not missing else f"서버에 없는 모델: {', '.join(missing)}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"GPU 서버에 연결하지 못함: {exc}"}


@app.get("/api/games")
def games():
    return [p.stem for p in sorted(GAMES.glob("*.json"))]


@app.get("/api/game/{name}")
def game(name: str):
    p = GAMES / f"{Path(name).name}.json"
    if not p.exists():
        return JSONResponse({"error": "없는 게임"}, status_code=404)
    data = load_game(p)
    v = verify(data)
    return {"game": data, "verify": v, "graph": graph.build(data, v)}


@app.post("/api/verify")
def api_verify(b: VerifyBody):
    v = verify(b.game, b.original, b.declared)
    return {"verify": v, "graph": graph.build(b.game, v)}


@app.post("/api/analyze")
def api_analyze(b: GameBody):
    return pipeline.analyze(b.game, run_tag="ui")


@app.post("/api/modify")
def api_modify(b: ModifyBody):
    return pipeline.modify(b.game, b.request, auto_retry=b.auto_retry, run_tag="ui")


@app.post("/api/apply_fix")
def api_apply_fix(b: FixBody):
    return pipeline.apply_fix(b.original, b.request, b.failed_game, b.fix, b.intent_paths, b.declared, run_tag="ui")


# ------------------------------------------------------------------ 게임 플레이(검증기와 같은 규칙 엔진 사용)
def _play_view(g: Game, s: State) -> dict:
    acts = g.actions(s)
    npcs = [{"id": n["id"], "name": n["name"], "dialogue": n.get("dialogue", [])}
            for n in g.npcs.values() if n.get("area") == s.area]
    return {"state": s.to_dict(), "area_name": g.name_of("area", s.area),
            "items": [{"id": i, "name": g.name_of("item", i)} for i in sorted(s.items)],
            "npcs": npcs, "ending": g.ending_reached(s), "ending_name": g.ending.get("name", "엔딩"),
            "actions": [{**a, "text": g.describe(a)} for a in acts]}


@app.post("/api/play")
def api_play(b: PlayBody):
    g = Game(b.game)
    s = State.from_dict(b.state) if b.state else g.initial_state()
    log = None
    if b.action:
        legal = g.actions(s)
        act = {"type": b.action.get("type"), "target": b.action.get("target")}
        if act not in legal:
            return JSONResponse({"error": "지금은 할 수 없는 행동입니다."}, status_code=400)
        log = g.describe(act)
        s = g.apply(s, act)
    out = _play_view(g, s)
    out["log"] = log
    return out


@app.post("/api/save_game")
def save_game(b: GameBody):
    """수정된 게임을 data/games/edited_game.json으로 저장(시연 뒤 확인용)."""
    p = GAMES / "edited_game.json"
    p.write_text(json.dumps(b.game, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": str(p.relative_to(config.ROOT))}
