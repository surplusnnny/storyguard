@echo off
chcp 65001 >nul
cd /d %~dp0
echo [1/3] 가상환경 만들기
py -3 -m venv .venv || python -m venv .venv
echo [2/3] 패키지 설치
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
if not exist .env copy .env.example .env >nul
echo [3/3] 시험 실행
set PYTHONUTF8=1
.venv\Scripts\python -m pytest -q
echo.
echo 준비 끝. run.bat 으로 실행하세요.
pause
