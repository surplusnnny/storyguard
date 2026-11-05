"""Vercel 진입점. Vercel은 루트의 main.py에서 `app`을 찾는다(Vercel FastAPI 문서).
app/server.py가 상대 import(from . import ...)를 쓰므로 패키지로 불러온다. 로컬 실행은 run.bat 그대로."""
from app.server import app

__all__ = ["app"]
