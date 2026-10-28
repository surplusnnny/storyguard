"""평가 실험: 모델 × 요청 20개 × 자동 재시도 켜기/끄기.

결과는 eval/results/<시각>/ 에 저장한다.
- results.csv : 요청 1건 = 1행 (발표 숫자의 원본)
- summary.csv : 모델 × 재시도 조건별 집계
- chart.png   : summary.csv에서 그린 막대그래프
- summary.md  : 숫자마다 어느 열에서 계산했는지 적은 요약

사용:
  python tools/evaluate.py --show                  평가 세트를 표로 보여 주고 끝냄(실험 전 사람 확인용)
  python tools/evaluate.py --models a,b --retry both
  python tools/evaluate.py --ids r01,r02 --retry on  일부만 실행

모의 모드(LLM_MODE=mock) 결과는 숫자에 [MOCK]이 붙으며 발표에 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, pipeline  # noqa: E402
from app.verifier import load_game  # noqa: E402

REQ_PATH = ROOT / "eval" / "requests.json"


# ------------------------------------------------------------ 의도 확인(요청한 변경이 최종 게임에 있는가)
def _by_id(data, col, id_):
    return next((o for o in data.get(col, []) if o.get("id") == id_), None)


def _item_ids_named(data, name):
    return {i["id"] for i in data.get("items", []) if name in i.get("name", "")}


def check(data: dict, c: dict) -> bool:
    t = c["type"]
    if t == "npc_dialogue_contains":
        n = _by_id(data, "npcs", c["npc"])
        return bool(n) and any(c["text"] in line for line in n.get("dialogue", []))
    if t in ("quest_reward_has_name", "quest_reward_lacks_name"):
        q = _by_id(data, "quests", c["quest"])
        has = bool(q) and bool(set(q.get("reward_items", [])) & _item_ids_named(data, c["name"]))
        return has if t == "quest_reward_has_name" else (bool(q) and not has)
    if t == "event_exists_name":
        return any(c["name"] in e.get("name", "") for e in data.get("events", []))
    if t == "item_exists_name":
        return bool(_item_ids_named(data, c["name"]))
    if t == "npc_exists_name":
        return any(c["name"] in n.get("name", "") for n in data.get("npcs", []))
    if t == "meta_title":
        return (data.get("meta") or {}).get("title") == c["name"]
    if t == "ending_name":
        return (data.get("ending") or {}).get("name") == c["name"]
    if t == "quest_name":
        q = _by_id(data, "quests", c["quest"])
        return bool(q) and q.get("name") == c["name"]
    if t == "event_name":
        e = _by_id(data, "events", c["event"])
        return bool(e) and e.get("name") == c["name"]
    if t == "event_absent":
        return _by_id(data, "events", c["event"]) is None
    if t == "npc_absent":
        return _by_id(data, "npcs", c["npc"]) is None
    if t in ("area_connected", "area_not_connected"):
        a = _by_id(data, "areas", c["from"])
        conn = bool(a) and c["to"] in a.get("connections", [])
        return conn if t == "area_connected" else not conn
    if t == "area_requires_item_name":
        a = _by_id(data, "areas", c["area"])
        return bool(a) and bool(set(a.get("requires_items", [])) & _item_ids_named(data, c["name"]))
    if t == "event_requires_item_name":
        e = _by_id(data, "events", c["event"])
        return bool(e) and bool(set(e.get("requires_items", [])) & _item_ids_named(data, c["name"]))
    if t == "quest_requires_quest":
        q = _by_id(data, "quests", c["quest"])
        return bool(q) and c["requires"] in q.get("requires_quests", [])
    raise ValueError(f"알 수 없는 확인 종류: {t}")


def intent_ok(game: dict | None, checks: list[dict]) -> bool:
    return bool(game) and all(check(game, c) for c in checks)


# ------------------------------------------------------------ 실행
def run_one(game: dict, req: dict, model: str, retry: bool, tag: str) -> dict:
    t0 = time.perf_counter()
    res = pipeline.modify(game, req["request"], auto_retry=retry, run_tag=tag)
    elapsed = (time.perf_counter() - t0) * 1000
    first = res["attempts"][0] if res["attempts"] else {}
    first_v = first.get("verify") or {}
    llm_ms = sum(a["llm"]["latency_ms"] for a in res["attempts"] if a.get("llm"))
    llm_fail = sum(1 for a in res["attempts"] if a.get("llm") and not a["llm"]["ok"])
    final_game = res.get("final_game")
    return {
        "id": req["id"], "category": req["category"], "model": model, "retry": "on" if retry else "off",
        "status": res["status"],
        "modified": int(bool(first_v)),
        "first_reachable": int(bool(first_v.get("reachable"))),
        "first_unintended": int(bool(first_v.get("unintended_changes"))),
        "first_pass": int(bool(first_v.get("passed"))),
        "final_pass": int(res["status"] == "passed"),
        "intent_ok": int(intent_ok(final_game, req["checks"])),
        "success": int(res["status"] == "passed" and intent_ok(final_game, req["checks"])),
        "attempts": len(res["attempts"]),
        "llm_fail_calls": llm_fail,
        "llm_ms": round(llm_ms, 1), "total_ms": round(elapsed, 1),
        "sources": "+".join(res.get("sources", [])),
        "first_blocker": (first_v.get("blockers") or [{}])[0].get("type", "") if first_v else "",
    }


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    keys = sorted({(r["model"], r["retry"]) for r in rows})
    for model, retry in keys:
        rs = [r for r in rows if r["model"] == model and r["retry"] == retry]
        n = len(rs)
        risky = [r for r in rs if r["category"] == "risky"]
        out.append({
            "model": model, "retry": retry, "n": n,
            "first_pass_rate": round(sum(r["first_pass"] for r in rs) / n, 3),
            "final_pass_rate": round(sum(r["final_pass"] for r in rs) / n, 3),
            "success_rate": round(sum(r["success"] for r in rs) / n, 3),
            "risky_first_break_rate": (round(sum(1 - r["first_reachable"] for r in risky_m) / len(risky_m), 3)
                                       if (risky_m := [r for r in risky if r["modified"]]) else ""),
            "modified_rate": round(sum(r["modified"] for r in rs) / n, 3),
            "unintended_rate": round(sum(r["first_unintended"] for r in rs) / n, 3),
            "avg_llm_ms": round(sum(r["llm_ms"] for r in rs) / n, 1),
            "llm_fail_calls": sum(r["llm_fail_calls"] for r in rs),
        })
    return out


def chart(summary: list[dict], path: Path, mock: bool):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ["Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"]:
        if any(f in x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False
    labels = [f"{s['model']}\n재시도 {'켬' if s['retry'] == 'on' else '끔'}" for s in summary]
    first = [s["first_pass_rate"] * 100 for s in summary]
    final = [s["success_rate"] * 100 for s in summary]
    fig, ax = plt.subplots(figsize=(max(6, 2.2 * len(summary)), 4.2), dpi=150)
    x = range(len(summary))
    b1 = ax.bar([i - 0.2 for i in x], first, 0.4, label="LLM 1차 수정만", color="#A3AEC4")
    b2 = ax.bar([i + 0.2 for i in x], final, 0.4, label="검증 + 재시도 후 (의도 유지)", color="#2E9E4F")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.5, f"{b.get_height():.0f}%", ha="center", fontsize=9)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 110); ax.set_ylabel("엔딩 유지 비율 (%)")
    ax.set_title(("[MOCK - 발표에 쓰지 말 것] " if mock else "") + f"수정 요청 {summary[0]['n']}개 기준", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(config.models()) or "mock")
    ap.add_argument("--retry", choices=["on", "off", "both"], default="both")
    ap.add_argument("--ids", default="")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--force", action="store_true", help="reviewed=false여도 실행")
    args = ap.parse_args()

    spec = json.loads(REQ_PATH.read_text(encoding="utf-8"))
    reqs = spec["requests"]
    if args.ids:
        want = set(args.ids.split(","))
        reqs = [r for r in reqs if r["id"] in want]
    if args.show:
        for r in reqs:
            print(f"{r['id']}  [{r['category']}]  {r['request']}\n      위험: {r['risk']}\n      확인: {json.dumps(r['checks'], ensure_ascii=False)}")
        print(f"\n총 {len(reqs)}개. 확인했으면 eval/requests.json의 reviewed를 true로 바꾸세요.")
        return
    if not spec.get("reviewed") and not args.force:
        print("eval/requests.json의 reviewed가 false입니다. --show로 평가 세트를 먼저 확인하고 reviewed를 true로 바꾸세요.")
        sys.exit(2)

    mock = config.mode() == "mock"
    game = load_game(ROOT / "data" / "games" / "sample_game.json")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "eval" / "results" / (stamp + ("-mock" if mock else ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    retries = {"on": [True], "off": [False], "both": [False, True]}[args.retry]
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    rows = []
    for model in models:
        if not mock:
            os.environ["LLM_MODELS"] = model
            os.environ["LLM_NO_FALLBACK"] = "1"
        for retry in retries:
            for r in reqs:
                row = run_one(game, r, model, retry, tag=f"eval-{stamp}")
                rows.append(row)
                print(f"{model:>24} 재시도{'켬' if retry else '끔'} {r['id']}: {row['status']:<10} 1차 {'통과' if row['first_pass'] else '실패'} "
                      f"최종 {'성공' if row['success'] else '실패'} ({row['llm_ms']}ms, {row['sources']})", flush=True)

    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    summary = summarize(rows)
    with open(out_dir / "summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys())); w.writeheader(); w.writerows(summary)
    chart(summary, out_dir / "chart.png", mock)
    rel = out_dir.relative_to(ROOT)
    lines = [f"# 평가 결과 {stamp}{' [MOCK - 발표에 쓰지 말 것]' if mock else ''}", "",
             f"원본: `{rel}/results.csv` ({len(rows)}행), 집계: `{rel}/summary.csv`", "",
             "| 모델 | 재시도 | 1차 통과율 | 최종 성공률(의도 유지) | 위험 요청 1차 파손율 | 요청하지 않은 변경 비율 | 평균 LLM 시간 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for s in summary:
        lines.append(f"| {s['model']} | {s['retry']} | {s['first_pass_rate']:.0%} | {s['success_rate']:.0%} | "
                     f"{s['risky_first_break_rate'] if s['risky_first_break_rate'] == '' else format(s['risky_first_break_rate'], '.0%')} | "
                     f"{s['unintended_rate']:.0%} | {s['avg_llm_ms']}ms |")
    lines += ["", "계산 방법 (results.csv의 열)",
              "- 1차 통과율 = first_pass 평균 (LLM이 처음 고친 게임이 엔딩 도달 가능하고 요청하지 않은 변경이 없음)",
              "- 최종 성공률 = success 평균 (최종 통과 AND 요청한 변경이 최종 게임에 남아 있음, checks로 확인)",
              "- 위험 요청 1차 파손율 = category=risky이고 modified=1인 행의 (1 - first_reachable) 평균 (수정을 거부·질문한 요청은 뺌)",
              "- 수정 시도율(summary.csv의 modified_rate) = modified 평균",
              "- 요청하지 않은 변경 비율 = first_unintended 평균",
              "- 평균 LLM 시간 = llm_ms 평균 (요청 1건의 모든 LLM 호출 합)"]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\n저장: {rel}")


if __name__ == "__main__":
    main()
