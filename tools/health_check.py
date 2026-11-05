"""GPU 서버(vLLM) 연결 시험. 대회장에서 .env를 채운 직후에 실행한다.

1. /v1/models 로 서버가 가진 모델 목록 확인
2. .env의 LLM_MODELS 각각에 실제 수정 프롬프트(시연 요청)를 보내
   - JSON으로만 답하는지, modified_game이 들어 있는지, 응답 시간, 오류 원인
3. 결과를 표로 출력하고 data/health_<시각>.json에 저장

값마다 괄호에 어떤 확인으로 얻은 값인지 적는다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LLM_MODE", "live")

from app import config, llm_client, prompts  # noqa: E402
from app.verifier import load_game, verify  # noqa: E402

DEMO = "두 번째 퀘스트 보상을 황금 열쇠에서 마법 지팡이로 바꿔 줘"


def main():
    if config.mode() != "live":
        print(f"LLM_MODE={config.mode()} 입니다. GPU 서버를 시험하려면 .env에서 LLM_MODE=live로 바꾸세요.")
        sys.exit(2)
    where = llm_client.ANTHROPIC_URL if config.provider() == "anthropic" else config.base_url()
    print(f"서버: {where}  (제공자: {config.provider()})")
    print(f"모델: {', '.join(config.models()) or '(비어 있음)'}  (.env LLM_MODELS)\n")
    report = {"base_url": where, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "models": []}
    try:
        ids = llm_client.list_models()
        print("서버가 가진 모델 (GET /v1/models 결과):")
        for i in ids:
            print("  -", i)
        report["server_models"] = ids
    except Exception as exc:  # noqa: BLE001
        print(f"GET /v1/models 실패 (오류 원문): {exc}")
        report["server_models_error"] = str(exc)
        ids = []
    print()
    game = load_game(ROOT / "data" / "games" / "sample_game.json")
    os.environ["LLM_NO_FALLBACK"] = "1"
    os.environ["LLM_REPLAY_FALLBACK"] = "0"
    rows = []
    for m in config.models():
        t0 = time.perf_counter()
        r = llm_client.call_json("modify", prompts.modify_messages(game, DEMO), models=[m], run_tag="health")
        ms = round((time.perf_counter() - t0) * 1000)
        has_game = bool(r.ok and isinstance((r.data or {}).get("modified_game"), dict))
        verdict = ""
        if has_game:
            v = verify(r.data["modified_game"], game, [c.get("path", "") for c in (r.data.get("plan") or {}).get("change", [])])
            verdict = "엔딩 막힘 감지" if not v["reachable"] else "엔딩 유지(보완까지 함)"
            if v["schema_errors"]:
                verdict = f"형식 오류 {len(v['schema_errors'])}건"
        row = {"model": m, "in_server_list": m in ids, "json_ok": r.ok, "modified_game": has_game,
               "verify": verdict, "ms": ms, "tries": len(r.tries), "error_kind": r.error_kind,
               "error": (r.error_message or "")[:200], "tokens": r.prompt_tokens + r.completion_tokens}
        rows.append(row)
    print(f"{'모델':<40} {'목록에 있음':<8} {'JSON':<6} {'게임 수정':<8} {'검증 결과':<16} {'시간':>7} 오류")
    for r in rows:
        print(f"{r['model']:<40} {str(r['in_server_list']):<8} {str(r['json_ok']):<6} {str(r['modified_game']):<8} "
              f"{r['verify']:<16} {r['ms']:>6}ms {r['error_kind']} {r['error']}")
    print("\n(목록에 있음: /v1/models 결과, JSON/게임 수정: 시연 요청 1회 호출 결과, 검증 결과: verifier.py 판정, 시간: 실측)")
    report["models"] = rows
    out = config.DATA / f"health_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {out.relative_to(ROOT)}")
    sys.exit(0 if rows and all(r["json_ok"] and r["modified_game"] for r in rows) else 1)


if __name__ == "__main__":
    main()
