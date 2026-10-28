@echo off
chcp 65001 >nul
cd /d %~dp0
set PYTHONUTF8=1
echo 브라우저에서 http://localhost:8501 을 여세요. 끄려면 Ctrl+C
start "" http://localhost:8501
.venv\Scripts\python -m uvicorn app.server:app --host 127.0.0.1 --port 8501
