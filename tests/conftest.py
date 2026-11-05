import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LLM_MODE", "mock")


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """시험이 실제 기록 파일(data/recordings, llm_calls.db)을 건드리지 않게 한다."""
    from app import config
    monkeypatch.setattr(config, "RECORDINGS", tmp_path / "recordings")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "calls.db")
    monkeypatch.setattr(config, "DATA", tmp_path)
    # .env에 실제 Supabase 키가 있어도 시험이 진짜 DB에 쓰지 않게 한다. Vercel 표시도 끈다.
    for key in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "VERCEL", "LLM_REQUEST_BUDGET"):
        monkeypatch.delenv(key, raising=False)
    yield


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def fake_server():
    import uvicorn
    os.environ["FAKE_SLOW_SEC"] = "3"
    from tools.fake_vllm import app
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


@pytest.fixture
def live(monkeypatch, fake_server):
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("LLM_BASE_URL", fake_server)
    monkeypatch.setenv("LLM_RETRY_WAITS", "0")
    monkeypatch.setenv("LLM_TIMEOUT", "1.5")
    monkeypatch.setenv("LLM_REPLAY_FALLBACK", "1")
    return fake_server
