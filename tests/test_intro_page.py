"""AI 심사자가 자바스크립트 없이 HTML 글자만 읽어도 서비스를 이해할 수 있어야 한다."""
import re

from fastapi.testclient import TestClient

from app.server import app


def html() -> str:
    r = TestClient(app).get("/")
    assert r.status_code == 200
    return r.text


def text_only(s: str) -> str:
    s = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))


def test_head_describes_the_service():
    h = html()
    assert re.search(r'<meta name="description" content="[^"]{30,}"', h)
    assert re.search(r"<title>[^<]*StoryGuard[^<]+</title>", h)


def test_intro_explains_roles_without_javascript():
    t = text_only(html())
    for must in ["AI가 고치고", "알고리즘", "엔딩", "game.json", "요청하지 않은 변경", "저장된 결과", "교내 GPU(틸론)"]:
        assert must in t, must


def test_demo_summary_shows_rejections_and_pass():
    t = text_only(html())
    assert "수정안 3개" in t and "거절" in t and "통과" in t
    assert "gpt-5.4-mini" in t


def test_noscript_message_exists():
    assert re.search(r"<noscript>[\s\S]{10,}</noscript>", html())


def test_no_secrets_in_html():
    h = html()
    for bad in ("sk-proj-", "sb_secret_", "sk-ant-", "AIza"):
        assert bad not in h
