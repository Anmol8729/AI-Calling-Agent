@echo off
title Clarivo Voice Agent
cd /d "%~dp0agent"
if exist "%~dp0agent\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0agent\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
)
echo ========================================
echo   Starting Clarivo Voice Agent
echo ========================================
call "%PYTHON_EXE%" main.py dev
pause
