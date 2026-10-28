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
    """live: GPU 서버 호출 / mock: 서버 없이 규칙 기반 모의 응답 / replay: 저장된 결과만 사용"""
    return get("LLM_MODE", "mock").lower()


def models() -> list[str]:
    return [m.strip() for m in get("LLM_MODELS", "").split(",") if m.strip()]


def base_url() -> str:
    return get("LLM_BASE_URL", "http://localhost:8000").rstrip("/")


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
