"""시연 시나리오를 처음부터 끝까지 자동으로 돌려 단계마다 통과/실패를 표로 보여 준다.

사용:
  python tools/demo_check.py                 서버 없이 바로 실행(현재 .env 모드 사용)
  python tools/demo_check.py --url http://localhost:8501   실행 중인 서버에 대해 확인
  python tools/demo_check.py --repeat 5      5번 연속

실패하면 원인을 추측하지 않고 오류 원문을 그대로 출력한다. 하나라도 실패하면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEMO = "두 번째 퀘스트 보상을 황금 열쇠에서 마법 지팡이로 바꿔 줘"


class Client:
    def __init__(self, url: str | None):
        if url:
            import httpx
            self.c = httpx.Client(base_url=url, timeout=180)
        else:
            from fastapi.testclient import TestClient
            from app.server import app
            self.c = TestClient(app)

    def get(self, p):
        r = self.c.get(p); r.raise_for_status(); return r.json()

    def post(self, p, body):
        r = self.c.post(p, json=body); r.raise_for_status(); return r.json()


def run_once(cli: Client) -> list[dict]:
    rows = []

    def step(name, fn):
        t0 = time.perf_counter()
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, "오류 원문: " + "".join(traceback.format_exception_only(type(exc), exc)).strip()
        rows.append({"step": name, "ok": ok, "ms": round((time.perf_counter() - t0) * 1000), "detail": detail})
        return ok

    ctx: dict = {}

    def s1():
        g = cli.get("/api/game/sample_game")
        ctx["game"] = g["game"]
        return g["verify"]["passed"], f"원본 게임 경로 {len(g['verify']['path'])}단계"

    def s2():
        r = cli.post("/api/modify", {"game": ctx["game"], "request": DEMO, "auto_retry": False})
        ctx["res"] = r
        if r["status"] != "failed":
            return False, f"기대: failed, 실제: {r['status']} {r.get('question') or r['attempts'][0]['llm'].get('error_message', '')}"
        b = r["verify"]["blockers"][0]
        ok = b["target"] == "area:final_dungeon" and b["requirement"] == "item:golden_key"
        return ok, f"막힌 지점 {b['target']} / {b['requirement']} (출처 {', '.join(r['sources'])})"

    def s3():
        ex = ctx["res"]["explanation"]
        ok = bool(ex and ex.get("problem") and len(ex.get("fixes", [])) >= 2)
        return ok, f"설명 출처 {ex.get('source') if ex else '-'}, 수정안 {len(ex.get('fixes', [])) if ex else 0}개"

    def s4():
        r0 = ctx["res"]
        fix = r0["explanation"]["fixes"][0]
        r = cli.post("/api/apply_fix", {"original": ctx["game"], "request": DEMO, "failed_game": r0["final_game"],
                                         "fix": fix, "intent_paths": r0["intent_paths"], "declared": r0["declared"]})
        ctx["fixed"] = r
        intent = r["attempts"][0].get("intent", {})
        return r["status"] == "passed" and intent.get("kept", False), f"'{fix['title']}' 적용 → {r['status']}, 요청 유지 {intent.get('kept')}"

    def s5():
        g = ctx["fixed"]["final_game"]
        st = None
        for p in ctx["fixed"]["verify"]["path"]:
            out = cli.post("/api/play", {"game": g, "state": st, "action": p["action"]})
            st = out["state"]
        return out["ending"], f"플레이 {len(ctx['fixed']['verify']['path'])}번 행동 후 엔딩 {out['ending']}"

    def s6():
        r = cli.post("/api/modify", {"game": ctx["game"], "request": DEMO, "auto_retry": True})
        return r["status"] == "passed", f"자동 재시도 {len(r['attempts']) - 1}회 → {r['status']}"

    for name, fn in [("1. 원본 게임 불러오기", s1), ("2. 시연 요청: 엔딩이 막히는지", s2),
                     ("3. 원인 설명과 수정안", s3), ("4. 수정안 적용 후 재검증", s4),
                     ("5. 수정한 게임을 엔딩까지 플레이", s5), ("6. 자동 재시도로 통과", s6)]:
        if not step(name, fn) and name.startswith(("1", "2", "4")):
            break  # 뒤 단계가 앞 단계 결과를 쓰므로 여기서 멈춘다
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()
    cli = Client(args.url or None)
    try:
        st = cli.get("/api/status")
        print(f"모드: {st['mode']}  모델: {', '.join(st['models']) or '-'}  저장된 결과: {st['recordings']}개\n")
    except Exception as exc:  # noqa: BLE001
        print(f"서버에 연결하지 못함: {exc}"); sys.exit(1)
    all_ok = True
    for i in range(args.repeat):
        rows = run_once(cli)
        ok = all(r["ok"] for r in rows) and len(rows) == 6
        all_ok &= ok
        print(f"[{i + 1}회차] {'성공' if ok else '실패'}")
        for r in rows:
            print(f"  {'✓' if r['ok'] else '✗'} {r['step']:<28} {r['ms']:>6}ms  {r['detail']}")
        print()
    print("전체 결과:", "모두 성공" if all_ok else "실패 있음")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
