@echo off
title Clarivo Backend API
cd /d "%~dp0"
set PYTHONPATH=%~dp0
echo ========================================
echo   Starting Clarivo Backend API (Uvicorn)
echo   URL: http://127.0.0.1:8000
echo   API Docs: http://127.0.0.1:8000/docs
echo ========================================
call "%~dp0.venv\Scripts\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
pause
