"""설정. .env 파일에서 읽는다. .env는 깃에 올리지 않는다(.gitignore)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RECORDINGS = DATA / "recordings"
DB_PATH = DATA / "llm_calls.db"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():  # 메모장의 BOM 대응
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(ROOT / ".env")


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def mode() -> str:
    """live: 실시간 호출 / mock: 서버 없이 규칙 기반 모의 응답 / replay: 저장된 결과만 사용 /
    replay_first: 저장된 결과가 있으면 쓰고 없으면 실시간 호출(성공하면 저장)"""
    return get("LLM_MODE", "mock").lower()


def provider() -> str:
    """vllm: GPU 서버(OpenAI 호환) / anthropic: Claude API. 기본은 vllm(예전 동작 그대로)."""
    return "anthropic" if get("LLM_PROVIDER", "vllm").lower() == "anthropic" else "vllm"


def models() -> list[str]:
    return [m.strip() for m in get("LLM_MODELS", "").split(",") if m.strip()]


def base_url() -> str:
    return get("LLM_BASE_URL", "http://localhost:8000").rstrip("/")


def api_root() -> str:
    """OpenAI 호환 API의 기준 주소. /v1이나 /openai로 끝나면(Gemini 등) /v1을 또 붙이지 않는다."""
    b = base_url()
    return b if b.endswith(("/v1", "/openai")) else b + "/v1"


def is_openai() -> bool:
    """LLM_BASE_URL이 OpenAI(api.openai.com)인지. 그러면 gpt-5 계열에 맞는 요청 형식을 쓴다."""
    return "api.openai.com" in base_url()


def reasoning_effort() -> str:
    """OpenAI 추론 모델의 생각 양(minimal/low/medium/high). 낮을수록 빠르고 싸다."""
    return get("LLM_REASONING_EFFORT", "low")


def api_key() -> str:
    return get("LLM_API_KEY", "EMPTY")


def timeout() -> float:
    return float(get("LLM_TIMEOUT", "30"))


def retry_waits() -> list[float]:
    return [float(x) for x in get("LLM_RETRY_WAITS", "2,4").split(",") if x.strip()]


def replay_fallback() -> bool:
    return get("LLM_REPLAY_FALLBACK", "1") == "1"


def json_mode() -> bool:
    """vLLM의 response_format={"type":"json_object"} 사용 여부. 서버가 지원하지 않으면 0으로 둔다."""
    return get("LLM_JSON_MODE", "1") == "1"


def max_tokens() -> int:
    return int(get("LLM_MAX_TOKENS", "4096"))


# ------------------------------------------------------------------ 기록 저장소 (app/storage.py)
def supabase_url() -> str:
    """Supabase 프로젝트 주소. 비어 있으면 Supabase를 쓰지 않는다."""
    return get("SUPABASE_URL", "").rstrip("/")


def supabase_secret_key() -> str:
    """서버 전용 secret 키(sb_secret_...). 브라우저 코드(app/static)에는 절대 넣지 않는다."""
    return get("SUPABASE_SECRET_KEY", "")


def supabase_timeout() -> float:
    return float(get("SUPABASE_TIMEOUT", "2"))


def request_budget() -> float:
    """요청 하나(수정→재수정→설명)의 전체 시간 한도(초). 0이면 끔. Vercel Hobby는 함수 최대 300초라 240을 권장."""
    return float(get("LLM_REQUEST_BUDGET", "0") or 0)


def on_vercel() -> bool:
    """Vercel 함수에서 실행 중인지. Vercel은 런타임에 VERCEL=1을 넣는다(Preview 배포에서 확인 예정)."""
    return get("VERCEL", "") == "1"
