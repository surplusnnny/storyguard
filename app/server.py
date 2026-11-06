"""웹 서버. 실행: python -m uvicorn app.server:app --port 8501 (run.bat)

상태는 서버에 두지 않고 화면이 들고 다닌다(원본 게임, 현재 게임). 새로 고쳐도 서버가 꼬이지 않게 하기 위함.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, graph, llm_client, pipeline, storage
from .engine import Game, State
from .verifier import load_game, verify

STATIC = Path(__file__).resolve().parent / "static"
GAMES = config.DATA / "games"

app = FastAPI(title="StoryGuard")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

MAX_BODY = 300_000  # 게임 데이터는 수 KB. 이보다 큰 요청은 거절한다(저장소·AI 호출 남용 방지)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


@app.middleware("http")
async def guard(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY:
        resp = JSONResponse({"error": "요청이 너무 큽니다."}, status_code=413)
    else:
        resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):  # 자동 API 문서는 외부 스크립트를 쓴다
        resp.headers["Content-Security-Policy"] = CSP
    return resp


_UNREADABLE = [{"type": "schema", "path": "$", "message": "게임 데이터를 해석하지 못했습니다. data/schema.json 형식을 확인하세요."}]


def _safe_verify(game: dict, original: dict | None = None, declared: list[str] | None = None) -> dict:
    """형식이 깨진 게임이 와도 서버 오류 대신 오류 목록을 돌려준다(외부 사용자가 올린 파일 대비)."""
    try:
        return verify(game, original, declared)
    except Exception:  # noqa: BLE001 - 검증기가 아예 읽지 못하는 경우
        return {"reachable": False, "passed": False, "blockers": [], "warnings": [], "changes": [],
                "unintended_changes": [], "path": [], "schema_errors": _UNREADABLE}


def _bad_game(*games: dict):
    """형식 오류가 있으면 422 응답을, 없으면 None을 돌려준다. AI를 부르기 전에 거른다."""
    for g in games:
        errs = _safe_verify(g).get("schema_errors") or []
        if errs:
            return JSONResponse({"error": "게임 데이터 형식 오류", "schema_errors": errs}, status_code=422)
    return None


class GameBody(BaseModel):
    game: dict


class VerifyBody(BaseModel):
    game: dict
    original: dict | None = None
    declared: list[str] | None = None


class ModifyBody(BaseModel):
    game: dict
    request: str = Field(max_length=500)
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
    # 공개 사이트(Vercel)에서는 GPU 서버 주소를 내보내지 않는다
    show_url = config.mode() == "live" and config.provider() == "vllm" and not config.on_vercel()
    return {"mode": config.mode(), "provider": config.provider(), "models": config.models(),
            "base_url": config.base_url() if show_url else "",
            "replay_fallback": config.replay_fallback(),
            "store": storage.backend(), "recordings": storage.count_recordings()}


@app.get("/api/health")
def health():
    """GPU 서버 연결 확인(화면 상단 배지용). live 모드가 아니면 확인하지 않는다."""
    if config.mode() != "live":
        why = {"replay": "저장된 결과를 보여 주는 중이라", "replay_first": "저장된 결과를 먼저 쓰는 중이라",
               "mock": "모의 모드라"}.get(config.mode(), f"{config.mode()} 모드라")
        return {"ok": None, "message": f"{why} AI 서버를 확인하지 않음"}
    target = "Claude API" if config.provider() == "anthropic" else "GPU 서버"
    try:
        ids = llm_client.list_models()
        missing = [m for m in config.models() if m not in ids]
        return {"ok": not missing, "server_models": ids, "missing": missing,
                "message": "연결됨" if not missing else f"서버에 없는 모델: {', '.join(missing)}"}
    except Exception as exc:  # noqa: BLE001
        if config.on_vercel():  # 예외 문구에 서버 주소가 들어 있을 수 있어 공개 사이트에서는 종류만 보인다
            return {"ok": False, "message": f"{target}에 연결하지 못함 ({type(exc).__name__})"}
        return {"ok": False, "message": f"{target}에 연결하지 못함: {exc}"}


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
    v = _safe_verify(b.game, b.original, b.declared)
    if v.get("schema_errors"):
        return {"verify": v, "graph": None}  # 형식이 깨졌으면 지도를 그리지 않는다
    return {"verify": v, "graph": graph.build(b.game, v)}


@app.post("/api/analyze")
def api_analyze(b: GameBody):
    if (bad := _bad_game(b.game)):
        return bad
    return pipeline.analyze(b.game, run_tag="ui")


@app.post("/api/modify")
def api_modify(b: ModifyBody):
    if (bad := _bad_game(b.game)):
        return bad
    return pipeline.modify(b.game, b.request, auto_retry=b.auto_retry, run_tag="ui")


@app.post("/api/apply_fix")
def api_apply_fix(b: FixBody):
    if (bad := _bad_game(b.original, b.failed_game)):
        return bad
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
    if (bad := _bad_game(b.game)):
        return bad
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
    if (bad := _bad_game(b.game)):
        return bad
    """수정된 게임 저장(시연 뒤 확인용). 로컬은 data/games/edited_game.json, 배포는 Supabase saved_games."""
    return storage.save_game(b.game)
