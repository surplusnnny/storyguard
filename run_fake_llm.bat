@echo off
chcp 65001 >nul
cd /d %~dp0
set PYTHONUTF8=1
echo 가짜 vLLM 서버(연습용): http://127.0.0.1:8001  모델: fake-ok, fake-think, fake-bad-json, fake-429, fake-500, fake-slow
.venv\Scripts\python tools\fake_vllm.py
